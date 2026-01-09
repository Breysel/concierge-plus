import json
import os
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
def health() -> Dict[str, bool]:
    return {"ok": True}


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


def should_smalltalk(text: str, history: List[HistoryItem]) -> bool:
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


def build_history_summary(history: List[HistoryItem], current_message: str) -> str:
    user_messages = [item.content for item in history if item.role == "user" and item.content]
    recent = user_messages[-2:]
    if not recent:
        return ""
    previous = "; ".join(recent)
    summary = f"User previously asked: {previous}. Now asks: {current_message}."
    return summary[:200]


def build_conversation_context(history: List[HistoryItem]) -> str:
    recent = history[-6:]
    lines = []
    for item in recent:
        if item.content:
            lines.append(f"{item.role}: {item.content}")
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

    history = request.history or []
    history = history[-12:]
    debug_enabled = os.getenv("DEBUG", "").lower() == "true"

    conversation_id = request.conversation_id or str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    is_new_chat = len(history) == 0
    turn_index = 1 + sum(1 for item in history if item.role == "user")
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

    mode = ""
    prompt_type = ""
    used_catalog = False
    candidate_count = 0
    top_candidates: List[Dict[str, Any]] = []
    system_prompt = ""
    user_prompt = ""
    assistant_reply = ""
    error_detail = None
    model_name = os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307")
    conversation_context = build_conversation_context(history)
    is_first_turn = len(history) == 0

    router_payload = None
    router_prompt = build_router_prompt(message, conversation_context=conversation_context)
    router_text, router_error = call_anthropic_router(
        ROUTER_RULES,
        [{"role": "user", "content": router_prompt}],
        model=os.getenv("CLAUDE_ROUTER_MODEL", "claude-3-haiku-20240307"),
        max_tokens=250,
    )
    if router_text and not router_error:
        router_payload = parse_router_response(router_text)

    if not router_payload:
        if should_smalltalk(message, history):
            router_payload = {
                "intent": "smalltalk",
                "strategy": "gateway",
                "query": message,
                "filters": {},
                "rank_by": "score_poplite",
                "need_clarifying_question": False,
                "clarifying_question": None,
            }
        else:
            mode_and_filters = infer_mode_and_filters(message)
            router_payload = {
                "intent": "reco",
                "strategy": mode_and_filters["mode"],
                "query": message,
                "filters": mode_and_filters["filters"],
                "rank_by": "score_poplite",
                "need_clarifying_question": False,
                "clarifying_question": None,
            }

    intent = (router_payload.get("intent") or "reco").strip().lower()
    strategy = (router_payload.get("strategy") or "gateway").strip().lower()
    rank_by = (router_payload.get("rank_by") or "score_poplite").strip()
    query = (router_payload.get("query") or message).strip()
    router_filters = router_payload.get("filters") or {}

    try:
        if intent == "smalltalk":
            prompt_type = "smalltalk"
            mode = "smalltalk"
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
            assistant_reply = call_anthropic_env(
                system, [{"role": "user", "content": prompt}], model=model_name
            )
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
            instruments = router_filters.get("instruments") or router_filters.get(
                "soloist_instruments"
            )
            if instruments:
                search_filters["soloist_instruments"] = instruments
            if router_filters.get("is_atmos") is True:
                search_filters["is_atmos"] = True
            if router_filters.get("is_atmos") is False:
                search_filters["is_atmos"] = False
            if router_filters.get("min_unique_users") is not None:
                search_filters["min_unique_users"] = router_filters.get("min_unique_users")
            try:
                candidates = catalog.search(
                    {
                        "query": query or message,
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
                history_summary = build_history_summary(history, message)
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
                assistant_reply = call_anthropic_env(
                    system, [{"role": "user", "content": prompt}], model=model_name
                )
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

    response = ChatResponse(reply=assistant_reply or "", mode=mode, conversation_id=conversation_id)
    if debug_enabled:
        response.debug = {
            "used_catalog": used_catalog,
            "candidate_count": candidate_count,
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
