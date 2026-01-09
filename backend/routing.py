import json
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.filters import infer_filters
from backend.llm import call_anthropic_router
from backend.prompts import ROUTER_RULES, build_router_prompt


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


def should_smalltalk(message: str, history: List[Dict[str, str]]) -> bool:
    lowered = (message or "").strip().lower()
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

    filters.update(infer_filters(message))

    return {
        "intent": "reco",
        "strategy": strategy,
        "query": message,
        "search_terms": [],
        "rank_by": rank_by,
        "filters": filters,
    }


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


def _last_meaningful_user_message(history: List[Dict[str, str]]) -> str:
    for item in reversed(history or []):
        if item.get("role") == "user":
            text = (item.get("content") or "").strip()
            if text and len(text) >= 3:
                if text.lower() not in {
                    "why these recommendations?",
                    "why these recommendations",
                    "more",
                    "more please",
                }:
                    return text
    return ""


def _looks_like_refinement_only(text: str) -> bool:
    lowered = (text or "").strip().lower()
    vibe_words = [
        "dark",
        "darker",
        "calm",
        "calmer",
        "funny",
        "weird",
        "strange",
        "sad",
        "happier",
        "more like that",
        "similar",
        "another",
        "faster",
        "slower",
        "sleepy",
        "focus",
        "study",
        "more intense",
        "more intimate",
        "more dramatic",
    ]
    if any(word in lowered for word in vibe_words):
        return True
    if len(lowered) <= 14 and any(word in lowered for word in ["more", "again", "another", "different", "else"]):
        return True
    return False


def _contains_anchor(text: str) -> bool:
    lowered = (text or "").lower()
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
    return any(anchor in lowered for anchor in anchors)


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
    if strategy in {"vibe", "continue"} and _looks_like_refinement_only(user_message):
        if not _contains_anchor(user_message):
            anchor = _last_meaningful_user_message(history)
            if anchor and anchor.lower() not in query.lower():
                query = f"{anchor} {query}".strip()
    return query or user_message.strip()


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


def route_message(
    message: str,
    history: List[Dict[str, str]],
    conversation_context: Optional[str] = None,
) -> Tuple[Dict[str, Any], str, bool, int]:
    router_used = False
    router_ms = 0
    router_raw_text = ""

    if should_smalltalk_fast(message, history):
        return (
            {
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
            },
            router_raw_text,
            router_used,
            router_ms,
        )

    if should_use_router(message, history):
        router_used = True
        router_prompt = build_router_prompt(message, conversation_context=conversation_context)
        router_start = time.perf_counter()
        router_text, router_error = call_anthropic_router(
            ROUTER_RULES,
            [{"role": "user", "content": router_prompt}],
        )
        router_ms = int((time.perf_counter() - router_start) * 1000)
        if router_text and not router_error:
            router_raw_text = router_text
            router_payload = parse_router_response(router_text)
            if router_payload:
                return router_payload, router_raw_text, router_used, router_ms

    return fast_route(message, history), router_raw_text, router_used, router_ms


__all__ = [
    "format_recent",
    "should_smalltalk_fast",
    "should_smalltalk",
    "should_use_router",
    "fast_route",
    "route_message",
    "build_effective_query",
]
