import random
from typing import Dict, Any, List, Optional

import streamlit as st

from backend import catalog
from backend.llm import call_anthropic, call_anthropic_stream
from backend.prompts import SYSTEM_PROMPT, RECO_RULES, build_reco_prompt, build_smalltalk_prompt
from backend.routing import (
    build_effective_query,
    format_recent,
    route_message,
    should_smalltalk,
)

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


def run_claude(prompt: str, system: Optional[str] = None) -> str:
    system = system or SYSTEM_PROMPT
    messages = [{"role": "user", "content": prompt}]
    model = (
        st.secrets.get("CLAUDE_WRITER_MODEL")
        or st.secrets.get("CLAUDE_MODEL")
        or "claude-3-5-sonnet-20241022"
    )

    chunks: List[str] = []
    try:
        placeholder = st.empty()

        for chunk in call_anthropic_stream(
            system=system,
            messages=messages,
            model=model,
            temperature=0.3,
            max_tokens=500,
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
            temperature=0.3,
            max_tokens=500,
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

    user_input = st.chat_input("Ask for a classical recommendation...")
    if user_input:
        prior_history = list(st.session_state["messages"])
        has_prior_user = any(message.get("role") == "user" for message in prior_history)
        is_first_turn = not has_prior_user

        st.session_state["messages"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        effective_history = prior_history + [{"role": "user", "content": user_input}]
        conversation_context = format_recent(effective_history)
        router_payload, _, _, _ = route_message(
            user_input, effective_history, conversation_context=conversation_context
        )
        intent = (router_payload.get("intent") or "reco").strip().lower()

        if intent == "smalltalk" and not should_smalltalk(user_input, effective_history):
            intent = "reco"

        if intent == "smalltalk":
            prompt = build_smalltalk_prompt(
                user_input,
                conversation_context=conversation_context,
                is_first_turn=is_first_turn,
            )
            with st.chat_message("assistant"):
                response_text = run_claude(prompt, system=SYSTEM_PROMPT)
            if response_text:
                st.session_state["messages"].append({"role": "assistant", "content": response_text})
            st.markdown("</div>", unsafe_allow_html=True)
            return

        with st.spinner(random.choice(SPINNER_MESSAGES)):
            strategy = (router_payload.get("strategy") or "gateway").strip().lower()
            rank_by = (router_payload.get("rank_by") or "score_poplite").strip()
            query = (router_payload.get("query") or user_input).strip()
            router_filters = router_payload.get("filters") or {}
            search_terms = router_payload.get("search_terms") or []

            search_filters: Dict[str, Any] = {}
            if router_filters.get("epochs"):
                search_filters["epochs"] = router_filters.get("epochs")
            if router_filters.get("genres"):
                search_filters["genres"] = router_filters.get("genres")
            if router_filters.get("exclude_genres"):
                search_filters["exclude_genres"] = router_filters.get("exclude_genres")
            instruments = router_filters.get("soloist_instruments")
            if instruments:
                search_filters["soloist_instruments"] = instruments
            if router_filters.get("is_atmos") is True:
                search_filters["is_atmos"] = True
            if router_filters.get("min_unique_users") is not None:
                search_filters["min_unique_users"] = router_filters.get("min_unique_users")

            effective_query = build_effective_query(
                query,
                search_terms,
                effective_history,
                strategy,
                user_input,
            )
            try:
                candidates = catalog.search(
                    {
                        "query": effective_query,
                        "mode": strategy,
                        "filters": search_filters,
                        "rank_by": rank_by,
                        "limit": 12,
                    }
                )
            except FileNotFoundError:
                response_text = (
                    "I'm having trouble accessing the music library right now. "
                    "Try again in a moment?"
                )
                with st.chat_message("assistant"):
                    st.markdown(response_text)
                st.session_state["messages"].append(
                    {"role": "assistant", "content": response_text}
                )
                st.markdown("</div>", unsafe_allow_html=True)
                return

        prompt = build_reco_prompt(
            user_input,
            candidates,
            strategy=strategy,
            rank_by=rank_by,
            conversation_context=conversation_context,
        )
        with st.chat_message("assistant"):
            response_text = run_claude(prompt, system=f"{SYSTEM_PROMPT}\n\n{RECO_RULES}")
            if not response_text:
                response_text = build_offline_response(candidates, user_input)
                st.markdown(response_text, unsafe_allow_html=True)
        st.session_state["messages"].append({"role": "assistant", "content": response_text})

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
