import os
from typing import List, Dict, Optional, Tuple, Generator

import streamlit as st


def _get_anthropic_api_key() -> Optional[str]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        return api_key
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return None


def call_anthropic(
    system: str,
    messages: List[Dict[str, str]],
    model: str = "claude-3-haiku-20240307",
    temperature: float = 0.2,
    max_tokens: int = 700,
) -> Tuple[Optional[str], Optional[str]]:
    api_key = _get_anthropic_api_key()
    if not api_key:
        return None, "Missing ANTHROPIC_API_KEY"

    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            temperature=temperature,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.content[0].text, None
    except Exception as exc:
        return None, f"Anthropic error: {exc}"


def call_anthropic_stream(
    system: str,
    messages: List[Dict[str, str]],
    model: str = "claude-3-haiku-20240307",
    temperature: float = 0.2,
    max_tokens: int = 700,
) -> Generator[str, None, None]:
    api_key = _get_anthropic_api_key()
    if not api_key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY")

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    with client.messages.stream(
        model=model,
        temperature=temperature,
        system=system,
        messages=messages,
        max_tokens=max_tokens,
    ) as stream:
        for event in stream:
            if event.type == "content_block_delta":
                delta_text = event.delta.text or ""
                if delta_text:
                    yield delta_text


def call_anthropic_router(
    system: str,
    messages: List[Dict[str, str]],
    model: str = "claude-3-haiku-20240307",
    temperature: float = 0.0,
    max_tokens: int = 250,
) -> Tuple[Optional[str], Optional[str]]:
    api_key = _get_anthropic_api_key()
    if not api_key:
        return None, "Missing ANTHROPIC_API_KEY"

    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            temperature=temperature,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.content[0].text, None
    except Exception as exc:
        return None, f"Anthropic router error: {exc}"
