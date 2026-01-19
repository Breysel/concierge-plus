import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Tuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _summarize(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    totals = 0
    passes = 0
    failures: List[str] = []
    latencies: List[int] = []
    mode_counts = Counter()
    fail_reasons = Counter()
    case_ids = []

    for row in rows:
        totals += 1
        case_id = row.get("case_id")
        case_ids.append(case_id)
        if row.get("pass"):
            passes += 1
        else:
            failures.append(case_id)
            for reason in row.get("fail_reasons") or []:
                fail_reasons[reason] += 1
        latency = row.get("latency_ms")
        if isinstance(latency, int):
            latencies.append(latency)
        expected_mode = row.get("expected", {}).get("expected_mode")
        if expected_mode:
            mode_counts[expected_mode] += 1

    pass_rate = (passes / totals) if totals else 0.0
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0
    return {
        "totals": totals,
        "passes": passes,
        "fails": totals - passes,
        "pass_rate": pass_rate,
        "avg_latency": avg_latency,
        "failures": failures,
        "mode_counts": dict(mode_counts),
        "fail_reasons": dict(fail_reasons),
        "case_ids": case_ids,
    }


def _compare(base: Dict[str, Any], other: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "pass_rate_delta": other["pass_rate"] - base["pass_rate"],
        "avg_latency_delta": other["avg_latency"] - base["avg_latency"],
        "fails_delta": other["fails"] - base["fails"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score Stage+ Concierge chat suite.")
    parser.add_argument("run", help="Run JSONL file")
    parser.add_argument("--compare", help="Compare against another run")
    args = parser.parse_args()

    rows = _read_jsonl(args.run)
    summary = _summarize(rows)

    print("Chat suite score")
    print(f"Total: {summary['totals']}  Pass: {summary['passes']}  Fail: {summary['fails']}")
    print(f"Pass rate: {summary['pass_rate']:.2%}")
    print(f"Avg latency: {summary['avg_latency']} ms")
    if summary["failures"]:
        print("Failures:")
        for failure in summary["failures"]:
            print(f"- {failure}")
    if summary["fail_reasons"]:
        print("Failure reasons:")
        for reason, count in summary["fail_reasons"].items():
            print(f"- {reason}: {count}")
    if summary["mode_counts"]:
        print("Expected mode counts:")
        for mode, count in summary["mode_counts"].items():
            print(f"- {mode}: {count}")

    if args.compare:
        other_rows = _read_jsonl(args.compare)
        other_summary = _summarize(other_rows)
        deltas = _compare(summary, other_summary)
        base_cases = set(summary["case_ids"])
        other_cases = set(other_summary["case_ids"])
        regressed = sorted(base_cases - other_cases)

        print("Comparison")
        print(f"Pass rate delta: {deltas['pass_rate_delta']:.2%}")
        print(f"Avg latency delta: {deltas['avg_latency_delta']} ms")
        print(f"Fails delta: {deltas['fails_delta']}")
        if regressed:
            print("Missing cases in compare run:")
            for case_id in regressed:
                print(f"- {case_id}")


if __name__ == "__main__":
    main()
