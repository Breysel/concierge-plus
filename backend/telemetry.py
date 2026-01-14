import csv
import json
import os
import re
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional

_LOG_LOCK = Lock()


def get_log_dir() -> str:
    override = os.getenv("CONCIERGE_LOG_DIR")
    if override:
        return override
    if os.path.isdir("/var/data"):
        return "/var/data/concierge_plus_logs"
    return "/tmp/concierge_plus_logs"


def truncate(text: str, max_chars: int = 20000) -> str:
    if text is None:
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(obj, ensure_ascii=True)
    with _LOG_LOCK:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def append_csv(path: str, header: Iterable[str], row: Iterable[Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_header = not os.path.exists(path)
    with _LOG_LOCK:
        with open(path, "a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(list(header))
            writer.writerow(list(row))


def extract_urls_from_markdown(text: str, max_urls: Optional[int] = 3) -> List[str]:
    if not text:
        return []
    pattern = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")
    urls = pattern.findall(text)
    if max_urls is None:
        return urls
    return urls[:max_urls]
