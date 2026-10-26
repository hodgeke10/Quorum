"""Parse uploaded .ics files into busy blocks.

Everything here treats the file as hostile input. A .ics is a text file a
third party hands you, and Quorum feeds date ranges from it into an LLM, so
the parser's job is to extract dates and throw the prose away — or, when the
defenses are deliberately disabled for the report's comparison run, to mark
the prose as quarantined so the rest of the app still knows what it is.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from icalendar import Calendar

from trip_data import BusyBlock, scan_title

# A single .ics should not be able to exhaust memory or the context window.
MAX_BYTES = 2_000_000
MAX_EVENTS = 500


class CalendarError(ValueError):
    """The upload was not a usable calendar."""


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def parse_ics(raw: bytes | str, *, horizon_start: date, horizon_end: date) -> list[BusyBlock]:
    """Return the busy blocks a calendar contributes inside the horizon."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise CalendarError(
            f"Calendar is {len(raw) // 1000} KB; the limit is {MAX_BYTES // 1000} KB."
        )

    try:
        cal = Calendar.from_ical(raw)
    except Exception as exc:  # icalendar raises a grab-bag of exception types
        raise CalendarError(f"Could not read this as an .ics file: {exc}") from None

    blocks: list[BusyBlock] = []
    for component in cal.walk("VEVENT"):
        if len(blocks) >= MAX_EVENTS:
            break

        start = _as_date(getattr(component.get("DTSTART"), "dt", None))
        if start is None:
            continue

        end = _as_date(getattr(component.get("DTEND"), "dt", None))
        if end is None:
            duration = component.get("DURATION")
            if duration is not None and getattr(duration, "dt", None):
                end = start + duration.dt
            else:
                end = start + timedelta(days=1)
        end = _as_date(end) or start + timedelta(days=1)
        if end <= start:
            end = start + timedelta(days=1)

        # Free-time events do not block a trip.
        if str(component.get("TRANSP", "OPAQUE")).upper() == "TRANSPARENT":
            continue
        if str(component.get("STATUS", "")).upper() == "CANCELLED":
            continue

        # Outside the planning horizon it cannot affect any window.
        if end <= horizon_start or start >= horizon_end:
            continue

        title = str(component.get("SUMMARY", "") or "").strip()
        blocks.append(BusyBlock(start=start, end=end, title=title, flags=scan_title(title)))

    if not blocks:
        raise CalendarError(
            "No events found in the planning horizon. Check that the export "
            "covers the dates you want to plan across."
        )

    blocks.sort(key=lambda b: b.start)
    return blocks
