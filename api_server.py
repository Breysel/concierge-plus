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
    SMALLTALK_RULES_FIRST_TURN,
    SMALLTALK_RULES_ONGOING,
    build_reco_prompt,
    build_smalltalk_prompt,
)
from backend.telemetry import (
    get_log_dir,
    truncate,
    append_csv,
    append_jsonl,
    extract_urls_from_markdown,
)
from backend.llm import call_anthropic_writer, DEFAULT_ROUTER_MODEL, DEFAULT_WRITER_MODEL
from backend.routing import (
    build_effective_query,
    format_recent,
    route_message,
    should_smalltalk,
)

VERSION = "router-v2"
_START_TIME = time.time()

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
    debug: Optional[bool] = None


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
    return {
        "ok": True,
        "version": VERSION,
        "catalog_loaded": catalog.is_catalog_loaded(),
        "uptime_seconds": int(time.time() - _START_TIME),
    }


@app.on_event("startup")
def preload_catalog() -> None:
    if os.getenv("PRELOAD_CATALOG", "1") == "0":
        return
    try:
        catalog_path = os.getenv("CATALOG_CSV_PATH")
        if catalog_path and catalog_path.startswith(("http://", "https://")):
            catalog.ensure_catalog_downloaded(catalog_path)
            local_path = catalog.get_catalog_local_path(catalog_path)
        else:
            local_path = catalog.get_catalog_local_path()
        catalog.load_catalog(local_path)
    except Exception as exc:
        print(f"Warning: catalog preload failed: {exc}")


def _now() -> float:
    return time.time()


def _conv_gc() -> None:
    with _CONV_LOCK:
        now = _now()
        dead = [
            cid
            for cid, v in _CONV_STORE.items()
            if now - float(v.get("updated_at", 0)) > _CONV_TTL_SEC
        ]
        for cid in dead:
            _CONV_STORE.pop(cid, None)
        if len(_CONV_STORE) > _CONV_MAX_CONVS:
            items = sorted(
                _CONV_STORE.items(), key=lambda kv: float(kv[1].get("updated_at", 0))
            )
            for cid, _ in items[: max(0, len(_CONV_STORE) - _CONV_MAX_CONVS)]:
                _CONV_STORE.pop(cid, None)


def get_or_create_conversation(conversation_id: Optional[str]) -> str:
    _conv_gc()
    with _CONV_LOCK:
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


def call_anthropic_env(
    system: str, messages: List[Dict[str, str]], model: Optional[str] = None
) -> str:
    reply, error = call_anthropic_writer(system, messages, model=model)
    if error:
        raise HTTPException(status_code=500, detail=error)
    return reply or ""


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    start_time = time.perf_counter()
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    request_history = request.history or []
    debug_enabled = request.debug is True or os.getenv("DEBUG", "").lower() == "true"

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
    is_first_turn = len(effective_history) == 0
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
    model_name = os.getenv("CLAUDE_WRITER_MODEL") or os.getenv("CLAUDE_MODEL") or DEFAULT_WRITER_MODEL
    conversation_context = format_recent(history_for_context)

    router_model = os.getenv("CLAUDE_ROUTER_MODEL", DEFAULT_ROUTER_MODEL)
    writer_model = model_name

    router_payload, router_raw_text, router_used, router_ms = route_message(
        message,
        effective_history,
        conversation_context=conversation_context,
    )

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
            writer_start = time.perf_counter()
            assistant_reply = call_anthropic_env(
                system, [{"role": "user", "content": prompt}], model=model_name
            )
            writer_ms = int((time.perf_counter() - writer_start) * 1000)
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
            search_start = time.perf_counter()
            try:
                candidates = catalog.search(
                    {
                        "query": effective_search_query,
                        "mode": strategy,
                        "filters": search_filters,
                        "rank_by": rank_by,
                        "limit": 12,
                    }
                )
            except FileNotFoundError:
                assistant_reply = (
                    "I'm having trouble accessing the music library right now. "
                    "Try again in a moment?"
                )
                candidates = []
            catalog_search_ms = int((time.perf_counter() - search_start) * 1000)

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
                writer_start = time.perf_counter()
                assistant_reply = call_anthropic_env(
                    system, [{"role": "user", "content": prompt}], model=model_name
                )
                writer_ms = int((time.perf_counter() - writer_start) * 1000)
    except Exception as exc:
        error_detail = f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc(limit=5)}"
        print(f"🔴 ERROR in /chat: {error_detail}")
        latency_ms = int((time.perf_counter() - start_time) * 1000)
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

    total_ms = int((time.perf_counter() - start_time) * 1000)
    print(
        f"chat timings total={total_ms}ms router={router_ms}ms search={catalog_search_ms}ms "
        f"writer={writer_ms}ms router_used={router_used}"
    )
    if router_used:
        print(f"[LLM] router={router_model}, writer={writer_model}")
    else:
        print(f"[LLM] router=unused, writer={writer_model}")

    response = ChatResponse(reply=assistant_reply or "", mode=mode, conversation_id=conversation_id)
    if debug_enabled:
        response.debug = {
            "used_catalog": used_catalog,
            "candidate_count": candidate_count,
            "timings_ms": {
                "router_ms": router_ms,
                "catalog_search_ms": catalog_search_ms,
                "writer_ms": writer_ms,
                "total_ms": total_ms,
            },
        }

    latency_ms = int((time.perf_counter() - start_time) * 1000)
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
