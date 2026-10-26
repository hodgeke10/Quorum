"""FastAPI backend for Quorum.

Serves the single-page frontend and the routes it calls. The frontend has no
build step on purpose: a fresh clone runs this one command and the app is up,
which is what the assignment's ten-minute rule asks for.

Run from this folder:  uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import json
import random
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from config import MODEL_NAME, PROJECT, credential

MCP_DIR = PROJECT / "mcp_server"
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

import trace_log  # noqa: E402
import trip_data as td  # noqa: E402
from agents import build_team, plan  # noqa: E402
from calendars import CalendarError, parse_ics  # noqa: E402

FRONTEND = PROJECT / "frontend"
DATA = PROJECT / "data"

app = FastAPI(title="Quorum", version="1.0")

# Planning runs this process has started, keyed by run_id.
RUNS: dict[str, dict[str, Any]] = {}


# ------------------------------------------------------------- the group


class TravelerIn(BaseModel):
    id: str = ""
    name: str
    home_airport: str = "JFK"
    budget_usd: int = Field(default=1200, ge=100, le=20000)
    likes: list[str] = []
    dislikes: list[str] = []
    must_have: str = ""
    lodging_tier: str = "mid"


class GroupIn(BaseModel):
    travelers: list[TravelerIn] = []
    nights: int = Field(default=6, ge=1, le=30)
    horizon_start: str = "2027-01-01"
    horizon_end: str = "2027-12-31"
    sanitize_calendars: bool = True


def _group_state() -> dict:
    g = td.group()
    snap = td.snapshot()
    return {
        "nights": g.nights,
        "horizon_start": g.horizon_start.isoformat(),
        "horizon_end": g.horizon_end.isoformat(),
        "sanitize_calendars": g.sanitize_calendars,
        "from_sample": g.from_sample,
        "destinations_loaded": len(snap.destinations),
        "sample_only": snap.sample_only,
        "travelers": [
            {
                "id": t.id,
                "name": t.name,
                "home_airport": t.home_airport,
                "budget_usd": t.budget_usd,
                "likes": t.likes,
                "dislikes": t.dislikes,
                "must_have": t.must_have,
                "lodging_tier": t.lodging_tier,
                "busy_blocks": [
                    {
                        "start": b.start.isoformat(),
                        "end": b.end.isoformat(),
                        # The human who uploaded the calendar may see its text;
                        # the agents never do. Flagged entries are marked so the
                        # UI can show them as quarantined rather than as events.
                        "title": b.title,
                        "flags": b.flags,
                    }
                    for b in t.busy
                ],
            }
            for t in g.travelers
        ],
        "flagged": g.flagged,
    }


@app.get("/api/state")
def get_state() -> dict:
    try:
        provider, _ = credential()
        key_status = f"{provider} key loaded"
    except RuntimeError as exc:
        provider, key_status = "none", str(exc)
    return {"model": MODEL_NAME, "provider": provider, "key_status": key_status,
            "group": _group_state()}


@app.post("/api/group")
def set_group(payload: GroupIn) -> dict:
    """Replace the roster from the form, keeping any calendars already parsed."""
    # Keyed by id. It used to be keyed by name, which meant renaming somebody
    # silently dropped the calendar they had already uploaded; the name is kept
    # as a fallback for a caller that does not send ids.
    current = td.group().travelers
    by_id = {t.id: t.busy for t in current if t.id}
    by_name = {t.name.strip().lower(): t.busy for t in current}
    try:
        horizon_start = date.fromisoformat(payload.horizon_start)
        horizon_end = date.fromisoformat(payload.horizon_end)
    except ValueError:
        raise HTTPException(400, "Dates must be YYYY-MM-DD.")
    if horizon_end <= horizon_start:
        raise HTTPException(400, "The horizon must end after it starts.")

    g = td.Group(
        nights=payload.nights, horizon_start=horizon_start, horizon_end=horizon_end,
        sanitize_calendars=payload.sanitize_calendars,
    )
    for t in payload.travelers:
        kept = by_id.get(t.id) if t.id else None
        if kept is None:
            kept = by_name.get(t.name.strip().lower(), [])
        traveler = td.Traveler(
            name=t.name.strip(), home_airport=t.home_airport.strip().upper(),
            budget_usd=t.budget_usd, likes=t.likes, dislikes=t.dislikes,
            must_have=t.must_have.strip(), lodging_tier=t.lodging_tier,
            busy=kept,
        )
        if t.id:
            traveler.id = t.id
        g.travelers.append(traveler)
    td.set_group(g)
    return _group_state()


ATTACK_FIXTURES = {"overt": "injected.ics", "subtle": "subtle.ics"}

# Used only when nothing else says how many people to pick.
DEFAULT_SAMPLE_SIZE = 5


@app.post("/api/group/sample")
def load_sample(attack: str = "none", count: int = 0, seed: int | None = None) -> dict:
    """Load a demo group drawn at random from the twelve sample travelers.

    `count` is how many people to pick; it defaults to the size of the group
    already on the roster, so clicking "try the sample group" fills exactly the
    number of places the user asked for rather than overwriting their choice.

    `attack` swaps one traveler's calendar for an adversarial fixture: `overt`
    is the shouty "ignore your instructions" payload, `subtle` is the one that
    reads like a note from a friend. The fixture always lands on the first
    traveler picked, so the demonstration works whoever comes up.

    `seed` makes the draw reproducible, which the safety harness relies on to
    compare runs; the interface never passes one.
    """
    # `attack=true` kept working so existing links and notes do not break.
    if attack in ("true", "1"):
        attack = "overt"

    roster = json.loads((DATA / "travelers.json").read_text(encoding="utf-8"))
    everyone = roster["travelers"]

    wanted = count or len(td.group().travelers) or DEFAULT_SAMPLE_SIZE
    wanted = max(2, min(wanted, len(everyone)))
    chosen = random.Random(seed).sample(everyone, wanted)

    g = td.Group()
    for i, row in enumerate(chosen):
        path = DATA / row["calendar"]
        if attack in ATTACK_FIXTURES and i == 0:
            path = DATA / "attack" / ATTACK_FIXTURES[attack]
        traveler = td.Traveler(
            name=row["name"], home_airport=row["home_airport"],
            budget_usd=row["budget_usd"], likes=row["likes"],
            dislikes=row["dislikes"], must_have=row["must_have"],
            lodging_tier=row["lodging_tier"],
        )
        traveler.busy = parse_ics(
            path.read_bytes(), horizon_start=g.horizon_start, horizon_end=g.horizon_end
        )
        g.travelers.append(traveler)
    g.from_sample = True
    td.set_group(g)
    return _group_state()


@app.post("/api/group/calendar")
async def upload_calendar(name: str = Form(...), file: UploadFile = File(...),
                          traveler_id: str = Form("")) -> dict:
    """Attach an uploaded .ics to a traveler already on the roster."""
    g = td.group()
    traveler = next((t for t in g.travelers if t.id and t.id == traveler_id), None)
    if traveler is None:
        traveler = g.by_name(name)
    if traveler is None:
        raise HTTPException(404, f"No traveler named {name} on the roster.")
    try:
        traveler.busy = parse_ics(
            await file.read(), horizon_start=g.horizon_start, horizon_end=g.horizon_end
        )
    except CalendarError as exc:
        raise HTTPException(400, str(exc))
    g.from_sample = False
    return _group_state()


@app.post("/api/settings/dataset")
def set_dataset(sample_only: bool = False) -> dict:
    """Switch between the six-destination test set and the full snapshot.

    Deliberately not in the interface: narrowing the catalogue is something a
    reviewer might want, but to a group planning a trip it looks like a trip
    setting and makes the slate worse for no reason they can see. The README
    documents how to call it.
    """
    td.set_snapshot(sample_only)
    return _group_state()


# -------------------------------------------------------------- planning


@app.post("/api/plan")
async def start_plan(background: BackgroundTasks) -> dict:
    g = td.group()
    if len(g.travelers) < 2:
        raise HTTPException(400, "Add at least two travelers first.")
    if not any(t.busy for t in g.travelers):
        raise HTTPException(400, "Nobody has a calendar loaded yet.")
    try:
        credential()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))

    job_id = uuid.uuid4().hex[:12]
    RUNS[job_id] = {"job_id": job_id, "status": "running", "phase": "Starting",
                    "result": None, "error": None}
    background.add_task(_run_plan, job_id)
    return {"job_id": job_id}


async def _run_plan(job_id: str) -> None:
    def progress(label: str) -> None:
        RUNS[job_id]["phase"] = label

    try:
        result = await plan(progress=progress)
        RUNS[job_id].update(status="done", phase="Done", result=result)
    except Exception as exc:
        RUNS[job_id].update(status="error", phase="Failed", error=f"{type(exc).__name__}: {exc}")


@app.get("/api/plan/{job_id}")
def get_plan(job_id: str) -> dict:
    run = RUNS.get(job_id)
    if run is None:
        raise HTTPException(404, "No such run.")
    return run


@app.get("/api/trace/{run_id}")
def get_trace(run_id: str) -> dict:
    trace = trace_log.get(run_id)
    if trace is None:
        raise HTTPException(404, "No such trace.")
    return trace.as_dict()


@app.get("/api/tokenomics/{run_id}")
def tokenomics(run_id: str, runs_per_user_per_month: int = 2) -> dict:
    """Measured cost for one run, projected out to a user base."""
    trace = trace_log.get(run_id)
    if trace is None:
        raise HTTPException(404, "No such run.")
    usage = trace.usage
    per_run = usage.cost_usd
    per_user_month = round(per_run * runs_per_user_per_month, 4)
    return {
        "run_id": run_id,
        "price_per_mtok": trace_log.PRICE_PER_MTOK,
        "price_source": trace_log.PRICE_SOURCE,
        "usage": usage.as_dict(),
        "by_agent": {k: v.as_dict() for k, v in trace.by_agent.items()},
        "tool_calls": trace.tool_calls,
        "cache_hits": trace.cache_hits,
        "cost_per_run_usd": per_run,
        "runs_per_user_per_month": runs_per_user_per_month,
        "cost_per_user_per_month_usd": per_user_month,
        "monthly_at_100_users_usd": round(per_user_month * 100, 2),
        "monthly_at_10000_users_usd": round(per_user_month * 10_000, 2),
    }


@app.get("/api/security")
def security() -> dict:
    import server
    return server.security_report()


# -------------------------------------------------------------- frontend

# The frontend is two files edited constantly during development, so they are
# served with revalidation forced rather than mounted as cacheable statics. A
# stale app.js against a fresh index.html is a confusing bug to chase.
NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}


@app.get("/static/{name}")
def asset(name: str) -> FileResponse:
    path = (FRONTEND / name).resolve()
    if path.parent != FRONTEND.resolve() or not path.is_file():
        raise HTTPException(404, "No such asset.")
    return FileResponse(path, headers=NO_CACHE)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers=NO_CACHE)


@app.on_event("startup")
def _startup() -> None:
    try:
        build_team()
    except RuntimeError:
        # No key yet: the UI reports it rather than the server refusing to boot.
        pass
