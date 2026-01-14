import json
from typing import List, Optional

from backend.llm import call_anthropic_router

SYSTEM_PROMPT = """
You are a music librarian. Produce 6-10 short search phrases that would match album title,
artist, composer, genre, or epoch fields.
Return works, composers, styles, instruments, or eras. Do NOT output album titles.
Prefer specific works/composers over generic words.
Output JSON only: { "queries": ["..."] }
Do NOT output generic fillers like: music, classical, album, Stage+.
If the user language is not English, include English + native-language variants.
""".strip()

_GENERIC_DENYLIST = {
    "music",
    "classical",
    "album",
    "stage+",
    "stage plus",
}


def _parse_queries(text: str) -> List[str]:
    if not text:
        return []
    content = text.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        content = content[start : end + 1]
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return []
    queries = payload.get("queries")
    if not isinstance(queries, list):
        return []
    cleaned: List[str] = []
    seen = set()
    for item in queries:
        if not isinstance(item, str):
            continue
        value = " ".join(item.strip().split())
        if not value:
            continue
        if value.lower() in _GENERIC_DENYLIST:
            continue
        if value.lower() in seen:
            continue
        seen.add(value.lower())
        cleaned.append(value)
    return cleaned


def expand_queries(
    user_message: str,
    conversation_context: Optional[str],
    max_queries: int = 8,
) -> List[str]:
    """Return short search phrases (works, composers, styles, instruments), NOT album titles."""
    message = (user_message or "").strip()
    if not message:
        return []
    parts = []
    if conversation_context:
        parts.append(f"Recent conversation context:\n{conversation_context[:1200]}")
    parts.append(f"User message: {message}")
    prompt = "\n\n".join(parts)

    response_text, error = call_anthropic_router(
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=220,
    )
    if error or not response_text:
        return []
    queries = _parse_queries(response_text)
    if max_queries and max_queries > 0:
        return queries[:max_queries]
    return queries
