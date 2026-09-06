#!/usr/bin/env python3
"""Fail if the frontend's TypeScript interfaces drift from the backend schemas.

The two are maintained by hand, so this compares the property names in
`frontend/src/lib/types.ts` against the live OpenAPI document. A mismatch here
is a silent runtime bug — the compiler cannot see it.

Usage:  python3 scripts/check-api-types.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# TypeScript interface -> Pydantic response model
PAIRS = [
    ("Job", "JobRead"),
    ("JobSummary", "JobSummary"),
    ("JobCriteria", "JobCriteria"),
    ("ScreeningQuestion", "ScreeningQuestion"),
    ("ScreeningPlan", "ScreeningPlan"),
    ("ParsePreview", "ParsePreview"),
    ("Candidate", "CandidateRead"),
    ("SearchRun", "SearchRunRead"),
    ("SearchResponse", "SearchResponse"),
    ("Call", "CallWithCandidate"),
    ("Campaign", "CampaignRead"),
    ("CampaignStats", "CampaignStats"),
    ("CampaignDetail", "CampaignDetail"),
    ("CampaignSummary", "CampaignSummary"),
    ("LaunchResponse", "LaunchResponse"),
]

ROOT = Path(__file__).resolve().parent.parent
TYPES = ROOT / "frontend" / "src" / "lib" / "types.ts"


def ts_fields(source: str, name: str) -> set[str] | None:
    match = re.search(rf"export interface {name} \{{(.*?)\n\}}", source, re.S)
    if not match:
        return None
    return set(re.findall(r"^\s{2}(\w+)\??:", match.group(1), re.M))


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/openapi.json", timeout=10) as response:
            schemas = json.load(response)["components"]["schemas"]
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Could not reach the backend at {base}: {exc}")
        print("Start it first:  cd backend && ./.venv/bin/uvicorn app.main:app --port 8000")
        return 2

    source = TYPES.read_text()
    problems = 0
    for ts_name, api_name in PAIRS:
        api = schemas.get(api_name)
        if api is None:
            print(f"FAIL  {api_name} is not in the OpenAPI document")
            problems += 1
            continue
        expected = set(api.get("properties", {}))
        actual = ts_fields(source, ts_name)
        if actual is None:
            print(f"FAIL  interface {ts_name} not found in {TYPES.name}")
            problems += 1
            continue
        missing, extra = expected - actual, actual - expected
        if missing or extra:
            problems += 1
            print(f"FAIL  {ts_name} vs {api_name}")
            if missing:
                print(f"        missing in TypeScript: {', '.join(sorted(missing))}")
            if extra:
                print(f"        not in the API:        {', '.join(sorted(extra))}")
        else:
            print(f"ok    {ts_name} == {api_name}")

    print()
    print(f"{len(PAIRS) - problems}/{len(PAIRS)} interfaces match")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
