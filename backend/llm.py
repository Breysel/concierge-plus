import os
from functools import lru_cache
from typing import List, Dict, Optional, Tuple, Generator


DEFAULT_ROUTER_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_WRITER_MODEL = "claude-sonnet-4-5-20250929"


def get_secret(name: str) -> Optional[str]:
    return os.getenv(name)


def _get_anthropic_api_key() -> Optional[str]:
    return get_secret("ANTHROPIC_API_KEY")


@lru_cache(maxsize=2)
def get_anthropic_client(api_key: str):
    from anthropic import Anthropic

    timeout = int(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "30"))
    return Anthropic(api_key=api_key, timeout=timeout)


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
        resolved_model = model or DEFAULT_WRITER_MODEL
        resolved_temp = (
            temperature if temperature is not None else float(os.getenv("CLAUDE_TEMPERATURE", "0.3"))
        )
        resolved_max_tokens = int(os.getenv("CLAUDE_MAX_TOKENS", "500"))
        if max_tokens is not None:
            resolved_max_tokens = int(max_tokens)
        resolved_timeout = int(os.getenv("CLAUDE_TIMEOUT", "18"))
        if timeout is not None:
            resolved_timeout = int(timeout)

        client = get_anthropic_client(api_key)
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


def call_anthropic_writer(
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
        resolved_model = model or DEFAULT_WRITER_MODEL
        resolved_temp = (
            temperature if temperature is not None else float(os.getenv("CLAUDE_TEMPERATURE", "0.3"))
        )
        resolved_max_tokens = int(os.getenv("CLAUDE_MAX_TOKENS", "500"))
        if max_tokens is not None:
            resolved_max_tokens = int(max_tokens)
        resolved_timeout = int(os.getenv("CLAUDE_TIMEOUT", "18"))
        if timeout is not None:
            resolved_timeout = int(timeout)

        client = get_anthropic_client(api_key)
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
        return None, f"Anthropic writer error: {exc}"


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

    resolved_model = model or os.getenv("CLAUDE_MODEL", DEFAULT_WRITER_MODEL)
    resolved_temp = (
        temperature if temperature is not None else float(os.getenv("CLAUDE_TEMPERATURE", "0.3"))
    )
    resolved_max_tokens = int(os.getenv("CLAUDE_MAX_TOKENS", "500"))
    if max_tokens is not None:
        resolved_max_tokens = int(max_tokens)
    resolved_timeout = int(os.getenv("CLAUDE_TIMEOUT", "18"))
    if timeout is not None:
        resolved_timeout = int(timeout)

    client = get_anthropic_client(api_key)
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
        resolved_model = model or DEFAULT_ROUTER_MODEL
        resolved_temp = 0.0 if temperature is None else float(temperature)
        resolved_max_tokens = int(os.getenv("CLAUDE_ROUTER_MAX_TOKENS", "200"))
        if max_tokens is not None:
            resolved_max_tokens = int(max_tokens)
        resolved_max_tokens = min(resolved_max_tokens, 300)
        resolved_timeout = int(os.getenv("CLAUDE_ROUTER_TIMEOUT", "12"))
        if timeout is not None:
            resolved_timeout = int(timeout)

        client = get_anthropic_client(api_key)
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
