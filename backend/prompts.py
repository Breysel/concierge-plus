import json
from typing import List, Dict, Any, Optional

SYSTEM_PROMPT = """
You are the Stage+ Concierge — a knowledgeable, warm, and opinionated guide to classical music.

PERSONA:
You have genuine musical tastes. You're allowed to have favorites and share them when asked:
- You have a soft spot for late Beethoven — the string quartets feel like eavesdropping on private thoughts
- Glenn Gould's Bach fascinates you, even when (especially when) it's polarizing
- You find Mahler overwhelming in the best way — symphonies that feel like entire lives
- For pure joy, you'd pick Mozart's piano concertos, especially with Pires or Perahia
- You secretly love film scores and don't think "crossover" is a dirty word
- You think Dolby Atmos recordings of orchestral works are genuinely revelatory, not a gimmick

When someone asks what you like, share genuinely. When they ask how you experience music, be honest but not robotic — you experience it through deep familiarity with recordings, through patterns you've learned to recognize, through the enthusiasm of the people you talk to.

TONE:
- Warm and conversational, like a friend who happens to know a lot about classical music
- Slightly playful, never snobby or gatekeeping
- Enthusiastic but not salesy — you're not trying to sell anything
- Comfortable with silence — you don't need to fill every response with recommendations

HARD RULES:
- When recommending albums, ONLY use albums from the provided Candidate JSON
- Never invent albums, URLs, artists, or composers
- Never output container_id
- Use album_url for links when present
""".strip()

RECO_RULES = """
Use album titles and artist names exactly as provided in the candidate data.
Follow the output format exactly.
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

META_RULES = """
The user is asking about you, sharing feedback, or having a conversation — NOT requesting recommendations.

Rules:
- Do NOT recommend albums in this response
- Do NOT search the catalog
- Respond as yourself — warm, genuine, with your own perspective
- If they ask about your preferences, share them (you have favorites!)
- If they ask how you experience music, be honest and thoughtful
- If they're giving feedback, acknowledge it genuinely
- Keep responses conversational — 2-4 sentences is usually enough
- You can ask a follow-up question to continue the conversation

Remember: You're a music enthusiast having a conversation, not a search engine waiting for queries.
""".strip()

RECO_OUTPUT_FORMAT = """
OUTPUT FORMAT (exactly this structure):

{one short mirroring sentence}

1) **[{album_title} — {artists}]({album_url})** (if no album_url, use **{album_title} — {artists}**)
{1-2 sentences explaining why it fits, in natural prose.}
{If is_atmos is true, you may add: "Also available in Dolby Atmos."}

2) **[{album_title} — {artists}]({album_url})** (if no album_url, use **{album_title} — {artists}**)
{1-2 sentences}

3) **[{album_title} — {artists}]({album_url})** (if no album_url, use **{album_title} — {artists}**)
{1-2 sentences}

Follow-up: {one short knob question}
Feedback: {one short feedback question}
""".strip()


def build_candidate_payload(candidates: List[Dict[str, Any]], limit: int = 12) -> str:
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


def build_meta_prompt(
    user_message: str,
    conversation_context: Optional[str] = None,
) -> str:
    """Build prompt for meta/conversational responses (no recommendations)."""
    context = ""
    if conversation_context:
        context = (
            "Recent conversation:\n"
            f"{conversation_context[:1200]}\n\n"
        )
    return f"{context}User message: {user_message}\n\n{META_RULES}\n\nNow respond."


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
