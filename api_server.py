import json
import os
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend import catalog
from backend.prompts import (
    SYSTEM_PROMPT,
    RECO_RULES,
    ROUTER_RULES,
    SMALLTALK_RULES_FIRST_TURN,
    SMALLTALK_RULES_ONGOING,
    build_reco_prompt,
    build_router_prompt,
    build_smalltalk_prompt,
)
from backend.telemetry import (
    get_log_dir,
    truncate,
    append_csv,
    append_jsonl,
    extract_urls_from_markdown,
)
from backend.llm import call_anthropic_router

VERSION = "router-v2"

_CONV_LOCK = threading.Lock()
_CONV_STORE: Dict[str, Dict[str, Any]] = {}
_CONV_TTL_SEC = 24 * 3600
_CONV_MAX_MSGS = 12
_CONV_MAX_CONVS = 500


class HistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[HistoryItem]] = None
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    mode: str
    debug: Optional[Dict[str, Any]] = None
    conversation_id: Optional[str] = None


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "version": VERSION}


def _now() -> float:
    return time.time()


def _conv_gc() -> None:
    now = _now()
    dead = [
        cid
        for cid, v in _CONV_STORE.items()
        if now - float(v.get("updated_at", 0)) > _CONV_TTL_SEC
    ]
    for cid in dead:
        _CONV_STORE.pop(cid, None)
    if len(_CONV_STORE) > _CONV_MAX_CONVS:
        items = sorted(_CONV_STORE.items(), key=lambda kv: float(kv[1].get("updated_at", 0)))
        for cid, _ in items[: max(0, len(_CONV_STORE) - _CONV_MAX_CONVS)]:
            _CONV_STORE.pop(cid, None)


def get_or_create_conversation(conversation_id: Optional[str]) -> str:
    with _CONV_LOCK:
        _conv_gc()
        cid = conversation_id or str(uuid.uuid4())
        if cid not in _CONV_STORE:
            _CONV_STORE[cid] = {"history": [], "updated_at": _now(), "turn_index": 0}
        return cid


def set_history(cid: str, history: List[Dict[str, str]]) -> None:
    clipped = history[-_CONV_MAX_MSGS:] if history else []
    user_turns = sum(1 for item in clipped if item.get("role") == "user")
    with _CONV_LOCK:
        _CONV_STORE[cid] = {
            "history": clipped,
            "updated_at": _now(),
            "turn_index": user_turns,
        }


def get_history(cid: str) -> List[Dict[str, str]]:
    with _CONV_LOCK:
        v = _CONV_STORE.get(cid) or {}
        return list(v.get("history") or [])


def append_turn(cid: str, role: str, content: str) -> None:
    content = (content or "").strip()
    if not content:
        return
    with _CONV_LOCK:
        v = _CONV_STORE.setdefault(cid, {"history": [], "updated_at": _now(), "turn_index": 0})
        v["history"].append({"role": role, "content": content})
        v["history"] = v["history"][-_CONV_MAX_MSGS:]
        v["updated_at"] = _now()
        if role == "user":
            v["turn_index"] = int(v.get("turn_index", 0)) + 1


def get_turn_index(cid: str) -> int:
    with _CONV_LOCK:
        v = _CONV_STORE.get(cid) or {}
        return int(v.get("turn_index", 0))


def infer_filters(text: str) -> Dict[str, Any]:
    lowered = text.lower()

    filters: Dict[str, Any] = {}

    exclude_genres = []
    if "no opera" in lowered or "without opera" in lowered:
        exclude_genres.append("opera")
    if any(x in lowered for x in ["no vocals", "no singing", "instrumental only", "no choir"]):
        exclude_genres += ["opera", "vocal", "choral"]
    if exclude_genres:
        filters["exclude_genres"] = list(dict.fromkeys(exclude_genres))

    instrument_words = {
        "piano": "piano",
        "violin": "violin",
        "cello": "cello",
        "clarinet": "clarinet",
        "flute": "flute",
        "organ": "organ",
        "guitar": "guitar",
        "trumpet": "trumpet",
    }
    requested_instruments = [v for k, v in instrument_words.items() if k in lowered]
    if requested_instruments:
        filters["soloist_instruments"] = requested_instruments

    if any(x in lowered for x in ["atmos", "dolby", "spatial", "immersive"]):
        filters["is_atmos"] = True
    return filters


def infer_mode_and_filters(text: str) -> Dict[str, Any]:
    return {
        "mode": "auto",
        "filters": infer_filters(text),
    }


def should_smalltalk(text: str, history: List[Dict[str, str]]) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False

    smalltalk_triggers = [
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "help",
        "what can you do",
        "who are you",
    ]
    reco_intent = [
        "something funny",
        "something dark",
        "something calm",
        "recommend",
        "give me",
        "music for",
        "suggest",
    ]

    if any(phrase in lowered for phrase in reco_intent):
        return False

    return any(phrase in lowered for phrase in smalltalk_triggers)


def should_smalltalk_fast(message: str, history: List[Dict[str, str]]) -> bool:
    lowered = (message or "").strip().lower()
    if not lowered:
        return False
    smalltalk_only = [
        "hello",
        "hi",
        "hey",
        "thanks",
        "thx",
        "who are you",
        "help",
        "what can you do",
    ]
    reco_intent = [
        "something funny",
        "something dark",
        "something calm",
        "give me",
        "recommend",
        "music for",
        "make it",
        "bach",
        "mozart",
        "beethoven",
    ]
    if any(phrase in lowered for phrase in reco_intent):
        return False
    return any(phrase in lowered for phrase in smalltalk_only)


def should_use_router(message: str, history: List[Dict[str, str]]) -> bool:
    lowered = (message or "").strip().lower()
    if not lowered:
        return False
    if should_smalltalk_fast(message, history):
        return False

    anchors = [
        "bach",
        "mozart",
        "beethoven",
        "chopin",
        "mahler",
        "piano",
        "violin",
        "cello",
        "symphony",
        "concerto",
        "opera",
        "quartet",
        "requiem",
        "orchestra",
        "choral",
    ]
    explicit_modes = [
        "atmos",
        "dolby",
        "spatial",
        "hidden gem",
        "deep dive",
        "obscure",
        "underrated",
        "study",
        "focus",
        "sleep",
        "relax",
        "calm",
        "dark",
        "funny",
        "energ",
    ]
    refinement_phrases = [
        "darker",
        "calmer",
        "funnier",
        "more like that",
        "similar",
        "another",
        "continue",
        "less opera",
        "no vocals",
    ]

    if len(history) == 0 and len(lowered.split()) <= 6 and any(a in lowered for a in anchors):
        return False
    if any(m in lowered for m in explicit_modes):
        return False
    if len(history) > 0 and len(lowered.split()) <= 5 and any(p in lowered for p in refinement_phrases):
        return True
    return False


def fast_route(message: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    lowered = (message or "").strip().lower()
    filters = {
        "epochs": [],
        "genres": [],
        "exclude_genres": [],
        "soloist_instruments": [],
        "is_atmos": None,
        "min_unique_users": None,
    }
    strategy = "gateway"
    rank_by = "score_poplite"

    if any(x in lowered for x in ["atmos", "dolby", "spatial"]):
        strategy = "atmos"
        filters["is_atmos"] = True
        rank_by = "score_poplite"
    elif any(x in lowered for x in ["hidden gem", "deep dive", "obscure", "underrated"]):
        strategy = "deep_dive"
        rank_by = "score_hidden_gem"
        filters["min_unique_users"] = 0
    elif any(x in lowered for x in ["study", "focus", "sleep", "relax", "calm", "dark", "funny", "energ"]):
        strategy = "vibe"
        rank_by = "score_sticky"
    elif any(
        x in lowered for x in ["bach", "mozart", "beethoven", "chopin", "mahler", "tchaikovsky"]
    ):
        strategy = "performer_led"
        rank_by = "score_poplite"

    if "no opera" in lowered or "without opera" in lowered:
        filters["exclude_genres"] = ["opera"]
    if any(x in lowered for x in ["no vocals", "no singing", "instrumental only", "no choir"]):
        filters["exclude_genres"] = list(
            dict.fromkeys(filters["exclude_genres"] + ["opera", "vocal", "choral"])
        )

    return {
        "intent": "reco",
        "strategy": strategy,
        "query": message,
        "search_terms": [],
        "rank_by": rank_by,
        "filters": filters,
    }


def build_history_summary(history: List[Dict[str, str]], current_message: str) -> str:
    user_messages = [
        item.get("content")
        for item in history
        if item.get("role") == "user" and item.get("content")
    ]
    recent = user_messages[-2:]
    if not recent:
        return ""
    previous = "; ".join(recent)
    summary = f"User previously asked: {previous}. Now asks: {current_message}."
    return summary[:200]


def format_recent(
    history: List[Dict[str, str]], max_msgs: int = 6, max_chars_each: int = 350
) -> str:
    recent = history[-max_msgs:] if history else []
    lines = []
    for item in recent:
        role = (item.get("role") or "").upper()
        content = (item.get("content") or "").strip().replace("\n", " ")
        if content:
            lines.append(f"{role}: {content[:max_chars_each]}")
    return "\n".join(lines)


def _extract_json_object(text: str) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return None


def parse_router_response(text: str) -> Optional[Dict[str, Any]]:
    payload = _extract_json_object(text)
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def is_refinement_request(text: str) -> bool:
    lowered = (text or "").lower()
    refinement_phrases = [
        "something",
        "more",
        "another",
        "else",
        "different",
        "funnier",
        "funny",
        "darker",
        "dark",
        "calmer",
        "calm",
        "energetic",
        "intense",
        "like that",
        "similar",
    ]
    return any(phrase in lowered for phrase in refinement_phrases)


def get_anchor_from_history(history: List[Dict[str, str]]) -> str:
    for item in reversed(history):
        if item.get("role") == "user" and item.get("content"):
            return item.get("content", "").strip()
    return ""


def build_effective_query(
    base_query: str,
    search_terms: List[str],
    history: List[Dict[str, str]],
    strategy: str,
    user_message: str,
) -> str:
    query = (base_query or "").strip()
    if search_terms:
        query = f"{query} {' '.join(search_terms)}".strip()
    if strategy in {"vibe", "continue"} and is_refinement_request(user_message):
        anchor = get_anchor_from_history(history)
        if anchor and anchor.lower() not in query.lower():
            query = f"{query} {anchor}".strip()
    return query or user_message.strip()


def call_anthropic_env(
    system: str, messages: List[Dict[str, str]], model: Optional[str] = None
) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Missing ANTHROPIC_API_KEY in environment.",
        )

    try:
        from anthropic import Anthropic
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model or os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307"),
        temperature=0.2,
        system=system,
        messages=messages,
        max_tokens=700,
    )
    return response.content[0].text


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    start_time = time.time()
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    request_history = request.history or []
    debug_enabled = os.getenv("DEBUG", "").lower() == "true"

    conversation_id = get_or_create_conversation(request.conversation_id)
    request_id = str(uuid.uuid4())
    if request_history:
        effective_history = [
            {"role": item.role, "content": item.content} for item in request_history
        ]
        set_history(conversation_id, effective_history)
    else:
        effective_history = get_history(conversation_id)
    is_new_chat = len(effective_history) == 0
    is_first_turn = is_new_chat
    turn_index = get_turn_index(conversation_id) + 1
    log_dir = get_log_dir()
    jsonl_path = os.path.join(log_dir, "chat_events.jsonl")
    csv_path = os.path.join(log_dir, "chat_turns.csv")
    os.makedirs(log_dir, exist_ok=True)

    if is_new_chat:
        append_jsonl(
            jsonl_path,
            {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "event": "chat_start",
                "conversation_id": conversation_id,
                "request_id": request_id,
                "turn_index": turn_index,
                "user_message": message,
            },
        )

    append_turn(conversation_id, "user", message)
    history_for_context = get_history(conversation_id)

    mode = ""
    prompt_type = ""
    used_catalog = False
    candidate_count = 0
    top_candidates: List[Dict[str, Any]] = []
    router_decision: Optional[Dict[str, Any]] = None
    effective_search_query = ""
    catalog_search_ms = 0
    writer_ms = 0
    system_prompt = ""
    user_prompt = ""
    assistant_reply = ""
    error_detail = None
    model_name = os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307")
    conversation_context = format_recent(history_for_context)

    router_payload = None
    router_raw_text = ""
    router_used = False
    router_ms = 0

    if should_smalltalk_fast(message, effective_history):
        router_payload = {
            "intent": "smalltalk",
            "strategy": "gateway",
            "query": message,
            "rank_by": "score_poplite",
            "search_terms": [],
            "filters": {
                "epochs": [],
                "genres": [],
                "exclude_genres": [],
                "soloist_instruments": [],
                "is_atmos": None,
                "min_unique_users": None,
            },
        }
    else:
        if should_use_router(message, effective_history):
            router_used = True
            router_prompt = build_router_prompt(message, conversation_context=conversation_context)
            router_start = time.time()
            router_text, router_error = call_anthropic_router(
                ROUTER_RULES,
                [{"role": "user", "content": router_prompt}],
            )
            router_ms = int((time.time() - router_start) * 1000)
            if router_text and not router_error:
                router_raw_text = router_text
                router_payload = parse_router_response(router_text)

        if not router_payload:
            router_payload = fast_route(message, effective_history)

    router_decision = router_payload
    intent = (router_payload.get("intent") or "reco").strip().lower()
    strategy = (router_payload.get("strategy") or "gateway").strip().lower()
    rank_by = (router_payload.get("rank_by") or "score_poplite").strip()
    query = (router_payload.get("query") or message).strip()
    router_filters = router_payload.get("filters") or {}
    search_terms = router_payload.get("search_terms") or []

    if router_filters.get("is_atmos") is False:
        router_filters["is_atmos"] = None

    heuristic_smalltalk = should_smalltalk(message, effective_history)
    if intent == "smalltalk" and not heuristic_smalltalk:
        intent = "reco"

    try:
        if intent == "smalltalk":
            prompt_type = "smalltalk"
            mode = "smalltalk"
            effective_search_query = message
            prompt = build_smalltalk_prompt(
                message,
                conversation_context=conversation_context,
                is_first_turn=is_first_turn,
            )
            rules = (
                SMALLTALK_RULES_FIRST_TURN if is_first_turn else SMALLTALK_RULES_ONGOING
            )
            system = f"{SYSTEM_PROMPT}\n\n{rules}"
            system_prompt = system
            user_prompt = prompt
            writer_start = time.time()
            assistant_reply = call_anthropic_env(
                system, [{"role": "user", "content": prompt}], model=model_name
            )
            writer_ms = int((time.time() - writer_start) * 1000)
        else:
            mode = "reco"
            prompt_type = "reco"
            search_filters: Dict[str, Any] = {}
            if router_filters.get("epochs"):
                search_filters["epochs"] = router_filters.get("epochs")
            if router_filters.get("genres"):
                search_filters["genres"] = router_filters.get("genres")
            if router_filters.get("exclude_genres"):
                search_filters["exclude_genres"] = router_filters.get("exclude_genres")
            instruments = router_filters.get("soloist_instruments")
            if instruments:
                search_filters["soloist_instruments"] = instruments
            if router_filters.get("is_atmos") is True:
                search_filters["is_atmos"] = True
            if router_filters.get("min_unique_users") is not None:
                search_filters["min_unique_users"] = router_filters.get("min_unique_users")
            effective_search_query = build_effective_query(
                query,
                search_terms,
                effective_history,
                strategy,
                message,
            )
            search_start = time.time()
            try:
                candidates = catalog.search(
                    {
                        "query": effective_search_query,
                        "mode": strategy,
                        "filters": search_filters,
                        "rank_by": rank_by,
                        "limit": 30,
                    }
                )
            except FileNotFoundError:
                assistant_reply = (
                    "Catalog isn't loaded on this server yet — I can still chat, but "
                    "can't recommend albums until the catalog is connected."
                )
                candidates = []
            catalog_search_ms = int((time.time() - search_start) * 1000)

            candidate_count = len(candidates)
            used_catalog = candidate_count > 0
            top_candidates = [
                {
                    "album_title": item.get("album_title"),
                    "album_url": item.get("album_url"),
                    "score_poplite": item.get("score_poplite"),
                    "score_hidden_gem": item.get("score_hidden_gem"),
                    "score_sticky": item.get("score_sticky"),
                    "unique_users": item.get("unique_users"),
                }
                for item in candidates[:5]
            ]

            if candidates:
                history_summary = build_history_summary(effective_history, message)
                prompt = build_reco_prompt(
                    message,
                    candidates,
                    strategy=strategy,
                    rank_by=rank_by,
                    conversation_context=conversation_context or None,
                    history_summary=history_summary or None,
                )
                system = f"{SYSTEM_PROMPT}\n\n{RECO_RULES}"
                system_prompt = system
                user_prompt = prompt
                writer_start = time.time()
                assistant_reply = call_anthropic_env(
                    system, [{"role": "user", "content": prompt}], model=model_name
                )
                writer_ms = int((time.time() - writer_start) * 1000)
    except Exception as exc:
        error_detail = f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc(limit=5)}"
        latency_ms = int((time.time() - start_time) * 1000)
        append_jsonl(
            jsonl_path,
            {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "event": "chat_turn",
                "conversation_id": conversation_id,
                "request_id": request_id,
                "turn_index": turn_index,
                "user_message": message,
                "mode": mode,
                "used_catalog": used_catalog,
                "candidate_count": candidate_count,
                "top_candidates": top_candidates,
                "router_raw_text": truncate(router_raw_text),
                "router_decision": router_decision,
                "effective_search_query": effective_search_query,
                "rank_by": rank_by,
                "router_ms": router_ms,
                "catalog_search_ms": catalog_search_ms,
                "writer_ms": writer_ms,
                "total_ms": latency_ms,
                "prompt_type": prompt_type,
                "anthropic_model": model_name,
                "system_prompt_sent_to_claude": truncate(system_prompt),
                "user_prompt_sent_to_claude": truncate(user_prompt),
                "system_prompt_len": len(system_prompt),
                "user_prompt_len": len(user_prompt),
                "assistant_reply": assistant_reply,
                "latency_ms": latency_ms,
                "error": error_detail,
            },
        )
        append_csv(
            csv_path,
            header=[
                "ts_utc",
                "conversation_id",
                "turn_index",
                "user_message",
                "mode",
                "candidate_count",
                "reply_preview",
                "recommended_urls",
                "latency_ms",
                "error_flag",
            ],
            row=[
                datetime.now(timezone.utc).isoformat(),
                conversation_id,
                turn_index,
                message,
                mode,
                candidate_count,
                (assistant_reply or "")[:160],
                "|".join(extract_urls_from_markdown(assistant_reply)),
                latency_ms,
                True,
            ],
        )
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while generating a response.",
        )

    if assistant_reply:
        append_turn(conversation_id, "assistant", assistant_reply)

    total_ms = int((time.time() - start_time) * 1000)
    print(
        f"chat timings total={total_ms}ms router={router_ms}ms search={catalog_search_ms}ms "
        f"writer={writer_ms}ms router_used={router_used}"
    )

    response = ChatResponse(reply=assistant_reply or "", mode=mode, conversation_id=conversation_id)
    if debug_enabled:
        response.debug = {
            "used_catalog": used_catalog,
            "candidate_count": candidate_count,
            "router_ms": router_ms,
            "catalog_search_ms": catalog_search_ms,
            "writer_ms": writer_ms,
            "total_ms": total_ms,
        }

    latency_ms = int((time.time() - start_time) * 1000)
    append_jsonl(
        jsonl_path,
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": "chat_turn",
            "conversation_id": conversation_id,
            "request_id": request_id,
            "turn_index": turn_index,
            "user_message": message,
            "mode": mode,
            "used_catalog": used_catalog,
            "candidate_count": candidate_count,
            "top_candidates": top_candidates,
            "router_raw_text": truncate(router_raw_text),
            "router_decision": router_decision,
            "effective_search_query": effective_search_query,
            "rank_by": rank_by,
            "router_ms": router_ms,
            "catalog_search_ms": catalog_search_ms,
            "writer_ms": writer_ms,
            "total_ms": latency_ms,
            "prompt_type": prompt_type,
            "anthropic_model": model_name,
            "system_prompt_sent_to_claude": truncate(system_prompt),
            "user_prompt_sent_to_claude": truncate(user_prompt),
            "system_prompt_len": len(system_prompt),
            "user_prompt_len": len(user_prompt),
            "assistant_reply": assistant_reply,
            "latency_ms": latency_ms,
            "error": error_detail,
        },
    )
    append_csv(
        csv_path,
        header=[
            "ts_utc",
            "conversation_id",
            "turn_index",
            "user_message",
            "mode",
            "candidate_count",
            "reply_preview",
            "recommended_urls",
            "latency_ms",
            "error_flag",
        ],
        row=[
            datetime.now(timezone.utc).isoformat(),
            conversation_id,
            turn_index,
            message,
            mode,
            candidate_count,
            (assistant_reply or "")[:160],
            "|".join(extract_urls_from_markdown(assistant_reply)),
            latency_ms,
            False,
        ],
    )

    return response


@app.get("/admin/logs/chat_events.jsonl")
def download_chat_events(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
) -> FileResponse:
    admin_token = os.getenv("ADMIN_TOKEN")
    if not admin_token:
        raise HTTPException(status_code=404, detail="Not found")
    if x_admin_token != admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    path = os.path.join(get_log_dir(), "chat_events.jsonl")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Log not found")
    return FileResponse(path, media_type="application/jsonl")


@app.get("/admin/logs/chat_turns.csv")
def download_chat_turns(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
) -> FileResponse:
    admin_token = os.getenv("ADMIN_TOKEN")
    if not admin_token:
        raise HTTPException(status_code=404, detail="Not found")
    if x_admin_token != admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    path = os.path.join(get_log_dir(), "chat_turns.csv")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Log not found")
    return FileResponse(path, media_type="text/csv")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=port)
