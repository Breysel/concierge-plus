import random
from typing import Dict, Any, List

import streamlit as st

from backend import catalog
from backend.llm import call_anthropic, call_anthropic_stream
from backend.prompts import SYSTEM_PROMPT, build_reco_prompt, build_smalltalk_prompt

SPINNER_MESSAGES = [
    "Flipping through the vinyl bins...",
    "Consulting the orchestra librarian...",
    "Checking for Dolby Atmos...",
    "Re-tuning the harpsichord...",
    "Paging the concertmaster...",
]


def stageplus_tokens() -> Dict[str, str]:
    return dict(
        STAGE_BG="#0B0F16",
        STAGE_PANEL="#121A26",
        STAGE_TEXT="#F3F6FF",
        STAGE_MUTED="#9AA7B8",
        STAGE_ACCENT="#FFD400",
    )


def inject_stageplus_styles() -> None:
    tokens = stageplus_tokens()
    root_vars = "\n".join(
        [
            ":root {",
            f"  --stage-bg: {tokens['STAGE_BG']};",
            f"  --stage-panel: {tokens['STAGE_PANEL']};",
            f"  --stage-text: {tokens['STAGE_TEXT']};",
            f"  --stage-muted: {tokens['STAGE_MUTED']};",
            f"  --stage-accent: {tokens['STAGE_ACCENT']};",
            "}",
        ]
    )
    st.markdown(f"<style>{root_vars}</style>", unsafe_allow_html=True)

    with open("assets/stageplus.css", "r", encoding="utf-8") as handle:
        st.markdown(f"<style>{handle.read()}</style>", unsafe_allow_html=True)


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


def get_last_user_message(messages: List[Dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content", "") or ""
    return ""


def is_vague_refinement(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False

    tokens = lowered.split()
    short_enough = len(tokens) <= 6
    vague_markers = [
        "dark",
        "calm",
        "relax",
        "focus",
        "energetic",
        "dramatic",
        "sleep",
        "study",
        "more",
        "less",
        "darker",
        "lighter",
    ]
    has_vague = any(word in lowered for word in vague_markers)

    anchor_markers = [
        "by",
        "composer",
        "conductor",
        "piano",
        "violin",
        "cello",
        "mozart",
        "beethoven",
    ]
    has_anchor = any(word in lowered for word in anchor_markers)

    return (short_enough or has_vague) and not has_anchor


def is_smalltalk(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True

    greetings = ["hello", "hey", "hi", "hola", "guten tag", "hallo", "yo"]
    thanks = ["thanks", "thank you", "thx", "appreciate it", "cheers"]
    meta = ["who are you", "what can you do", "help", "how does this work"]

    request_verbs = [
        "recommend",
        "suggest",
        "give me",
        "play",
        "listen",
        "looking for",
        "in the mood",
        "i want",
        "i'm after",
        "show me",
        "something",
        "anything",
    ]
    intent_words = [
        "funny",
        "calm",
        "relaxing",
        "dramatic",
        "romantic",
        "dark",
        "uplifting",
        "energ",
        "sleep",
        "study",
        "focus",
    ]

    if any(phrase in lowered for phrase in greetings + thanks + meta):
        if any(verb in lowered for verb in request_verbs + intent_words):
            return False
        return True

    return False


def format_album_title(item: Dict[str, Any]) -> str:
    title = item.get("album_title") or "Untitled Album"
    url = item.get("album_url")
    if url:
        return f"[{title}]({url})"
    return title


def summarize_album(item: Dict[str, Any]) -> str:
    title = format_album_title(item)
    composers = item.get("composers") or ""
    artists = item.get("artists") or ""
    genres = item.get("genres") or ""
    epochs = item.get("epochs") or ""
    is_atmos = bool(item.get("is_atmos"))

    details = ", ".join([bit for bit in [composers, artists] if bit])
    tone_bits = ", ".join([bit for bit in [genres, epochs] if bit])

    sentence_one = "A thoughtful pick that stays close to your request."
    if details:
        sentence_one = f"A thoughtful pick centered on {details}."
    sentence_two = "It keeps the mood tight and focused."
    if tone_bits:
        sentence_two = f"It leans into {tone_bits.lower()} colors without overdoing it."

    atmos_line = " Also available in Dolby Atmos." if is_atmos else ""
    return f"**{title}**\n{sentence_one} {sentence_two}{atmos_line}"


def build_offline_response(candidates: List[Dict[str, Any]], user_input: str) -> str:
    if not candidates:
        return "I couldn't find any matches in the catalog. Want to try a different mood, composer, or instrument?"
    top = candidates[:3]
    lines = [f"Got it - you want {user_input.strip() or 'something in that lane'}.", ""]
    for item in top:
        lines.append(summarize_album(item))
        lines.append("")
    lines.append("Follow-up: Do you want this more calm or more dramatic?")
    lines.append("Feedback: Which one is closest?")
    return "\n".join(lines).strip()


def run_claude(prompt: str) -> str:
    system = SYSTEM_PROMPT
    messages = [{"role": "user", "content": prompt}]
    model = st.secrets.get("CLAUDE_MODEL", "claude-3-haiku-20240307")

    chunks: List[str] = []
    try:
        placeholder = st.empty()

        for chunk in call_anthropic_stream(
            system=system,
            messages=messages,
            model=model,
            temperature=0.2,
            max_tokens=700,
        ):
            chunks.append(chunk)
            response_text = "".join(chunks)
            placeholder.markdown(response_text, unsafe_allow_html=True)

        response_text = "".join(chunks)
        if not response_text.strip():
            raise RuntimeError("Empty stream response.")
        return response_text
    except Exception:
        response_text, error = call_anthropic(
            system=system,
            messages=messages,
            model=model,
            temperature=0.2,
            max_tokens=700,
        )
        if error:
            st.error(error)
            return ""
        st.markdown(response_text, unsafe_allow_html=True)
        return response_text


def main() -> None:
    st.set_page_config(page_title="Concierge Plus", page_icon="V")
    inject_stageplus_styles()
    st.markdown('<div class="stageplus-container">', unsafe_allow_html=True)
    st.markdown("# Concierge Plus")

    if "ANTHROPIC_API_KEY" not in st.secrets:
        st.error("Missing ANTHROPIC_API_KEY in Streamlit secrets.")
        st.stop()

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    if not st.session_state["messages"]:
        welcome = "\n".join(
            [
                "Welcome - I'm Concierge Plus. Tell me a mood, composer, instrument, or \"hidden gems\" and I'll recommend 3 albums from our Stage+ catalog.",
                "",
                "Examples:",
                "- \"Late-night piano, calm and reflective\"",
                "- \"Hidden gems for string quartet\"",
                "- \"Dolby Atmos orchestral showpieces\"",
            ]
        )
        st.session_state["messages"].append({"role": "assistant", "content": welcome})

    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                st.markdown(message["content"], unsafe_allow_html=True)
            else:
                st.markdown(message["content"])

    has_prior_user = any(
        message.get("role") == "user" for message in st.session_state["messages"]
    )

    user_input = st.chat_input("Ask for a classical recommendation...")
    if user_input:
        st.session_state["messages"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        if is_smalltalk(user_input) and not has_prior_user:
            prompt = build_smalltalk_prompt(user_input)
            with st.chat_message("assistant"):
                response_text = run_claude(prompt)
            if response_text:
                st.session_state["messages"].append({"role": "assistant", "content": response_text})
            st.markdown("</div>", unsafe_allow_html=True)
            return

        filters = infer_filters(user_input)

        with st.spinner(random.choice(SPINNER_MESSAGES)):
            candidates1 = catalog.search(
                {
                    "query": user_input,
                    "mode": "auto",
                    "filters": filters,
                    "limit": 30,
                }
            )

            last_user = get_last_user_message(st.session_state["messages"][:-1])
            if last_user and is_vague_refinement(user_input):
                candidates2 = catalog.search(
                    {
                        "query": last_user,
                        "mode": "find",
                        "filters": {},
                        "limit": 20,
                    }
                )
                seen = set()
                merged = []
                for item in candidates1 + candidates2:
                    cid = item.get("container_id")
                    if cid in seen:
                        continue
                    seen.add(cid)
                    merged.append(item)
                candidates = merged
            else:
                candidates = candidates1

        prev_assistant = ""
        for message in reversed(st.session_state["messages"][:-1]):
            if message["role"] == "assistant":
                prev_assistant = message["content"]
                break

        prompt = build_reco_prompt(
            user_input,
            candidates,
            conversation_context=prev_assistant,
        )
        with st.chat_message("assistant"):
            response_text = run_claude(prompt)
            if not response_text:
                response_text = build_offline_response(candidates, user_input)
                st.markdown(response_text, unsafe_allow_html=True)
        st.session_state["messages"].append({"role": "assistant", "content": response_text})

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
