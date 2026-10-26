# Quorum

**The trip your whole group will actually agree to.**

Five friends want to travel together. Their calendars barely overlap, their
budgets differ by a factor of three, and one of them wants a beach while
another wants a mountain. Quorum takes everyone's real calendar and real
ceiling, puts a slate of priced options on the table, gives every traveler an
agent that argues their corner, and picks the trip with the *highest floor* —
the one that works best for whoever it suits least — then shows exactly who
flexed, and by how much.

It is not a trip planner. It is a way for a group to make a decision it will
actually stick to.

---

## Run it

Requires Python 3.11 or newer. From this folder:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Supply the API credential:

```bash
cp .env.example .env     # then put your PORTKEY_API_KEY in it
```

Quorum looks for `.env` in **this folder first**, then in the folder **one
level above** it. Either location works.

Start it:

```bash
.venv/bin/python -m uvicorn main:app --port 8013 --app-dir backend
```

Open **http://localhost:8013** and click **Load the sample group**, then
**Run the negotiation**. A run takes about 10 seconds.

There is no frontend build step — no `npm install`, no bundler. The interface
is one HTML file, one stylesheet and one script, served by the same process.

---

## Using it with your own group

1. Each traveler exports their calendar as `.ics` — in Google Calendar,
   Settings → Import & export → Export; in Apple Calendar, File → Export.
2. Add each person in the app, set their home airport and their budget
   ceiling, and write what matters to them in their own words.
3. Upload each person's `.ics` against their name.
4. Set the trip length and the window you are planning inside, then run it.

Calendar files never leave your machine, and their contents are never sent to
the model — see **Safety** below.

---

## What is inside

| Path | What it is |
|---|---|
| `backend/agents.py` | the three agent roles and the run that orchestrates them |
| `backend/prompts/` | each agent's system prompt, as Markdown |
| `backend/trace_log.py` | per-run step trace and measured token accounting |
| `backend/main.py` | FastAPI routes, and the frontend |
| `mcp_server/server.py` | **trip-ops** — the ten tools the agents can call |
| `mcp_server/trip_data.py` | the snapshot, group state, and the injection screen |
| `mcp_server/calendars.py` | `.ics` parsing, written to distrust its input |
| `frontend/` | the interface: one HTML file, one CSS file, one JS file |
| `data/` | the destination, fare, lodging and seasonality snapshot |
| `tools/injection_eval.py` | the safety harness that measures the defenses |
| `vendor/` | reveal.js, inlined into `slides.html` so the deck needs no network |
| `output/` | traces, screenshots and the evidence behind the report |

### The agents

**Scout** (one run, with tools) builds a slate of three to five genuinely
different options. **Advocate** (one run per traveler, in parallel, no tools)
scores the whole slate from one person's point of view and returns a fit
score per option, where 10 means they love it. **Chair** (one run, with tools) makes the call and explains
who paid for it.

Pricing is deliberately **not** an agent. `price_trip` is exact arithmetic over
the snapshot, run in Python, so a language model cannot invent a number that no
tool returned. The fit ranking is computed in Python too; the Chair explains
the ranking rather than producing it, and its prompt says that where the two
disagree, the arithmetic wins.

### The model

Every agent runs on **gpt-6-luna** through Portkey. `reasoning_effort` is set to
`none` because the model rejects function tools on `/chat/completions`
otherwise. A personal OpenAI key named `OPENAI_API_KEY` is used instead if no
Portkey key is present.

---

## The data

Prices are a **snapshot in the repo, not live quotes.** `data/build_data.py`
generates four CSVs — destinations, seasonality, fares and lodging — from
hand-set base rates per destination spread across the year with seasonal
multipliers. The numbers are realistic in shape and magnitude; they are not
scraped from an airline.

This is a deliberate choice, not a shortcut: live fare APIs need credentials
this project is not permitted to use, and a snapshot makes every run in the
report reproducible by anyone who clones the repo.

To use real data, replace `data/fares.csv` and `data/lodging.csv` with an
export in the same columns. Nothing else changes.

**Sample versus full dataset.** The app ships with all 111 destinations loaded.
A six-destination test set — Cancún, Lisbon, Reykjavík, Denver, New Orleans and
Tokyo, chosen to span region, climate and price so every code path is still
exercised — is marked by the `in_sample` column in `data/destinations.csv`.

Switch to it, and back, while the app is running:

```bash
curl -X POST "localhost:8013/api/settings/dataset?sample_only=true"    # six
curl -X POST "localhost:8013/api/settings/dataset?sample_only=false"   # all 18
```

There is no control for this in the interface. Narrowing the catalogue is
useful to a reviewer, but to a group planning a trip it looks like a trip
setting and only makes the slate thinner. Run `python data/build_data.py` to
regenerate the snapshot itself.

For scale: the whole snapshot is four CSVs totalling about 360 KB — 111
destinations across 63 countries and 11 regions, 17,280 fares, 3,996 lodging
rates and 1,332 seasonality rows. Still small enough to read in a text editor,
which is why the full set is the default.

The twelve sample travelers and their calendars come from
`data/travelers.json` and `data/build_calendars.py`, and contain no real
personal data. "Try the sample group" fills however many places the user asked
for by drawing **at random** from those twelve, so the demo is different each
time. `POST /api/group/sample?count=N&seed=S` pins the draw, which is how
`tools/injection_eval.py` keeps its conditions comparable.

---

## Safety

**Uploaded calendars are untrusted input.** A `.ics` is a file written by
someone else, and its event titles are prose that would otherwise flow straight
into a model's context. Quorum's defense is structural rather than persuasive:

- **Calendar text never reaches an agent.** Availability travels as dates and
  names. `find_windows` reports *who* is blocked, never *why*. There is no tool
  that returns an event title while screening is on.
- **A screen flags what it quarantines.** Entries matching any of twelve named
  heuristics — instruction overrides, impersonated system messages, asserted
  group decisions, implausible length — are shown to the human in the interface
  with the matched text and the rule it tripped.
- **No agent does arithmetic on money,** so no agent can be talked into
  reporting a cost that the pricing tool did not produce.
- **No tool books, reserves, holds or pays for anything.** There is no write
  path to the outside world for an agent to be tricked into using.
- **Every agent run is capped** by request and tool-call limits, so a loop
  cannot quietly spend a group's money on tokens.

`tools/injection_eval.py` measures all of this. It plants a payload in one
traveler's calendar and runs the same job under four conditions, reporting
whether the payload *reached* an agent and whether it *worked*. Results are in
`output/evidence/injection_eval.json` and discussed in the report.

```bash
.venv/bin/python tools/injection_eval.py --trials 3
```

To see the defense from the inside, click **Load sample group with a poisoned
calendar** in the interface.

Screening is deliberately **not** a setting in the interface — it is not
something a group should be able to switch off by accident. The undefended
baseline the report compares against is driven through the API instead, which
is what `tools/injection_eval.py` does:

```bash
curl -X POST localhost:8013/api/group \
  -H 'Content-Type: application/json' \
  -d '{"travelers": [], "nights": 6, "horizon_start": "2027-01-01",
       "horizon_end": "2027-12-31", "sanitize_calendars": false}'
```

That turns off both the calendar screen and the prompt-level guard, which is
what the comparison measures.

---

## What it costs

Measured, not estimated — the counts come from the gateway and are shown in the
interface after every run, per agent, with cached input broken out.

A typical five-traveler run: **~33,800 input tokens** (about 12,400 of them
cached), **~2,800 output tokens**, 9 model requests, 5 tool calls, about 10
seconds, **$0.057**.

The price basis lives in one place, `PRICE_PER_MTOK` in
`backend/trace_log.py`, and is currently a placeholder — confirm it against the
gateway's published rates before quoting dollar figures.

---

## API

| Route | What it does |
|---|---|
| `GET /api/state` | model, credential status, and the current group |
| `POST /api/group` | replace the roster and planning settings |
| `POST /api/group/sample?attack=none\|overt\|subtle` | load the demo group |
| `POST /api/group/calendar` | attach an uploaded `.ics` to a traveler |
| `POST /api/settings/dataset?sample_only=` | switch sample / full data |
| `POST /api/plan` | start a run, returns a `job_id` |
| `GET /api/plan/{job_id}` | poll status, phase, and the result |
| `GET /api/trace/{run_id}` | every step of a run |
| `GET /api/tokenomics/{run_id}` | measured usage and cost projections |
| `GET /api/security` | what the calendar screen quarantined |

## Limits

Fares are a snapshot, so the dollar figures are realistic rather than bookable.
The destination set is 111 cities, not the world. Quorum assumes one shared
lodging booking split evenly, which is wrong for a group that wants separate
rooms. And it plans the decision, not the trip: there are no flights booked, no
itinerary, and no restaurant at the end of it.
