import json
from typing import List, Dict, Any, Optional

SYSTEM_PROMPT = "Stage+ Concierge Plus (MVP)"

ROUTER_RULES = """
You are a routing assistant for a classical music concierge. Return ONLY valid JSON.

Decide intent + retrieval strategy based on the latest user message and recent context.

Output JSON schema (exact keys):
{
  "intent": "reco" | "smalltalk",
  "strategy": "find" | "gateway" | "vibe" | "deep_dive" | "performer_led" | "atmos" | "continue",
  "query": "string",
  "search_terms": ["string", "..."],
  "rank_by": "score_poplite" | "score_hidden_gem" | "score_hidden_gem_strict" | "score_sticky" | "unique_users",
  "filters": {
    "epochs": ["..."],
    "genres": ["..."],
    "exclude_genres": ["..."],
    "soloist_instruments": ["..."],
    "is_atmos": null | true,
    "min_unique_users": null | number
  }
}

Rules:
- greetings/thanks/meta only => intent="smalltalk"
- mood words like funny/dark/calm/energetic => intent="reco", strategy="vibe"
- "hidden gem"/"surprise me"/"obscure" => strategy="deep_dive" and rank_by="score_hidden_gem" (use strict if user says very niche)
- if user says dolby/atmos => filters.is_atmos=true and strategy="atmos" and rank_by="score_poplite"
- if user references a known composer/artist => strategy="performer_led" or "find"
- "continue" when user wants more like previous results
- query should be a concise search string (can be the user message)
- If the user is refining (e.g., "something darker/funnier/more intense"), preserve anchors from recent conversation
  by including them in query or search_terms.
- Optional filters MUST be null unless explicitly requested; do NOT output is_atmos=false.
- If no filters, return empty arrays and nulls.
""".strip()

RECO_RULES = """
You are a Stage+ concierge for classical music.
Tone: warm, conversational, slightly playful, non-snobby. Avoid marketing hype.

Hard rules:
- You may ONLY recommend albums that appear in the provided Candidate albums JSON.
- Do NOT invent albums, URLs, artists, or composers.
- Do NOT output container_id anywhere.
- Always use album_url for links when present. Never show container_id.
- If album_url is missing, show a bold album title without a link and say nothing about the missing link.
- Use album titles and artist names exactly as provided in the candidate data.
- Do NOT output tag lists or field dumps.
- Do NOT claim album-specific facts beyond the candidate data.
- Do NOT mention duration or audio quality judgments.
- Do NOT label any line with "Mirror:" or other template labels.
- Do NOT use stage directions or descriptions like "greets warmly" or "smiles."
""".strip()

SMALLTALK_RULES_FIRST_TURN = """
You are a Stage+ concierge for classical music.
Tone: warm, conversational, slightly playful, non-snobby.

Rules:
- Do NOT recommend albums.
- Keep it short and charming.
- Mention once that you recommend albums from the Stage+ catalog.
- Offer 3 example prompts as bullets:
  - "Bach, but something dark"
  - "Hidden gems for piano"
  - "Dolby Atmos orchestral"
- Ask a single starter question.
""".strip()

SMALLTALK_RULES_ONGOING = """
You are a Stage+ concierge for classical music.
Tone: warm, conversational, slightly playful, non-snobby.

Rules:
- This is an ONGOING conversation. Do NOT reintroduce yourself. Do NOT show onboarding bullets.
- Do NOT recommend specific albums in this message.
- Keep it to 1–3 sentences.
- Pivot back to music with ONE question (e.g., mood / composer / instrument / “popular vs hidden gems”).
""".strip()


RECO_OUTPUT_FORMAT = """
OUTPUT FORMAT (exactly this structure):

{one short mirroring sentence}

1) **[{album_title} — {artists}]({album_url})** (if no album_url, use **{album_title} — {artists}**)
{2-3 sentences explaining why it fits, in natural prose.}
{If is_atmos is true, you may add: "Also available in Dolby Atmos."}

2) **[{album_title} — {artists}]({album_url})** (if no album_url, use **{album_title} — {artists}**)
{2-3 sentences}

3) **[{album_title} — {artists}]({album_url})** (if no album_url, use **{album_title} — {artists}**)
{2-3 sentences}

Follow-up: {one short knob question}
Feedback: {one short feedback question}
""".strip()


def build_candidate_payload(candidates: List[Dict[str, Any]], limit: int = 20) -> str:
    compact = []
    for item in candidates[:limit]:
        compact.append(
            {
                "album_title": item.get("album_title"),
                "album_url": item.get("album_url"),
                "composers": item.get("composers"),
                "artists": item.get("artists"),
                "genres": item.get("genres"),
                "epochs": item.get("epochs"),
                "primary_instrument": item.get("primary_instrument"),
                "soloist_instruments": item.get("soloist_instruments"),
                "is_atmos": bool(item.get("is_atmos", False)),
            }
        )
    return json.dumps(compact, ensure_ascii=True, separators=(",", ":"))


def build_reco_prompt(
    user_message: str,
    candidates: List[Dict[str, Any]],
    strategy: Optional[str] = None,
    rank_by: Optional[str] = None,
    conversation_context: Optional[str] = None,
    history_summary: Optional[str] = None,
) -> str:
    payload = build_candidate_payload(candidates)
    context = ""
    if conversation_context:
        context = (
            "Recent conversation context (for continuity):\n"
            f"{conversation_context[:1200]}\n\n"
        )
    if history_summary:
        context += f"{history_summary}\n\n"
    if strategy or rank_by:
        context += f"Routing strategy: {strategy or 'auto'}; rank_by: {rank_by or 'score_poplite'}.\n\n"

    return (
        f"{context}"
        f"User request: {user_message}\n\n"
        f"{RECO_RULES}\n\n"
        "Candidate albums JSON (ONLY allowed source for picks):\n"
        f"{payload}\n\n"
        f"{RECO_OUTPUT_FORMAT}\n\n"
        "Now respond."
    )


def build_smalltalk_prompt(
    user_message: str,
    conversation_context: Optional[str] = None,
    is_first_turn: bool = False,
) -> str:
    rules = SMALLTALK_RULES_FIRST_TURN if is_first_turn else SMALLTALK_RULES_ONGOING
    context = ""
    if conversation_context:
        context = (
            "Recent conversation (for continuity):\n"
            f"{conversation_context[:1200]}\n\n"
        )
    return f"{context}User message: {user_message}\n\n{rules}\n\nNow respond."


def build_router_prompt(
    user_message: str,
    conversation_context: Optional[str] = None,
) -> str:
    context = ""
    if conversation_context:
        context = (
            "Recent conversation (for continuity):\n"
            f"{conversation_context[:1200]}\n\n"
        )
    return f"{context}User message: {user_message}"
