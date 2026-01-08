import os
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import catalog
from backend.prompts import (
    SYSTEM_PROMPT,
    RECO_RULES,
    SMALLTALK_RULES,
    build_reco_prompt,
    build_smalltalk_prompt,
)


class HistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[HistoryItem]] = None


class ChatResponse(BaseModel):
    reply: str
    mode: str
    debug: Optional[Dict[str, Any]] = None


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


def is_smalltalk(text: str, history: List[HistoryItem]) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True

    greetings = ["hello", "hey", "hi", "hola", "guten tag", "hallo", "yo"]
    thanks = ["thanks", "thank you", "thx", "appreciate it", "cheers"]
    meta = ["who are you", "what can you do", "help", "how does this work"]
    short_reactions = ["lol", "lmao", "haha", "ok", "okay"]
    music_keywords = [
        "music",
        "classical",
        "composer",
        "orchestra",
        "orchestral",
        "symphony",
        "concerto",
        "quartet",
        "baroque",
        "romantic",
        "atmos",
        "dolby",
        "piano",
        "violin",
        "cello",
        "bach",
        "mozart",
        "beethoven",
        "chopin",
        "tchaikovsky",
        "dark",
        "calm",
        "relax",
        "focus",
        "dramatic",
        "sleep",
        "study",
    ]

    has_music_intent = any(keyword in lowered for keyword in music_keywords)
    has_history = any(item.role == "user" and item.content for item in history)

    if has_history:
        if any(phrase in lowered for phrase in greetings + thanks + meta + short_reactions):
            return not has_music_intent
        return False

    if any(phrase in lowered for phrase in greetings + thanks + meta + short_reactions):
        return not has_music_intent

    if len(lowered.split()) <= 2 and not has_music_intent:
        return True

    return False


def build_history_summary(history: List[HistoryItem], current_message: str) -> str:
    user_messages = [item.content for item in history if item.role == "user" and item.content]
    recent = user_messages[-2:]
    if not recent:
        return ""
    previous = "; ".join(recent)
    summary = f"User previously asked: {previous}. Now asks: {current_message}."
    return summary[:200]


def call_anthropic_env(system: str, messages: List[Dict[str, str]]) -> str:
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
        model=os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307"),
        temperature=0.2,
        system=system,
        messages=messages,
        max_tokens=700,
    )
    return response.content[0].text


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    history = request.history or []
    history = history[-12:]
    debug_enabled = os.getenv("DEBUG", "").lower() == "true"

    if is_smalltalk(message, history):
        prompt = build_smalltalk_prompt(message)
        system = f"{SYSTEM_PROMPT}\n\n{SMALLTALK_RULES}"
        reply = call_anthropic_env(system, [{"role": "user", "content": prompt}])
        response = ChatResponse(reply=reply or "", mode="smalltalk")
        if debug_enabled:
            response.debug = {"used_catalog": False, "candidate_count": 0}
        return response

    mode_and_filters = infer_mode_and_filters(message)
    try:
        candidates = catalog.search(
            {
                "query": message,
                "mode": mode_and_filters["mode"],
                "filters": mode_and_filters["filters"],
                "limit": 30,
            }
        )
    except FileNotFoundError:
        response = ChatResponse(
            reply=(
                "Catalog isn't loaded on this server yet — I can still chat, but "
                "can't recommend albums until the catalog is connected."
            ),
            mode="reco",
        )
        if debug_enabled:
            response.debug = {"used_catalog": False, "candidate_count": 0}
        return response

    history_summary = build_history_summary(history, message)
    prompt = build_reco_prompt(
        message,
        candidates,
        conversation_context=None,
        history_summary=history_summary or None,
    )
    system = f"{SYSTEM_PROMPT}\n\n{RECO_RULES}"
    reply = call_anthropic_env(system, [{"role": "user", "content": prompt}])

    response = ChatResponse(reply=reply or "", mode="reco")
    if debug_enabled:
        response.debug = {"used_catalog": True, "candidate_count": len(candidates)}
    return response


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=port)
