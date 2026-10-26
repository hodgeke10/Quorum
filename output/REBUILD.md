# Rebuilding the deliverables

The report and the deck are generated, never hand-edited. Everything in them —
token counts, costs, the injection table, the ledger rows — is read out of
`output/evidence/`, so the documents cannot drift from what was measured.

**Do this once, after the app's design and behaviour are final.** Rebuilding
after every tweak wastes a planning run each time and the screenshots go stale
again with the next change.

## The order

1. **Run the app** and leave it on a clean sample group:
   ```bash
   .venv/bin/python -m uvicorn main:app --port 8013 --app-dir backend
   ```
2. **Do one full run** in the browser at a 1120x840 viewport — home, load the
   sample group, continue, find the trip. Note the run id shown in the trace
   panel.
3. **Capture eleven screenshots** into `output/screenshots/`, named exactly:

   | file | what it shows |
   |---|---|
   | `00-home.jpg` | the home page |
   | `01-group.jpg` | step I, sample group loaded |
   | `02-calendars.jpg` | step II, all calendars attached |
   | `03-decision.jpg` | the pitch and "what each of you gets" |
   | `04-details.jpg` | who flexed and good to know |
   | `05-scorecard.jpg` | the scorecard, including both summary rows |
   | `06-alternatives.jpg` | the "if you would rather" cards |
   | `07-security-cost.jpg` | **expand the Show toggle first** |
   | `08-trace.jpg` | the trace with the run id visible |
   | `09-injection-quarantined.jpg` | the quarantine panel, poisoned calendar loaded |
   | `10-about.jpg` | the about page |

   Capture at a **1040x800** viewport. Wider than that and the pane clips the
   right edge of the frame.

4. **Copy that run's trace** over the evidence file, and refresh the derived
   numbers:
   ```bash
   cp output/traces/<run_id>.json output/evidence/traced_run.json
   ```
   Then regenerate `output/evidence/tokenomics.json` from it (the baseline half
   of that file, `baseline_before_survey_tool.json`, does not change).

5. **Re-run the safety harness** if any prompt or tool changed, since its table
   is quoted in both documents:
   ```bash
   .venv/bin/python tools/injection_eval.py --trials 3
   ```

6. **Rebuild**, in this order:
   ```bash
   .venv/bin/python tools/crop_shots.py     # slide-sized details
   .venv/bin/python tools/build_report.py   # report.html
   .venv/bin/python tools/build_slides.py   # slides.html
   ```

## If the destination catalogue changed

`data/build_data.py` is the catalogue. After editing it:

```bash
python data/build_data.py          # regenerate the four CSVs
```

Then re-run **both** measurements before rebuilding, because the catalogue
changes which trips get slated:

```bash
.venv/bin/python tools/window_scarcity.py
.venv/bin/python tools/injection_eval.py --trials 3
```

The safety harness is the one that matters here. It has twice caught a real
leak that "did the attack work?" would have missed — once the Chair's brief
carrying the quarantined text, once the `security_report` tool being callable
by agents. Read its `reached` column, not just the outcome columns, and if any
condition reports reach with screening **on**, something is handing the payload
to a model.

## Keep these in step with the app

The documents carry their own copy of the product's wording. When the app's
headline, tagline or vocabulary changes, update the builders too — they are
plain strings in `tools/build_report.py` and `tools/build_slides.py`:

- the report's `lede` and the deck's title-slide subtitle
- the agent-design section's description of the fit scale
- anything quoting the home page

## Checks before submitting

- `crop_shots.py` offsets are tuned to the capture size. If the layout moved,
  open `output/screenshots/slides/*.jpg` and retune the numbers in that file.
- Set the repository URL in `tools/build_report.py` — it currently says
  `REPO_URL_HERE` in two places.
- Confirm `PRICE_PER_MTOK` in `backend/trace_log.py` against the gateway's
  published rates. Token counts are measured; only the multiplier is assumed.
- Replace the red TODO box in the report's Impact section with the real user
  trial.
- Both HTML files must open by double-clicking, with every image embedded.
