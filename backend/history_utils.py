import re
from typing import Iterable, Dict, Any, Set

STAGE_PLUS_ALBUM_RE = re.compile(r"https?://www\.stage-plus\.com/audio/album_[A-Za-z0-9]+")


def extract_album_urls_from_history(history: Iterable[Dict[str, Any]]) -> Set[str]:
    urls: Set[str] = set()
    for message in history or []:
        if message.get("role") == "assistant":
            for url in STAGE_PLUS_ALBUM_RE.findall(message.get("content") or ""):
                urls.add(url)
    return urls
