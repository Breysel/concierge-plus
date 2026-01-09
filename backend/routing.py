"""
Simplified routing - always use LLM for intent classification.
Quality over cost. Claude understands nuance better than keyword matching.
"""

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.llm import call_anthropic_router
from backend.filters import infer_filters

ROUTER_SYSTEM = """
You are a routing classifier for a classical music recommendation chatbot.

Analyze the user's message and return JSON with this exact schema:
{
  "intent": "smalltalk" | "meta" | "reco",
  "strategy": "gateway" | "performer_led" | "vibe" | "deep_dive" | "atmos" | "continue",
  "query": "search query to use",
  "search_terms": ["additional", "search", "terms"],
  "rank_by": "score_poplite" | "score_sticky" | "score_hidden_gem",
  "filters": {
    "epochs": [],
    "genres": [],
    "exclude_genres": [],
    "soloist_instruments": [],
    "is_atmos": null,
    "min_unique_users": null
  }
}

INTENT CLASSIFICATION (most important):

"smalltalk":
  - Greetings/thanks/emoji in any language
  - Help: what can you do, how does this work

"meta":
  - Questions about the concierge itself: what do you like, what's your favorite, do you have preferences
  - Philosophical: how do you experience music, do you care about music, what moves you
  - Personal: tell me about yourself, who are you (beyond basic help)
  - Opinion requests: what should I listen to (without any criteria given)
  - Feedback responses: that was great, I loved it, not what I wanted (without new request)

"reco":
  - Explicit requests: recommend, suggest, give me, play, find me
  - Composer/performer mentions: Bach, Mozart, Karajan, Yo-Yo Ma
  - Mood/vibe requests: something dark, calming music, energetic
  - Instrument requests: piano music, violin concertos
  - Context requests: music for studying, dinner party, workout
  - Refinements with criteria: darker, more like that but calmer, less vocals

IMPORTANT: If the user is having a conversation (asking about you, sharing feelings, giving feedback without a new request),
classify as "meta" NOT "reco". The concierge should be able to chat without always recommending albums.

If the user says "show me something you like" or "recommend something you like", classify as "reco" (NOT "meta").

STRATEGY (only matters if intent is "reco"):
- "gateway": general/unclear requests
- "performer_led": specific composer or performer mentioned
- "vibe": mood/feeling words (dark, calm, energetic, romantic)
- "deep_dive": hidden gems, obscure, underrated
- "atmos": Dolby Atmos, spatial audio
- "continue": refining previous request

FILTERS (only populate when explicitly requested):
- Handle negations: "no opera" -> exclude_genres: ["opera"]
- Handle "no vocals/singing" -> exclude_genres: ["opera", "vocal", "choral"]
If the user asks for jazz, do NOT put Jazz into filters.genres. Put "jazz" into query/search_terms instead.

Return ONLY valid JSON, no explanation.
""".strip()


def _build_router_prompt(message: str, conversation_context: Optional[str] = None) -> str:
    """Build the prompt for the router LLM."""
    parts = []
    if conversation_context:
        parts.append(f"Recent conversation:\n{conversation_context[:1500]}\n")
    parts.append(f"User message: {message}")
    return "\n".join(parts)


def _parse_router_response(text: str) -> Optional[Dict[str, Any]]:
    """Extract and parse JSON from router response."""
    if not text:
        return None
    text = text.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _default_route(message: str) -> Dict[str, Any]:
    """Fallback route if LLM fails. Simple and safe."""
    return {
        "intent": "reco",
        "strategy": "gateway",
        "query": message,
        "search_terms": [],
        "rank_by": "score_poplite",
        "filters": {
            "epochs": [],
            "genres": [],
            "exclude_genres": [],
            "soloist_instruments": [],
            "is_atmos": None,
            "min_unique_users": None,
        },
    }


def fast_route(message: str) -> Dict[str, Any]:
    return _default_route(message)


def route_message(
    message: str,
    history: List[Dict[str, str]],
    conversation_context: Optional[str] = None,
) -> Tuple[Dict[str, Any], str, bool, int]:
    """
    Route a user message using Claude Haiku.

    Returns:
        - route_decision: Dict with intent, strategy, filters, etc.
        - raw_response: Raw LLM response text (for logging)
        - router_used: Always True now (for logging compatibility)
        - router_ms: Time taken in milliseconds
    """
    prompt = _build_router_prompt(message, conversation_context)

    start = time.perf_counter()
    response_text, error = call_anthropic_router(
        system=ROUTER_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    router_ms = int((time.perf_counter() - start) * 1000)

    if error or not response_text:
        print(f"Router error (using fallback): {error}")
        return fast_route(message), "", True, router_ms

    parsed = _parse_router_response(response_text)
    if not parsed:
        print(f"Router parse error (using fallback). Raw: {response_text[:200]}")
        return fast_route(message), response_text, True, router_ms

    route = {
        "intent": parsed.get("intent", "reco"),
        "strategy": parsed.get("strategy", "gateway"),
        "query": parsed.get("query", message),
        "search_terms": parsed.get("search_terms", []),
        "rank_by": parsed.get("rank_by", "score_poplite"),
        "filters": {
            "epochs": parsed.get("filters", {}).get("epochs", []),
            "genres": parsed.get("filters", {}).get("genres", []),
            "exclude_genres": parsed.get("filters", {}).get("exclude_genres", []),
            "soloist_instruments": parsed.get("filters", {}).get("soloist_instruments", []),
            "is_atmos": parsed.get("filters", {}).get("is_atmos"),
            "min_unique_users": parsed.get("filters", {}).get("min_unique_users"),
        },
    }

    inferred = infer_filters(message)
    if inferred.get("genres") and not route["filters"]["genres"]:
        route["filters"]["genres"] = inferred.get("genres")

    return route, response_text, True, router_ms


def format_recent(
    history: List[Dict[str, str]], max_msgs: int = 6, max_chars_each: int = 350
) -> str:
    """Format recent conversation history for context."""
    recent = history[-max_msgs:] if history else []
    lines = []
    for item in recent:
        role = (item.get("role") or "").upper()
        content = (item.get("content") or "").strip().replace("\n", " ")
        if content:
            lines.append(f"{role}: {content[:max_chars_each]}")
    return "\n".join(lines)


def build_effective_query(
    base_query: str,
    search_terms: List[str],
    history: List[Dict[str, str]],
    strategy: str,
    user_message: str,
) -> str:
    """Build the final search query. LLM already handles context, so this is simpler now."""
    query = (base_query or "").strip()
    if search_terms:
        query = f"{query} {' '.join(search_terms)}".strip()
    return query or user_message.strip()


__all__ = [
    "route_message",
    "format_recent",
    "build_effective_query",
    "fast_route",
]
