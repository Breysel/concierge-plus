from typing import Tuple


def rank_metrics(mode: str, deep_cuts_strict: bool) -> Tuple[str, str]:
    mode = (mode or "").strip().lower()
    if mode == "find":
        return "unique_users", "score_poplite"
    if mode == "gateway":
        return "score_poplite", "unique_users"
    if mode == "vibe":
        return "score_sticky", "score_poplite"
    if mode == "deep_dive":
        primary = "score_hidden_gem_strict" if deep_cuts_strict else "score_hidden_gem"
        return primary, "score_poplite"
    if mode == "performer_led":
        primary = "score_hidden_gem" if deep_cuts_strict else "score_poplite"
        return primary, "unique_users"
    if mode == "atmos":
        return "score_poplite", "unique_users"
    if mode == "continue":
        return "score_poplite", "unique_users"
    return "score_poplite", "unique_users"
