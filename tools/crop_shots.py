"""Crop slide-sized details out of the full-page screenshots.

The report wants whole screens — context matters when you are reading. A slide
wants the one thing being pointed at, because a full page shrunk to fit a
slide is unreadable. Rather than capture everything twice, the detail crops
are cut from the same source images here, so both documents are provably
showing the same run.

Uses macOS `sips` so there is no image library to install.

    python tools/crop_shots.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SHOTS = PROJECT / "output" / "screenshots"
OUT = SHOTS / "slides"

# source -> (name, offset_y, offset_x, height, width), in the 800x550 source.
CROPS = [
    # the scorecard grid, from the column headers down past the two summary
    # rows that decide it
    ("05-scorecard.jpg",             "scorecard.jpg",  150, 30, 392, 760),
    # one quarantined entry, close up
    ("09-injection-quarantined.jpg", "quarantine.jpg", 198, 36, 158, 730),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for src, dst, y, x, h, w in CROPS:
        subprocess.run(
            ["sips", "-c", str(h), str(w), "--cropOffset", str(y), str(x),
             str(SHOTS / src), "--out", str(OUT / dst)],
            check=True, stdout=subprocess.DEVNULL,
        )
        print(f"{src} -> slides/{dst}  {w}x{h} at ({x},{y})")


if __name__ == "__main__":
    main()
