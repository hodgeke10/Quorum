"""Build slides.html — reveal.js from a CDN, images embedded, 10 slides.

Numbers are read from output/evidence/ so the deck and the report cannot
disagree.

    python tools/build_slides.py
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import submission

PROJECT = Path(__file__).resolve().parent.parent
EVIDENCE = PROJECT / "output" / "evidence"
SHOTS = PROJECT / "output" / "screenshots"

tok = json.loads((EVIDENCE / "tokenomics.json").read_text())
inj = json.loads((EVIDENCE / "injection_eval.json").read_text())
run = json.loads((EVIDENCE / "traced_run.json").read_text())
scarcity = json.loads((EVIDENCE / "window_scarcity.json").read_text())
SCARCITY = {r["group_size"]: r for r in scarcity["by_group_size"]}
STARTS = scarcity["candidate_start_dates"]

BASE, OPT = tok["baseline_22_tool_calls"], tok["optimized_survey_tool"]


def decision_from(trace: dict) -> dict:
    """The Chair's output, recovered from the saved trace of the demo run."""
    for event in trace["events"]:
        if event["kind"] == "agent_done" and event["actor"] == "chair":
            out = event["result"]
            return json.loads(out) if isinstance(out, str) else out
    return {}


DECISION = decision_from(run)


def first_clause(text: str) -> str:
    """The Chair writes for the app, where there is room; a slide has none."""
    return text.split(";")[0].strip().rstrip(".")
COST = OPT["cost"]
PER_USER_MONTH = COST * 2
# reveal.js is vendored into the file rather than pulled from a CDN. The deck
# has to open by double-clicking on someone else's computer, and a CDN fails
# exactly there: offline, behind a blocker, or on a machine that will not load
# remote scripts into a file:// page. Inlining it removes the dependency.
VENDOR = PROJECT / "vendor"


def vendored(name: str) -> str:
    text = (VENDOR / name).read_text(encoding="utf-8")
    # the theme imports a web font we do not use; our own CSS sets the faces
    return "\n".join(l for l in text.splitlines() if "@import" not in l)


def img(name: str) -> str:
    """A cropped detail from output/screenshots/slides/, cut by crop_shots.py."""
    return "data:image/jpeg;base64," + base64.b64encode(
        (SHOTS / "slides" / name).read_bytes()).decode()


def logo() -> str:
    """The mark, inlined so the deck stays one self-contained file."""
    raw = (PROJECT / "frontend" / "logo.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode()


LOGO = logo()


CSS = """
:root{--parchment:#fbf9f4;--panel:#fff;--line:#e8e2d6;--ink:#1f2a38;
  --ink-2:#4e5a6b;--ink-3:#8b8578;--lapis:#1d4e89;--lapis-dk:#143862;
  --gold:#b8893b;--gold-lt:#f3ead6;--terracotta:#bf5a45;--olive:#6b8f5e;
  --serif:"Optima","Palatino Linotype",Palatino,"Iowan Old Style",Georgia,serif;
  --sans:ui-sans-serif,-apple-system,"Segoe UI",system-ui,sans-serif}
.reveal{font-family:var(--sans);font-size:30px;color:var(--ink)}
.reveal-viewport{background:
  radial-gradient(1100px 620px at 8% -10%,#f2eee2 0%,transparent 62%),
  radial-gradient(900px 520px at 102% -4%,#eef2f8 0%,transparent 58%),var(--parchment)}
.reveal h1,.reveal h2{color:var(--lapis-dk);font-family:var(--serif);
  font-weight:400;text-transform:none;letter-spacing:-.005em;margin-bottom:.3em}
.reveal h1{font-size:2.5em;line-height:1.1;letter-spacing:.1em;text-transform:uppercase}
.reveal h2{font-size:1.5em;line-height:1.24}
.reveal h3{font-family:var(--serif);font-weight:400;font-size:.6em;color:var(--gold);
  letter-spacing:.2em;text-transform:uppercase;margin-bottom:1.1em}
.reveal p{line-height:1.5}
.reveal section{text-align:left}
.reveal .sub{color:var(--ink-2);font-size:.78em;font-family:var(--serif);font-style:italic}
.reveal .tiny{font-size:.48em;color:var(--ink-3);line-height:1.55}
.reveal strong{color:var(--lapis-dk)}
.reveal em{color:var(--lapis);font-style:normal;font-weight:600}
.reveal ul{margin-left:.6em}
.reveal li{margin-bottom:.45em;line-height:1.4}
.reveal table{font-size:.5em;border-collapse:collapse;width:100%;margin-top:.6em}
.reveal th{color:var(--ink-3);font-weight:600;text-align:left;
  border-bottom:1px solid var(--line);padding:.45em .6em;font-size:.95em;
  text-transform:uppercase;letter-spacing:.08em}
.reveal td{border-bottom:1px solid #f0ece3;padding:.45em .6em}
.reveal td.n,.reveal th.n{text-align:right;font-family:ui-monospace,Menlo,monospace}
.reveal tr.hi td{color:var(--lapis-dk);font-weight:650;background:var(--gold-lt)}
.reveal .big{font-size:2.3em;font-family:var(--serif);font-weight:400;
  color:var(--lapis-dk);line-height:1}
.reveal .stat{margin-bottom:1.1em}
.reveal .stat .lbl{font-size:.52em;color:var(--ink-3);display:block;margin-top:.3em;line-height:1.4}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:1.4em;align-items:start}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:1.2em}
.shot{width:100%;max-height:9.4em;object-fit:contain;object-position:top;
  border:1px solid var(--line);border-radius:10px;display:block;background:#fff}
.ledger{display:grid;gap:.3em}
.ledger-row{display:grid;grid-template-columns:4.4em 1fr 15em;gap:.8em;
  align-items:baseline;background:var(--panel);border:1px solid var(--line);
  border-left:3px solid var(--gold);border-radius:8px;padding:.55em .8em;font-size:.5em}
.ledger-row b{color:var(--lapis-dk);font-size:1.12em}
.ledger-row span{color:var(--ink-2);line-height:1.4}
.ledger-row em{color:#8a5e1f;font-style:normal;font-family:ui-monospace,Menlo,monospace;
  font-size:.92em;line-height:1.4}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:.75em .95em;font-size:.57em;line-height:1.5;box-shadow:0 1px 2px rgba(31,42,56,.05)}
.card b{color:var(--lapis-dk)}
.good{color:var(--olive);font-weight:650}
.bad{color:var(--terracotta);font-weight:650}
.mark{display:block;width:2.6em;height:2.6em;margin-bottom:.6em}
.reveal .repo{font-size:.5em;color:var(--ink-2);margin-top:.8em;line-height:1.5}
.reveal .repo a{color:var(--lapis);text-decoration:underline;text-underline-offset:3px;word-break:break-all}
"""

SLIDES = f"""
<section>
  <img class="mark" src="{LOGO}" alt="" />
  <h1>Quorum</h1>
  <p class="sub" style="font-size:1.05em;margin-top:.1em">
    Busy calendars, strong opinions, one trip everyone loves.</p>
  <p class="tiny" style="margin-top:1.5em">
    Kelly Hodge &middot; MGT 409 &middot; three agents on gpt-6-luna via Portkey<br/>
    Not a trip planner — a way for a group to make a decision it will stick to.</p>
  <p class="repo">Code: <a href="{submission.REPO_URL}">{submission.REPO_URL}</a>
    &nbsp;·&nbsp; <span class="tiny">{submission.visibility_note_plain()}</span></p>
</section>

<section>
  <h3>The problem</h3>
  <h2>Five friends, five calendars,<br/>and a thread that goes quiet.</h2>
  <div class="grid2" style="margin-top:1em">
    <div>
      <p style="font-size:.78em">Availability, money and taste all conflict at
      once, and no one person can hold it in their head.</p>
      <p class="tiny">So the thread dies, or the loudest person decides and
      someone quietly resents it.</p>
    </div>
    <div>
      <div class="stat"><span class="big">{SCARCITY[5]["windows_mean"]:.0f}</span>
        <span class="lbl">weeks in a year work for five people, out of {STARTS}
        candidate start dates &mdash; for ten people it is
        {SCARCITY[10]["windows_mean"]:.0f}</span></div>
      <div class="stat"><span class="big">$1,150&ndash;$3,000</span>
        <span class="lbl">spread in what people can spend</span></div>
      <div class="stat"><span class="big">12</span>
        <span class="lbl">sample travelers with real-shaped calendars; a group is
        drawn at random from them</span></div>
    </div>
  </div>
</section>

<section>
  <h3>What is new</h3>
  <h2>Everyone else solves one slice.</h2>
  <table>
    <tr><th>Tool</th><th>Solves</th><th>Misses</th></tr>
    <tr><td>Doodle, When2meet</td><td>Availability</td>
        <td>Stops there — no money, no taste</td></tr>
    <tr><td>Google Flights, Hopper</td><td>Money, for one person</td>
        <td>One origin, one budget, one set of tastes</td></tr>
    <tr><td>Wanderlog, TripIt</td><td>The itinerary</td>
        <td>Starts after the decision is made</td></tr>
    <tr><td>Splitwise</td><td>Splitting the bill</td>
        <td>Too late — money's already spent</td></tr>
    <tr><td>ChatGPT / Gemini</td><td>A plausible plan</td>
        <td>Invents prices; nobody can audit it for fairness</td></tr>
    <tr class="hi"><td><b>Quorum</b></td><td>The <b>disagreement</b></td>
        <td>Every traveler gets an agent that argues their corner</td></tr>
  </table>
</section>

<section>
  <h3>The agents</h3>
  <h2>Three roles. Two things deliberately <em>not</em> agents.</h2>
  <div class="grid3" style="margin-top:.8em">
    <div class="card"><b>Scout</b> &mdash; 1 run, with tools.<br/>
      Builds a slate of 3&ndash;5 genuinely different priced options.</div>
    <div class="card"><b>Advocate &times; N</b> &mdash; 1 run per traveler,
      parallel, no tools.<br/>Scores how well every option fits one person,
      0&ndash;10.</div>
    <div class="card"><b>Chair</b> &mdash; 1 run, with tools.<br/>
      Makes the call and writes who flexed for the group, and by how much.</div>
  </div>
  <div class="grid2" style="margin-top:1.1em">
    <div class="card" style="border-color:#5a4a28"><b>Pricing is Python.</b>
      A model can't invent a number it never had to add up.</div>
    <div class="card" style="border-color:#5a4a28"><b>The ranking is Python.</b>
      The fairness rule is computed, not generated. The Chair explains it.</div>
  </div>
  <p class="tiny" style="margin-top:.9em">All three on gpt-6-luna,
  <code>reasoning_effort=none</code> (required for tool calls). Tools reach the
  data through one MCP server: <b>trip-ops</b>, 10 tools.</p>
</section>

<section>
  <h3>The idea, in one picture</h3>
  <img class="shot" src="{img('scorecard.jpg')}" alt="Everyone's scorecard" />
  <p class="tiny" style="margin-top:.6em">Rows are people, columns are trips,
  cells are fit (10 = my dream trip, 0 = not for me). We pick the column with the
  <b>highest floor</b> — <em>not</em> the best average. New Orleans is $55
  cheaper with a better average; its floor is a 4, so Austin wins.</p>
</section>

<section>
  <h3>The output</h3>
  <h2 style="font-size:1.12em;max-width:27ch;margin-bottom:.45em">{DECISION.get("headline", "")}</h2>
  <p style="font-size:.56em;color:var(--ink-2);margin-bottom:.8em">
    Not just a destination — a <b>ledger of who flexed</b>, measured as the gap
    between how well this trip fits each person and how well their own favourite
    would have.</p>
  <div class="ledger">
    {"".join(
        f'<div class="ledger-row"><b>{c["traveler"]}</b>'
        f'<span>{first_clause(c["flexed_on"])}</span>'
        f'<em>{first_clause(c["the_numbers"])}</em></div>'
        for c in DECISION.get("flexes", [])[:4])}
  </div>
  <p class="tiny" style="margin-top:.7em">Groups accept a decision when they can
  see the receipts — and anyone can argue with a number.</p>
</section>

<section>
  <h3>Tokenomics</h3>
  <h2>${COST:.3f} to decide a trip for five.</h2>
  <div class="grid2" style="margin-top:.5em">
    <div>
      <table>
        <tr><th></th><th class="n">Before</th><th class="n">After</th></tr>
        <tr><td>Tool calls</td><td class="n">{BASE['tool_calls']}</td>
            <td class="n good">{OPT['tool_calls']}</td></tr>
        <tr><td>Input tokens</td><td class="n">{BASE['input']:,}</td>
            <td class="n good">{OPT['input']:,}</td></tr>
        <tr><td>Output tokens</td><td class="n">{BASE['output']:,}</td>
            <td class="n good">{OPT['output']:,}</td></tr>
        <tr><td>Seconds</td><td class="n">{BASE['elapsed']}</td>
            <td class="n good">{OPT['elapsed']}</td></tr>
        <tr class="hi"><td><b>Cost / run</b></td>
            <td class="n">${BASE['cost']:.4f}</td>
            <td class="n">${COST:.4f}</td></tr>
      </table>
      <p class="tiny">One batched <code>survey</code> tool replaced 19 one-at-a-time
      lookups. Every tool result is re-sent on every later request, so tool calls
      bill quadratically.</p>
    </div>
    <div>
      <div class="stat"><span class="big">${PER_USER_MONTH * 10_000:,.0f}</span>
        <span class="lbl">per month at 10,000 users (2 runs each)</span></div>
      <div class="stat"><span class="big">{COST / 5 * 100:.1f}&cent;</span>
        <span class="lbl">per person per trip decided</span></div>
      <p class="tiny"><b>The tradeoff:</b> slates got slightly less exotic — the
      survey's cheapest-first ordering buries the expensive-but-perfect option.
      The floor didn't drop.</p>
      <p class="tiny">All five advocates together are only
      {sum(tok['per_agent_optimized'][k]['input_tokens'] + tok['per_agent_optimized'][k]['output_tokens'] for k in tok['per_agent_optimized'] if k.startswith('advocate'))
        / (OPT['input'] + OPT['output']) * 100:.0f}% of tokens — <em>the
      per-person part is the cheap part.</em></p>
    </div>
  </div>
</section>

<section>
  <h3>Safety</h3>
  <h2>A calendar is a file someone else wrote.</h2>
  <div class="grid2">
    <div>
      <img class="shot" src="{img('quarantine.jpg')}" alt="Quarantined entries" />
    </div>
    <div>
      <p style="font-size:.66em"><b>The defense is structural.</b> Event text
      never reaches an agent — availability travels as dates and names only.
      There is no tool that returns a calendar title, so there is no channel.</p>
      <table>
        <tr><th>Condition</th><th class="n">Payload reached<br/>an agent</th>
            <th>Trip chosen</th></tr>
        <tr><td>Screening on, overt</td><td class="n good">0/3</td><td>Austin</td></tr>
        <tr><td>Screening off, overt</td><td class="n bad">3/3</td><td>Charleston</td></tr>
        <tr><td>Screening on, subtle</td><td class="n good">0/3</td><td>Austin</td></tr>
        <tr><td>Screening off, subtle</td><td class="n bad">3/3</td><td>Austin</td></tr>
      </table>
      <p class="tiny"><b>Measuring reach, not just effect, found two real holes:</b>
      the orchestration once passed the payload to the Chair in a prompt, and the
      quarantine log was exposed as a tool the Scout could call. Both read clean
      on "did the attack work?" In an earlier build the subtle payload <em>did</em>
      steer the slate 3/3 — whether it works shifts with the model and the
      catalogue. Reach is the only property that holds by construction.</p>
    </div>
  </div>
</section>

<section>
  <h3>Impact</h3>
  <h2>What it replaces.</h2>
  <div class="grid3" style="margin-top:1em">
    <div class="stat"><span class="big">{run['elapsed_s']}s</span>
      <span class="lbl">five calendars to a priced, explained, ranked
      decision</span></div>
    <div class="stat"><span class="big">{SCARCITY[5]["windows_mean"] / STARTS * 100:.0f}%</span>
      <span class="lbl">of candidate start dates actually work for five people —
      the number no group computes by hand</span></div>
    <div class="stat"><span class="big">3 of 5</span>
      <span class="lbl">travelers named in the ledger, with dollars and
      fit points</span></div>
  </div>
</section>

<section>
  <h3>Limits &amp; next</h3>
  <h2>What I'd do next.</h2>
  <div class="grid2">
    <div>
      <p style="font-size:.6em;color:var(--dim)"><b>Limits</b></p>
      <ul style="font-size:.6em">
        <li>Fares are a snapshot, not live quotes</li>
        <li>111 destinations, not the world</li>
        <li>One shared booking, split evenly</li>
        <li>It decides a trip; it doesn't plan one</li>
      </ul>
    </div>
    <div>
      <p style="font-size:.6em;color:var(--dim)"><b>Next</b></p>
      <ul style="font-size:.6em">
        <li><em>Run it with a real group</em> — everything else is speculation
          until the ledger is put in front of the person it says paid most</li>
        <li>Let people challenge their own score and re-run — turn a
          recommendation into a negotiation</li>
        <li>Real fare data: the schema is already right</li>
        <li>Re-run when calendars change, and say what moved</li>
      </ul>
    </div>
  </div>
  <p class="repo" style="margin-top:1em">Clone it:
    <a href="{submission.REPO_URL}">{submission.REPO_URL}</a>
    &nbsp;·&nbsp; <span class="tiny">{submission.visibility_note_plain()}</span></p>
</section>
"""

HTML = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Quorum — MGT 409 final project</title>
<style>{vendored("reveal.css")}</style>
<style>{vendored("white.css")}</style>
<style>{CSS}</style></head>
<body><div class="reveal"><div class="slides">{SLIDES}</div></div>
<script>{vendored("reveal.js")}</script>
<script>
  // `hash: true` makes reveal write the slide number into the URL via
  // history.replaceState. That throws a SecurityError anywhere the deck is
  // shown inside a sandboxed frame — Canvas's file preview, an LMS viewer,
  // the preview pane in a chat app — because the frame's document is
  // about:srcdoc and cannot take a history entry. Deep links to a slide are
  // worth less than the deck surviving however somebody opens it.
  Reveal.initialize({{ hash: false, slideNumber: 'c/t', width: 1280, height: 760,
                       margin: 0.06, transition: 'fade' }});
</script>
</body></html>
"""

if __name__ == "__main__":
    submission.warn_if_placeholder("slides.html")
    out = PROJECT / "slides.html"
    out.write_text(HTML, encoding="utf-8")
    print(f"wrote {out.relative_to(PROJECT)}  ({out.stat().st_size / 1024:.0f} KB, "
          f"{SLIDES.count('<section>')} slides)")
