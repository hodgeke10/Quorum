"""Data access and group state for Quorum's tools.

Three responsibilities, kept here so `server.py` is only tool signatures:

1. Load the destination / seasonality / fare / lodging snapshot from `data/`.
2. Hold the current planning group — travelers, their parsed calendars, their
   preferences — for the life of one planning session.
3. Sanitize calendar text. Event titles are untrusted input uploaded by five
   different people, so by default nothing an agent sees carries free text
   from a .ics file at all: a busy block is a pair of dates and nothing else.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from threading import Lock
from uuid import uuid4

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DATA = PROJECT / "data"

# ---------------------------------------------------------------- snapshot


def _rows(name: str) -> list[dict]:
    with (DATA / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class Snapshot:
    """The priced world the agents plan against, loaded once."""

    def __init__(self, sample_only: bool = False) -> None:
        self.sample_only = sample_only
        dests = _rows("destinations.csv")
        if sample_only:
            dests = [d for d in dests if d["in_sample"] == "yes"]
        self.destinations = {d["dest_code"]: d for d in dests}

        self.seasonality = {
            (r["dest_code"], int(r["month"])): r
            for r in _rows("seasonality.csv")
            if r["dest_code"] in self.destinations
        }
        self.fares = {
            (r["origin"], r["dest_code"], int(r["month"])): int(r["median_roundtrip_usd"])
            for r in _rows("fares.csv")
            if r["dest_code"] in self.destinations
        }
        self.lodging = {
            (r["dest_code"], int(r["month"]), r["tier"]): int(r["nightly_usd"])
            for r in _rows("lodging.csv")
            if r["dest_code"] in self.destinations
        }

    @property
    def origins(self) -> set[str]:
        return {o for (o, _, _) in self.fares}


# ------------------------------------------------------------ sanitizing

# Phrases that have no business in a calendar event title and every business
# in a prompt-injection payload. Matching one does not change what the agents
# see — titles are already withheld — it raises a flag for the human.
# Named heuristics. Each is a phrase that has no business in a calendar event
# title and every business in a prompt-injection payload. Matching one does not
# change what the agents see — titles are already withheld — it raises a flag
# for the human, so the name is written to be read by one.
INJECTION_RULES: list[tuple[str, str]] = [
    ("instruction override",   r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions"),
    ("instruction override",   r"disregard\s+(all\s+|every\s+)?(previous|prior|other)"),
    ("impersonates the system", r"\bsystem\s*:"),
    ("role reassignment",      r"\byou\s+are\s+now\b"),
    ("jailbreak phrasing",     r"unrestricted\s+mode|developer\s+mode"),
    ("new instructions",       r"new\s+instructions"),
    ("falsifies a cost",       r"report\s+the\s+total\s+cost\s+as"),
    ("truncates the answer",   r"output\s+only\b|and\s+stop\b"),
    ("override language",      r"\boverride\b"),
    ("prompt extraction",      r"reveal\s+(your|the)\s+(system\s+)?prompt"),
    # The two below catch the quiet version: text that asserts a group decision
    # or a budget change that no traveler actually made.
    ("asserts a decision was made", r"we\s+(already\s+)?(voted|agreed|decided)|already\s+agreed"),
    ("claims budgets changed", r"budgets?\s+(below\s+)?(are|is)\s+out\s+of\s+date|raised\s+theirs"),
]
_COMPILED = [(name, re.compile(pattern, re.I)) for name, pattern in INJECTION_RULES]

# A calendar title is a short human label. Anything much longer than this is
# not a label, and length alone is a strong signal on its own.
TITLE_LENGTH_LIMIT = 120


def scan_title(title: str) -> list[str]:
    """Return the names of any injection heuristics this title trips."""
    hits = []
    if len(title) > TITLE_LENGTH_LIMIT:
        hits.append(f"unusually long for a calendar title ({len(title)} characters)")
    for name, rx in _COMPILED:
        if name not in hits and rx.search(title):
            hits.append(name)
    return hits


# ------------------------------------------------------------ group state


@dataclass
class BusyBlock:
    start: date
    end: date           # exclusive
    title: str          # retained for the human UI, withheld from agents
    flags: list[str] = field(default_factory=list)


@dataclass
class Traveler:
    name: str
    home_airport: str
    budget_usd: int
    likes: list[str]
    dislikes: list[str]
    must_have: str
    lodging_tier: str
    busy: list[BusyBlock] = field(default_factory=list)
    # Identity has to survive a rename: calendars are re-attached by this, not
    # by what the person is currently called. Declared last so the positional
    # arguments above keep working.
    id: str = field(default_factory=lambda: uuid4().hex[:8])

    def is_free(self, start: date, end: date) -> bool:
        return not any(b.start < end and start < b.end for b in self.busy)

    def conflicts(self, start: date, end: date) -> list[BusyBlock]:
        return [b for b in self.busy if b.start < end and start < b.end]


@dataclass
class Group:
    """One planning session's travelers and settings."""

    travelers: list[Traveler] = field(default_factory=list)
    horizon_start: date = date(2027, 1, 1)
    horizon_end: date = date(2027, 12, 31)
    nights: int = 6
    # True while the roster is untouched sample data. The interface uses this
    # to decide whether resizing the group may discard people: real entries
    # are kept, sample ones are scenery.
    from_sample: bool = False
    # When False, calendar event titles are passed through to the agents.
    # This exists only so the report can show the undefended run beside the
    # defended one; the app ships defended and the UI warns loudly.
    sanitize_calendars: bool = True

    def by_name(self, name: str) -> Traveler | None:
        lowered = name.strip().lower()
        return next((t for t in self.travelers if t.name.lower() == lowered), None)

    @property
    def flagged(self) -> list[dict]:
        """Every quarantined title, for the human-facing security panel."""
        out = []
        for t in self.travelers:
            for b in t.busy:
                if b.flags:
                    out.append({
                        "traveler": t.name,
                        "dates": f"{b.start.isoformat()} to {b.end.isoformat()}",
                        "title": b.title,
                        "tripped": b.flags,
                    })
        return out


_lock = Lock()
_group = Group()
_snapshot: Snapshot | None = None


def snapshot() -> Snapshot:
    global _snapshot
    if _snapshot is None:
        _snapshot = Snapshot()
    return _snapshot


def set_snapshot(sample_only: bool) -> None:
    global _snapshot
    _snapshot = Snapshot(sample_only=sample_only)


def group() -> Group:
    return _group


def set_group(new: Group) -> None:
    global _group
    with _lock:
        _group = new


# ------------------------------------------------------------- windows


def candidate_windows(g: Group, nights: int, limit: int = 40) -> list[dict]:
    """Every start date in the horizon, scored by how many travelers are free.

    Returned sorted by fewest conflicts, then earliest. The agents never see
    event titles here — only counts and names — which is the whole point.
    """
    results = []
    day = g.horizon_start
    span = timedelta(days=nights)
    while day + span <= g.horizon_end:
        end = day + span
        free = [t.name for t in g.travelers if t.is_free(day, end)]
        blocked = [t.name for t in g.travelers if t.name not in free]
        results.append({
            "start": day.isoformat(),
            "end": end.isoformat(),
            "month": day.month,
            "nights": nights,
            "free": free,
            "blocked": blocked,
            "free_count": len(free),
        })
        day += timedelta(days=1)

    results.sort(key=lambda r: (-r["free_count"], r["start"]))

    # Collapse runs of adjacent starts with the same availability so the agent
    # sees distinct opportunities rather than 40 shifted copies of one week.
    seen: list[dict] = []
    for r in results:
        same = next(
            (s for s in seen
             if s["free_count"] == r["free_count"]
             and set(s["free"]) == set(r["free"])
             and abs((date.fromisoformat(s["start"]) - date.fromisoformat(r["start"])).days) <= nights),
            None,
        )
        if same is None:
            seen.append(r)
        if len(seen) >= limit:
            break
    return seen
