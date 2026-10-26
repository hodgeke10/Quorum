"""Quorum's agents and the run that puts them together.

Three LLM roles:

* **Scout** — one run, with tools. Builds a slate of three to five real options.
* **Advocate** — one run *per traveler*, in parallel, with no tools. Each scores
  the whole slate from one person's point of view, 0 to 10, higher is better.
* **Chair** — one run, with tools. Picks the winner and explains who paid for it.

Pricing is not an agent. `price_trip` is exact arithmetic over the snapshot, so
it runs in Python: a language model cannot invent a number that no tool
returned if it never does the sum in the first place. The same goes for the
fit tally the Chair decides on — Python computes the ranking, the Chair
explains it, and when the two disagree the prompt tells the Chair the
arithmetic wins.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from pydantic_ai import Agent, RunContext, UsageLimits

import trace_log
from config import MODEL_NAME, MODEL_SETTINGS, build_model, load_prompt, toolset
from models import AdvocateReport, Decision, Shortlist

# A planning run that needs more than this has gone wrong. The ceiling is the
# defense against a loop quietly spending the group's money on tokens.
SCOUT_LIMITS = UsageLimits(request_limit=14, tool_calls_limit=28)
ADVOCATE_LIMITS = UsageLimits(request_limit=3, tool_calls_limit=0)
CHAIR_LIMITS = UsageLimits(request_limit=8, tool_calls_limit=12)

MAX_CANDIDATES = 5
OPTION_IDS = "ABCDE"


@dataclass
class Deps:
    """Shared state for one planning run."""

    run_id: str
    actor: str = "scout"
    traveler: str = ""
    tool_cache: dict = field(default_factory=dict)


_scout: Agent | None = None
_advocate: Agent | None = None
_chair: Agent | None = None
_built_guarded: bool | None = None


def build_team(guarded: bool = True) -> None:
    """Create the three agents, reusing them unless the guard setting changed.

    `guarded` controls whether the injection warning stays in the shared
    prompt. It is only ever False for the report's undefended baseline.
    """
    global _scout, _advocate, _chair, _built_guarded
    if _scout is not None and _built_guarded == guarded:
        return

    model = build_model()
    shared = load_prompt("_shared", guarded=guarded)
    tools = toolset()
    _built_guarded = guarded

    _scout = Agent(
        model, deps_type=Deps, output_type=Shortlist,
        system_prompt=shared + "\n\n" + load_prompt("scout"),
        toolsets=[tools], model_settings=MODEL_SETTINGS, retries=2,
    )

    # No toolset. The advocate is handed the priced slate and judges it; it has
    # nothing to look up, which keeps five parallel runs cheap and gives the
    # untrusted-input surface one fewer place to reach.
    _advocate = Agent(
        model, deps_type=Deps, output_type=AdvocateReport,
        system_prompt=shared + "\n\n" + load_prompt("advocate"),
        model_settings=MODEL_SETTINGS, retries=2,
    )

    _chair = Agent(
        model, deps_type=Deps, output_type=Decision,
        system_prompt=shared + "\n\n" + load_prompt("chair"),
        toolsets=[tools], model_settings=MODEL_SETTINGS, retries=2,
    )


async def _run(agent: Agent, prompt: str, deps: Deps, limits: UsageLimits):
    """Run one agent and fold its measured usage into the trace."""
    trace_log.record(deps.run_id, "agent_start", deps.actor, detail=_preview(prompt))
    result = await agent.run(prompt, deps=deps, usage_limits=limits)
    # `usage` is a property in current PydanticAI and was a method in older
    # releases; accept either rather than pinning to one.
    usage = result.usage() if callable(result.usage) else result.usage
    trace_log.record_usage(deps.run_id, deps.actor, usage)
    trace_log.record(deps.run_id, "agent_done", deps.actor,
                     result=result.output.model_dump())
    return result.output


def _preview(text: str, limit: int = 40_000) -> str:
    """Prompts are recorded whole.

    They were truncated at 600 characters, which quietly defeated the point of
    having a trace: the injection harness searches it to decide whether a
    payload reached a model, and anything past the cut was invisible to it.
    A brief is a few kilobytes; keep all of it.
    """
    return text if len(text) <= limit else text[:limit] + f"... [{len(text)} chars]"


# ----------------------------------------------------------- the pricing


def price_slate(shortlist: Shortlist, run_id: str) -> tuple[list[dict], list[str]]:
    """Turn the Scout's candidates into priced options. Python, not a model."""
    import server  # the MCP tools are plain callables
    import trip_data as td

    g = td.group()
    snap = td.snapshot()
    priced, rejected = [], []

    for candidate in shortlist.candidates[:MAX_CANDIDATES]:
        code = (candidate.dest_code or "").upper()
        tier = candidate.tier if candidate.tier in ("budget", "mid", "upscale") else "mid"

        if code not in snap.destinations:
            rejected.append(f"{candidate.dest_code}: not a destination in the snapshot")
            continue
        try:
            start = date.fromisoformat(candidate.start_date)
        except ValueError:
            rejected.append(f"{code}: start date '{candidate.start_date}' is not a date")
            continue
        if not (g.horizon_start <= start <= g.horizon_end - timedelta(days=g.nights)):
            rejected.append(f"{code} on {start}: outside the planning horizon")
            continue

        quote = server.price_trip(code, start.isoformat(), g.nights, tier)
        if "error" in quote:
            rejected.append(f"{code} on {start}: {quote['error']}")
            continue

        quote["option_id"] = OPTION_IDS[len(priced)]
        quote["why"] = candidate.why
        priced.append(quote)
        trace_log.record(run_id, "priced", "pricing-engine", code,
                         {"start": start.isoformat(), "tier": tier},
                         {"group_total_usd": quote["group_total_usd"]})

    for note in rejected:
        trace_log.record(run_id, "rejected", "pricing-engine", result=note)
    return priced, rejected


def _slate_text(priced: list[dict]) -> str:
    """The priced slate as the advocates and Chair see it."""
    lines = []
    for opt in priced:
        lines.append(
            f"### Option {opt['option_id']} — {opt['city']} ({opt['dest_code']}), "
            f"{opt['start']} to {opt['end']}, {opt['nights']} nights, {opt['tier']} tier\n"
            f"Why it is on the slate: {opt['why']}\n"
            f"Typically {opt['avg_high_f']}\u00b0F that month, "
            f"{opt['rain_days']} rainy days, crowd index {opt['crowd_index']}/10"
            f"{' (PEAK SEASON)' if opt['is_peak_season'] else ''}.\n"
            f"Lodging {opt['lodging_nightly_usd']}/night, "
            f"group total ${opt['group_total_usd']:,}.\n"
            "Per traveler:"
        )
        for p in opt["per_person"]:
            status = "within budget" if p["within_budget"] else f"${p['over_budget_usd']} OVER their ceiling"
            avail = "available" if p["free_these_dates"] else "NOT AVAILABLE these dates"
            lines.append(
                f"  - {p['name']} ({p['home_airport']}): flight ${p['flight_usd']}, "
                f"lodging share ${p['lodging_share_usd']}, total ${p['total_usd']} "
                f"vs ceiling ${p['budget_usd']} — {status}; {avail}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------- the scoring


def tally(priced: list[dict], reports: list[AdvocateReport]) -> dict:
    """Rank the options by their floor. Deterministic, in Python.

    The floor is the lowest fit score any traveler gave an option. Ranking by
    the highest floor picks the trip that works best for whoever it suits
    least, which is the same arithmetic as minimising the worst case — stated
    the way the group would want to hear it.
    """
    scores: dict[str, dict] = {}
    for opt in priced:
        oid = opt["option_id"]
        fits, joins = [], []
        for report in reports:
            verdict = next((v for v in report.verdicts if v.option_id == oid), None)
            if verdict is None:
                continue
            fits.append({"traveler": report.traveler, "fit": verdict.fit,
                         "would_join": verdict.would_join,
                         "one_wish": verdict.one_wish})
            joins.append(verdict.would_join)

        values = [f["fit"] for f in fits] or [0]
        scores[oid] = {
            "option_id": oid,
            "city": opt["city"],
            "start": opt["start"],
            "floor": min(values),
            "avg_fit": round(sum(values) / len(values), 2),
            "floor_traveler": min(fits, key=lambda f: f["fit"])["traveler"] if fits else None,
            "not_joining": sum(1 for j in joins if not j),
            "unavailable": len(opt["travelers_unavailable"]),
            "over_budget": len(opt["travelers_over_budget"]),
            "group_total_usd": opt["group_total_usd"],
            "per_traveler": fits,
        }

    ranked = sorted(
        scores.values(),
        key=lambda s: (-s["floor"], s["unavailable"], s["over_budget"],
                       s["group_total_usd"], -s["avg_fit"]),
    )

    # Who is flexing, measured rather than guessed: a traveler flexes on the
    # winning option by the gap between their fit there and their fit on
    # whichever option they liked best. Without this the Chair tends to thank
    # someone who scored the winner a 9, which reads as flattery and costs the
    # explanation its credibility.
    winner_id = ranked[0]["option_id"] if ranked else ""
    positions: dict[str, dict] = {}
    for report in reports:
        if not report.verdicts:
            continue
        best = max(report.verdicts, key=lambda v: v.fit)
        here = next((v for v in report.verdicts if v.option_id == winner_id), None)
        if here is None:
            continue
        positions[report.traveler] = {
            "traveler": report.traveler,
            "fit_on_winner": here.fit,
            "their_favourite_option": best.option_id,
            "their_best_fit": best.fit,
            "fit_gap": best.fit - here.fit,
            "one_wish_on_winner": here.one_wish,
            "loves_on_winner": here.loves_most,
        }

    return {
        "ranked": ranked,
        "winner": winner_id,
        "runner_up": ranked[1]["option_id"] if len(ranked) > 1 else "",
        # Ordered by who is flexing most; the Chair thanks these and only these.
        "flexing": sorted(
            (p for p in positions.values() if p["fit_gap"] >= 2),
            key=lambda p: -p["fit_gap"],
        ),
        "got_their_favourite": [
            p["traveler"] for p in positions.values() if p["fit_gap"] < 2
        ],
    }


# -------------------------------------------------------------- the run


async def plan(progress=None) -> dict:
    """Run one full planning session and return everything the UI needs."""
    import server
    import trip_data as td

    g = td.group()
    # The undefended baseline drops the prompt-layer guard along with the
    # calendar screening, so the two builds differ in exactly one decision.
    build_team(guarded=g.sanitize_calendars)
    run_id = uuid.uuid4().hex[:12]
    trace_log.start(run_id)
    cache: dict = {}

    def step(label: str) -> None:
        trace_log.record(run_id, "phase", "quorum", result=label)
        if progress:
            progress(label)

    if len(g.travelers) < 2:
        raise ValueError("Quorum needs at least two travelers to mediate between.")

    # 1 — the Scout builds a slate.
    step("Reading everyone's calendars and finding real options")
    shortlist = await _run(
        _scout,
        "Build the slate of options for this group. Use the tools to find the "
        "windows they are actually free and destinations that fit what they "
        f"said they want. The trip is {g.nights} nights. Horizon: "
        f"{g.horizon_start.isoformat()} to {g.horizon_end.isoformat()}.",
        Deps(run_id=run_id, actor="scout", tool_cache=cache),
        SCOUT_LIMITS,
    )

    # 2 — price it exactly, in Python.
    step("Pricing every option, to the dollar")
    priced, rejected = price_slate(shortlist, run_id)
    if not priced:
        raise ValueError(
            "None of the Scout's candidates could be priced: " + "; ".join(rejected)
        )
    slate = _slate_text(priced)

    # 3 — every traveler's advocate scores the slate, in parallel.
    step(f"{len(g.travelers)} advocates are weighing in")

    async def advocate_for(t) -> AdvocateReport:
        brief = (
            f"You represent {t.name}.\n"
            f"- Flies from: {t.home_airport}\n"
            f"- Budget ceiling: ${t.budget_usd}\n"
            f"- Likes: {', '.join(t.likes) or 'nothing stated'}\n"
            f"- Dislikes: {', '.join(t.dislikes) or 'nothing stated'}\n"
            f"- Preferred lodging tier: {t.lodging_tier}\n"
            f"- In their own words: {t.must_have}\n\n"
            f"Here is the priced slate. Score every option.\n\n{slate}"
        )
        return await _run(
            _advocate, brief,
            Deps(run_id=run_id, actor=f"advocate:{t.name}", traveler=t.name,
                 tool_cache=cache),
            ADVOCATE_LIMITS,
        )

    reports = await asyncio.gather(*(advocate_for(t) for t in g.travelers))

    # 4 — rank deterministically, then let the Chair explain the ranking.
    step("Finding the trip that works for everyone")
    ranking = tally(priced, list(reports))
    # Deliberately NOT handed to the Chair. It carries the quarantined text, so
    # passing it as "evidence" would walk the very payload the screen caught
    # straight into a model's context. The humans see it in the security panel;
    # no agent needs it to choose a trip.
    security = server.security_report()

    chair_brief = (
        f"{len(g.travelers)} travelers. The priced slate:\n\n{slate}\n\n"
        "Every advocate's scores, and the ranking by highest floor — the trip "
        "that works best for whoever it suits least (this arithmetic is already "
        "done; your job is the call and the explanation):\n\n"
        f"{json.dumps(ranking['ranked'], indent=2)}\n\n"
        "What each advocate said:\n"
        + "\n".join(f"- {r.traveler}: {r.bottom_line}" for r in reports)
        + "\n\n"
        f"The ranking makes option {ranking['winner']} the winner. Write about "
        "that trip only — the group sees the other options elsewhere, in their "
        "own section, and does not want the recommendation hedged against "
        "them.\n\n"
        "Who is flexing, measured as the gap between their fit on the winner "
        "and their fit on the option they liked best. List these people in "
        "`flexes` and nobody else:\n"
        f"{json.dumps(ranking['flexing'], indent=2)}\n\n"
        "These travelers got essentially their favourite and must NOT appear "
        f"in `flexes`: {', '.join(ranking['got_their_favourite']) or 'none'}.\n\n"
        "Make the call and explain it."
    )
    decision = await _run(
        _chair, chair_brief,
        Deps(run_id=run_id, actor="chair", tool_cache=cache),
        CHAIR_LIMITS,
    )

    step("Done")
    trace = trace_log.get(run_id)
    trace_log.save(run_id)

    return {
        "run_id": run_id,
        "model": MODEL_NAME,
        "options": priced,
        "rejected": rejected,
        "scout_reasoning": shortlist.reasoning,
        "advocates": [r.model_dump() for r in reports],
        "ranking": ranking,
        "decision": decision.model_dump(),
        "security": security,
        "trace": trace.as_dict() if trace else {},
    }
