import os
from typing import List, Dict, Optional, Tuple, Generator


def get_secret(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st

        return st.secrets.get(name)
    except Exception:
        return None


def _get_anthropic_api_key() -> Optional[str]:
    return get_secret("ANTHROPIC_API_KEY")


def call_anthropic(
    system: str,
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[int] = None,
) -> Tuple[Optional[str], Optional[str]]:
    api_key = _get_anthropic_api_key()
    if not api_key:
        return None, "Missing ANTHROPIC_API_KEY"

    try:
        from anthropic import Anthropic

        resolved_model = model or os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307")
        resolved_temp = (
            temperature if temperature is not None else float(os.getenv("CLAUDE_TEMPERATURE", "0.3"))
        )
        resolved_max_tokens = int(os.getenv("CLAUDE_MAX_TOKENS", "500"))
        if max_tokens is not None:
            resolved_max_tokens = int(max_tokens)
        resolved_timeout = int(os.getenv("CLAUDE_TIMEOUT", "18"))
        if timeout is not None:
            resolved_timeout = int(timeout)

        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=resolved_model,
            temperature=resolved_temp,
            system=system,
            messages=messages,
            max_tokens=resolved_max_tokens,
            timeout=resolved_timeout,
        )
        return response.content[0].text, None
    except Exception as exc:
        return None, f"Anthropic error: {exc}"


def call_anthropic_stream(
    system: str,
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[int] = None,
) -> Generator[str, None, None]:
    api_key = _get_anthropic_api_key()
    if not api_key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY")

    from anthropic import Anthropic

    resolved_model = model or os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307")
    resolved_temp = (
        temperature if temperature is not None else float(os.getenv("CLAUDE_TEMPERATURE", "0.3"))
    )
    resolved_max_tokens = int(os.getenv("CLAUDE_MAX_TOKENS", "500"))
    if max_tokens is not None:
        resolved_max_tokens = int(max_tokens)
    resolved_timeout = int(os.getenv("CLAUDE_TIMEOUT", "18"))
    if timeout is not None:
        resolved_timeout = int(timeout)

    client = Anthropic(api_key=api_key)
    with client.messages.stream(
        model=resolved_model,
        temperature=resolved_temp,
        system=system,
        messages=messages,
        max_tokens=resolved_max_tokens,
        timeout=resolved_timeout,
    ) as stream:
        for event in stream:
            if event.type == "content_block_delta":
                delta_text = event.delta.text or ""
                if delta_text:
                    yield delta_text


def call_anthropic_router(
    system: str,
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[int] = None,
) -> Tuple[Optional[str], Optional[str]]:
    api_key = _get_anthropic_api_key()
    if not api_key:
        return None, "Missing ANTHROPIC_API_KEY"

    try:
        from anthropic import Anthropic

        resolved_model = model or os.getenv("CLAUDE_ROUTER_MODEL", "claude-3-haiku-20240307")
        resolved_temp = 0.0 if temperature is None else float(temperature)
        resolved_max_tokens = int(os.getenv("CLAUDE_ROUTER_MAX_TOKENS", "120"))
        if max_tokens is not None:
            resolved_max_tokens = int(max_tokens)
        resolved_timeout = int(os.getenv("CLAUDE_ROUTER_TIMEOUT", "12"))
        if timeout is not None:
            resolved_timeout = int(timeout)

        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=resolved_model,
            temperature=resolved_temp,
            system=system,
            messages=messages,
            max_tokens=resolved_max_tokens,
            timeout=resolved_timeout,
        )
        return response.content[0].text, None
    except Exception as exc:
        return None, f"Anthropic router error: {exc}"
