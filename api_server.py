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


class ChatRequest(BaseModel):
    message: str
    conversation_context: Optional[str] = None


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


def is_smalltalk(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True

    greetings = ["hello", "hey", "hi", "hola", "guten tag", "hallo", "yo"]
    thanks = ["thanks", "thank you", "thx", "appreciate it", "cheers"]
    meta = ["who are you", "what can you do", "help", "how does this work"]
    short_reactions = ["lol", "lmao", "haha", "ok", "okay"]

    if any(phrase in lowered for phrase in greetings + thanks + meta + short_reactions):
        return True

    if len(lowered.split()) <= 2:
        return True

    return False


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


@app.post("/chat")
def chat(request: ChatRequest) -> Dict[str, str]:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    if is_smalltalk(message):
        prompt = build_smalltalk_prompt(message)
        system = f"{SYSTEM_PROMPT}\n\n{SMALLTALK_RULES}"
    else:
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
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail=str(exc),
            ) from exc

        prompt = build_reco_prompt(
            message,
            candidates,
            conversation_context=request.conversation_context,
        )
        system = f"{SYSTEM_PROMPT}\n\n{RECO_RULES}"

    reply = call_anthropic_env(system, [{"role": "user", "content": prompt}])

    return {"reply": reply or ""}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=port)
