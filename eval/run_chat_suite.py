import argparse
import json
import os
import re
import sys
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple

import requests

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from eval.chat_suite_cases import SINGLE_TURN_CASES, MULTI_TURN_SCENARIOS

ALBUM_URL_RE = re.compile(r"https?://[^\s)]+/audio/album_[A-Za-z0-9]+")
LEAK_TOKENS = [
    "Candidate JSON",
    "routing",
    "router",
    "rank_by",
    "filters_relaxed",
    "system prompt",
]
DE_TOKENS = [" und ", " nicht ", " für ", " ich ", " du ", " mir ", " etwas ", " gern "]


def _now_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_album_urls(text: str) -> List[str]:
    if not text:
        return []
    return ALBUM_URL_RE.findall(text)


def _has_japanese(text: str) -> bool:
    if not text:
        return False
    for ch in text:
        code = ord(ch)
        if 0x3040 <= code <= 0x30FF:
            return True
        if 0x4E00 <= code <= 0x9FFF:
            return True
    return False


def _has_german(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    if any(token in lower for token in DE_TOKENS):
        return True
    return any(ch in text for ch in "äöüßÄÖÜ")


def _check_language(lang_seen: str, reply: str) -> Tuple[bool, str]:
    if lang_seen == "ja":
        return (_has_japanese(reply), "lang_expected_ja")
    if lang_seen == "de":
        return (_has_german(reply), "lang_expected_de")
    return (True, "")


def _check_leaks(reply: str) -> Tuple[bool, List[str]]:
    hits = []
    for token in LEAK_TOKENS:
        if token.lower() in (reply or "").lower():
            hits.append(token)
    return (len(hits) == 0, hits)


def _check_reply(case: Dict[str, Any], response_json: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons = []
    reply = (response_json.get("reply") or "").strip()
    mode = (response_json.get("mode") or "").strip()
    expected_mode = case.get("expected_mode")

    if expected_mode != mode:
        reasons.append(f"mode_expected_{expected_mode}")

    urls = _extract_album_urls(reply)
    min_urls = int(case.get("min_album_urls", 0))
    max_urls = int(case.get("max_album_urls", 0))

    if expected_mode == "reco":
        if not (min_urls <= len(urls) <= max_urls):
            reasons.append("album_url_count_out_of_range")
        if case.get("require_followup_feedback"):
            if "Follow-up:" not in reply:
                reasons.append("missing_followup")
            if "Feedback:" not in reply:
                reasons.append("missing_feedback")
    else:
        if len(urls) != 0:
            reasons.append("unexpected_album_url")

    ok_lang, lang_reason = _check_language(case.get("lang_seen"), reply)
    if not ok_lang:
        reasons.append(lang_reason)

    ok_leaks, leak_hits = _check_leaks(reply)
    if not ok_leaks:
        reasons.append("leak: " + ", ".join(leak_hits))

    return (len(reasons) == 0, reasons)


def _post_chat(
    base_url: str,
    message: str,
    conversation_id: str,
    timeout: int,
    debug: bool,
) -> Tuple[int, Dict[str, Any], int]:
    payload = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if debug:
        payload["debug"] = True

    start = time.perf_counter()
    response = requests.post(f"{base_url}/chat", json=payload, timeout=timeout)
    latency_ms = int((time.perf_counter() - start) * 1000)
    try:
        data = response.json()
    except ValueError:
        data = {"_raw": response.text}
    return response.status_code, data, latency_ms


def _write_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_suite(args: argparse.Namespace) -> None:
    run_id = str(uuid.uuid4())
    out_path = args.out
    sleep_s = max(0, int(args.sleep_ms)) / 1000.0
    timeout = int(args.timeout)
    debug = args.debug

    totals = 0
    passes = 0
    failures: List[str] = []
    latencies: List[int] = []
    mode_counts = Counter()

    def record_result(row: Dict[str, Any]) -> None:
        nonlocal totals, passes
        totals += 1
        if row.get("pass"):
            passes += 1
        else:
            failures.append(row.get("case_id"))
        if isinstance(row.get("latency_ms"), int):
            latencies.append(row["latency_ms"])
        expected_mode = row.get("expected", {}).get("expected_mode")
        if expected_mode:
            mode_counts[expected_mode] += 1

    rows: List[Dict[str, Any]] = []

    for case in SINGLE_TURN_CASES:
        status_code, response_json, latency_ms = _post_chat(
            args.base_url,
            case["message"],
            "",
            timeout,
            debug,
        )
        extracted_urls = _extract_album_urls(response_json.get("reply") or "")
        passed = False
        fail_reasons: List[str] = []
        if status_code == 200:
            passed, fail_reasons = _check_reply(case, response_json)
        else:
            fail_reasons = [f"http_{status_code}"]
        row = {
            "run_id": run_id,
            "ts_utc": _now_ts(),
            "case_id": case["id"],
            "message": case["message"],
            "expected": {
                "expected_mode": case["expected_mode"],
                "lang_seen": case["lang_seen"],
                "min_album_urls": case["min_album_urls"],
                "max_album_urls": case["max_album_urls"],
                "require_followup_feedback": case["require_followup_feedback"],
            },
            "status_code": status_code,
            "response_json": response_json,
            "latency_ms": latency_ms,
            "extracted_album_urls": extracted_urls,
            "pass": passed,
            "fail_reasons": fail_reasons,
        }
        rows.append(row)
        record_result(row)
        if sleep_s:
            time.sleep(sleep_s)

    if args.include_multiturn:
        for scenario in MULTI_TURN_SCENARIOS:
            conversation_id = str(uuid.uuid4())
            for idx, turn in enumerate(scenario["turns"], start=1):
                status_code, response_json, latency_ms = _post_chat(
                    args.base_url,
                    turn["message"],
                    conversation_id,
                    timeout,
                    debug,
                )
                extracted_urls = _extract_album_urls(response_json.get("reply") or "")
                passed = False
                fail_reasons: List[str] = []
                if status_code == 200:
                    passed, fail_reasons = _check_reply(turn, response_json)
                else:
                    fail_reasons = [f"http_{status_code}"]
                row = {
                    "run_id": run_id,
                    "ts_utc": _now_ts(),
                    "scenario_id": scenario["id"],
                    "turn_idx": idx,
                    "case_id": turn["id"],
                    "message": turn["message"],
                    "expected": {
                        "expected_mode": turn["expected_mode"],
                        "lang_seen": turn["lang_seen"],
                        "min_album_urls": turn["min_album_urls"],
                        "max_album_urls": turn["max_album_urls"],
                        "require_followup_feedback": turn["require_followup_feedback"],
                    },
                    "status_code": status_code,
                    "response_json": response_json,
                    "latency_ms": latency_ms,
                    "extracted_album_urls": extracted_urls,
                    "pass": passed,
                    "fail_reasons": fail_reasons,
                }
                rows.append(row)
                record_result(row)
                if sleep_s:
                    time.sleep(sleep_s)

    _write_jsonl(out_path, rows)

    pass_rate = (passes / totals) if totals else 0.0
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0
    print("Chat suite summary")
    print(f"Run ID: {run_id}")
    print(f"Total: {totals}  Pass: {passes}  Fail: {totals - passes}")
    print(f"Pass rate: {pass_rate:.2%}")
    print(f"Avg latency: {avg_latency} ms")
    if failures:
        print("Failures:")
        for failure in failures:
            print(f"- {failure}")
    print("Expected mode counts:")
    for mode, count in mode_counts.items():
        print(f"- {mode}: {count}")
    print(f"Results: {out_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage+ Concierge chat suite.")
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="Base URL for /chat"
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    parser.add_argument(
        "--out",
        default=f"eval/results/chat_suite_{timestamp}.jsonl",
        help="Output JSONL path",
    )
    parser.add_argument("--sleep-ms", default=250, type=int, help="Sleep between calls")
    parser.add_argument("--timeout", default=60, type=int, help="Request timeout")
    parser.add_argument("--debug", default=True, type=lambda v: str(v).lower() != "false")
    parser.add_argument(
        "--include-multiturn",
        default=True,
        type=lambda v: str(v).lower() != "false",
        help="Include multi-turn scenarios",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_suite(args)


if __name__ == "__main__":
    main()
