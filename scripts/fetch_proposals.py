#!/usr/bin/env python3
"""
Pull recent proposals from a curated list of Internet Computer SNS DAOs.

Emits normalized JSON to stdout. Designed to be piped to a drafter or
ingested by a weekly digest workflow.

Usage:
    python3 scripts/fetch_proposals.py                  # default targets, 6 props each
    python3 scripts/fetch_proposals.py --limit 10
    python3 scripts/fetch_proposals.py --sns openchat   # filter
    python3 scripts/fetch_proposals.py > /tmp/digest_data.json

No external deps. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from typing import Any

SNS_API_BASE = "https://sns-api.internetcomputer.org/api/v1"

# Target SNSes — curated by active governance + holder density.
# Add or remove here; each entry is (display_name, root_canister_id).
TARGETS: list[tuple[str, str]] = [
    ("OpenChat", "3e3x2-xyaaa-aaaaq-aaalq-cai"),
    ("ELNA AI", "gkoex-viaaa-aaaaq-aacmq-cai"),
    ("ICPanda", "d7wvo-iiaaa-aaaaq-aacsq-cai"),
    ("ORIGYN", "leu43-oiaaa-aaaaq-aadgq-cai"),
    ("Dragginz", "zxeu2-7aaaa-aaaaq-aaafa-cai"),
    ("Neutrinite", "extk7-gaaaa-aaaaq-aacda-cai"),
    ("ALICE", "oh4fn-kyaaa-aaaaq-aaega-cai"),
    ("ICPSwap", "csyra-haaaa-aaaaq-aacva-cai"),
    ("KongSwap", "ormnc-tiaaa-aaaaq-aadyq-cai"),
    ("SONIC", "qtooy-2yaaa-aaaaq-aabvq-cai"),
    ("Nuance", "rzbmc-yiaaa-aaaaq-aabsq-cai"),
]

USER_AGENT = "Mozilla/5.0 (compatible; SNS-Digest/0.1; +https://github.com/WoodrowLove/sns-digest)"

# SNS API rejects default Python UA — always send browser-ish UA
HEADERS = {"accept": "application/json", "user-agent": USER_AGENT}


def fetch_proposals(root: str, limit: int = 6) -> list[dict[str, Any]]:
    url = (
        f"{SNS_API_BASE}/snses/{root}/proposals"
        f"?limit={limit}&offset=0&sort_by=-proposal_creation_timestamp_seconds"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r).get("data", [])


def normalize(sns_name: str, root: str, prop: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw SNS API proposal into a stable schema for the digest."""
    tally = prop.get("latest_tally") or {}
    yes = tally.get("yes") or 0
    no = tally.get("no") or 0
    total = tally.get("total") or 1
    decided = (yes + no) > 0
    yes_pct = round(yes / max(yes + no, 1) * 100, 1) if decided else 0.0
    turnout_pct = round((yes + no) / max(total, 1) * 100, 1)

    topic_info = prop.get("topic_info") or {}
    return {
        "sns": sns_name,
        "root": root,
        "id": prop.get("id"),
        "title": prop.get("proposal_title") or "(untitled)",
        "topic": topic_info.get("name"),
        "critical": bool(topic_info.get("is_critical")),
        "status": prop.get("status"),
        "reward_status": prop.get("reward_status"),
        "url": prop.get("proposal_url"),
        "summary": (prop.get("summary") or "")[:2500],
        "payload_text": (prop.get("payload_text_rendering") or "")[:2500],
        "proposer": prop.get("proposer"),
        "yes_pct": yes_pct,
        "turnout_pct": turnout_pct,
        "created": prop.get("proposal_creation_timestamp_seconds"),
        "deadline": prop.get("wait_for_quiet_state_current_deadline_timestamp_seconds"),
    }


def run(targets: list[tuple[str, str]], limit: int, delay: float = 0.3) -> dict[str, Any]:
    """Fetch + normalize all targets. One SNS failure is isolated."""
    proposals: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for i, (name, root) in enumerate(targets):
        try:
            raw = fetch_proposals(root, limit=limit)
            for p in raw:
                proposals.append(normalize(name, root, p))
        except urllib.error.HTTPError as e:
            errors.append({"sns": name, "kind": "http", "code": str(e.code), "message": e.reason})
        except urllib.error.URLError as e:
            errors.append({"sns": name, "kind": "url", "message": str(e.reason)})
        except Exception as e:  # noqa: BLE001
            errors.append({"sns": name, "kind": "unknown", "message": str(e)})

        # Be polite to the public API
        if i < len(targets) - 1:
            time.sleep(delay)

    by_status: dict[str, int] = {}
    for p in proposals:
        by_status[p["status"] or "?"] = by_status.get(p["status"] or "?", 0) + 1

    return {
        "generated_at": int(time.time()),
        "sns_count": len(targets),
        "proposal_count": len(proposals),
        "by_status": by_status,
        "errors": errors,
        "proposals": proposals,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=6, help="Proposals per SNS (default 6)")
    parser.add_argument(
        "--sns",
        help="Filter to a single SNS by case-insensitive substring of name",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON (default: compact for piping)",
    )
    args = parser.parse_args()

    targets = TARGETS
    if args.sns:
        needle = args.sns.lower()
        targets = [(n, r) for (n, r) in TARGETS if needle in n.lower()]
        if not targets:
            print(f"no SNS matched filter: {args.sns!r}", file=sys.stderr)
            return 2

    result = run(targets, limit=args.limit)

    if args.pretty:
        json.dump(result, sys.stdout, indent=2, default=str)
    else:
        json.dump(result, sys.stdout, default=str)
    print()

    # Brief summary to stderr so humans see it even when stdout is piped
    err_count = len(result["errors"])
    print(
        f"[fetch_proposals] {result['proposal_count']} proposals from "
        f"{result['sns_count'] - err_count}/{result['sns_count']} SNSes "
        f"({err_count} errors) — status: {result['by_status']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
