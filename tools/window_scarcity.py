"""Measure how rare a workable week is, as a group gets bigger.

This is the motivation number the report leads with, so it should be measured
rather than asserted. For each group size it draws several random groups from
the twelve sample travelers and counts the six-night windows in 2027 where
everybody is free.

    python tools/window_scarcity.py
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
for sub in ("backend", "mcp_server"):
    sys.path.insert(0, str(PROJECT / sub))

DRAWS = 8
NIGHTS = 6
SIZES = (2, 3, 4, 5, 6, 8, 10, 12)


def main() -> None:
    from fastapi.testclient import TestClient
    import main as backend
    import server
    import trip_data as td

    client = TestClient(backend.app)
    rows = []

    for size in SIZES:
        counts = []
        for seed in range(DRAWS):
            client.post(f"/api/group/sample?count={size}&seed={seed}")
            windows = server.find_windows(nights=NIGHTS, limit=400)["windows"]
            counts.append(sum(1 for w in windows if w["free_count"] == size))
        rows.append({
            "group_size": size,
            "draws": DRAWS,
            "windows_min": min(counts),
            "windows_max": max(counts),
            "windows_mean": round(sum(counts) / len(counts), 1),
        })
        print(f"  group of {size:>2}: {min(counts):>2}-{max(counts):<2} weeks work "
              f"(mean {rows[-1]['windows_mean']})")

    g = td.group()
    span = (g.horizon_end - g.horizon_start - timedelta(days=NIGHTS)).days + 1

    out = {
        "nights": NIGHTS,
        "horizon": f"{g.horizon_start.isoformat()} to {g.horizon_end.isoformat()}",
        "candidate_start_dates": span,
        "draws_per_size": DRAWS,
        "by_group_size": rows,
    }
    path = PROJECT / "output" / "evidence" / "window_scarcity.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n  {span} candidate start dates in the horizon")
    print(f"  written to {path.relative_to(PROJECT)}")


if __name__ == "__main__":
    main()
