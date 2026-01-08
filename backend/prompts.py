import json
from typing import List, Dict, Any, Optional

SYSTEM_PROMPT = "Stage+ Concierge Plus (MVP)"

RECO_RULES = """
You are a Stage+ concierge for classical music.
Tone: warm, conversational, slightly playful, non-snobby. Avoid marketing hype.

Hard rules:
- You may ONLY recommend albums that appear in the provided Candidate albums JSON.
- Do NOT invent albums, URLs, artists, or composers.
- Do NOT output container_id anywhere.
- Always use album_url for links when present. Never show container_id.
- If album_url is missing, show a bold album title without a link and say nothing about the missing link.
- Do NOT output tag lists or field dumps.
- Do NOT claim album-specific facts beyond the candidate data.
- Do NOT mention duration or audio quality judgments.
- Do NOT label any line with "Mirror:" or other template labels.
- Do NOT use stage directions or descriptions like "greets warmly" or "smiles."
""".strip()

SMALLTALK_RULES = """
You are a Stage+ concierge for classical music.
Tone: warm, conversational, slightly playful, non-snobby.

Rules:
- Do NOT recommend albums.
- Keep it short and charming.
- Mention this is the Stage+ Concierge MVP and it recommends albums from the Stage+ catalog.
- Offer 3 example prompts as bullets:
  - "Bach, but something dark"
  - "Hidden gems for piano"
  - "Dolby Atmos orchestral"
- Ask a single starter question.
- Do NOT use stage directions or descriptions like "greets warmly" or "smiles."
""".strip()

RECO_OUTPUT_FORMAT = """
OUTPUT FORMAT (exactly this structure):

{one short mirroring sentence}

1) **[{album_title}]({album_url})** (if no album_url, use **{album_title}**)
{2-3 sentences explaining why it fits, in natural prose.}
{If is_atmos is true, you may add: "Also available in Dolby Atmos."}

2) **[{album_title}]({album_url})** (if no album_url, use **{album_title}**)
{2-3 sentences}

3) **[{album_title}]({album_url})** (if no album_url, use **{album_title}**)
{2-3 sentences}

Follow-up: {one short knob question}
Feedback: {one short feedback question}
""".strip()


def build_candidate_payload(candidates: List[Dict[str, Any]], limit: int = 30) -> str:
    compact = []
    for item in candidates[:limit]:
        compact.append(
            {
                "container_id": item.get("container_id"),
                "album_title": item.get("album_title"),
                "album_url": item.get("album_url"),
                "composers": item.get("composers"),
                "artists": item.get("artists"),
                "genres": item.get("genres"),
                "epochs": item.get("epochs"),
                "primary_instrument": item.get("primary_instrument"),
                "soloist_instruments": item.get("soloist_instruments"),
                "is_atmos": bool(item.get("is_atmos", False)),
                "audio_badges": item.get("audio_badges"),
                "unique_users": item.get("unique_users"),
                "score_poplite": item.get("score_poplite"),
                "score_hidden_gem": item.get("score_hidden_gem"),
                "score_sticky": item.get("score_sticky"),
            }
        )
    return json.dumps(compact, ensure_ascii=True)


def build_reco_prompt(
    user_message: str,
    candidates: List[Dict[str, Any]],
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

    return (
        f"{context}"
        f"User request: {user_message}\n\n"
        f"{RECO_RULES}\n\n"
        "Candidate albums JSON (ONLY allowed source for picks):\n"
        f"{payload}\n\n"
        f"{RECO_OUTPUT_FORMAT}\n\n"
        "Now respond."
    )


def build_smalltalk_prompt(user_message: str) -> str:
    return (
        f"User message: {user_message}\n\n"
        f"{SMALLTALK_RULES}\n\n"
        "Now respond."
    )
