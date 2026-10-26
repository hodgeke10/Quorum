/* Quorum front end. No framework, no build step — the whole app is this file,
   one stylesheet and the HTML shell. */

const $ = (id) => document.getElementById(id);
const api = async (path, opts) => {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `${res.status} ${res.statusText}`);
  return body;
};

let group = { travelers: [] };
let lastResult = null;
// A run costs real money, so arriving at the trip page only starts one when
// there is nothing to show or the inputs have moved since last time.
let resultStale = true;
let planning = false;

/* ─────────────────────────────── the roster ─────────────────────────────── */

const AIRPORTS = ["BDL","JFK","EWR","LGA","BOS","ORD","ATL","DFW","DEN","LAX","SFO","SEA","MIA"];
const TAGS = ["beach","city","food","nightlife","culture","outdoors","nature","budget","mountains","skiing","winter","art","photography","upscale"];

function travelerCard(t, i) {
  const el = document.createElement("div");
  el.className = "tcard";
  const blocks = t.busy_blocks || [];
  const flagged = blocks.filter((b) => b.flags && b.flags.length).length;

  el.innerHTML = `
    <button class="remove" title="Remove">×</button>
    <input class="name" value="${esc(t.name)}" placeholder="Name" />
    <div class="row">
      <div style="flex:1">
        <label>Flies from</label>
        <select class="airport">${AIRPORTS.map((a) =>
          `<option ${a === t.home_airport ? "selected" : ""}>${a}</option>`).join("")}</select>
      </div>
      <div style="flex:1">
        <label>Ceiling</label>
        <input class="budget" type="number" min="100" step="50" value="${t.budget_usd}" />
      </div>
    </div>
    <label>Likes</label>
    <input class="likes" value="${esc((t.likes || []).join(", "))}" placeholder="beach, food" list="taglist" />
    <label>Dislikes</label>
    <input class="dislikes" value="${esc((t.dislikes || []).join(", "))}" placeholder="nightlife" list="taglist" />
    <label>In their words</label>
    <textarea class="musthave" placeholder="What matters to them?">${esc(t.must_have || "")}</textarea>
    <div class="cal">
      <span class="${blocks.length ? (flagged ? "quarantined" : "loaded") : ""}">
        ${blocks.length
          ? `${calendarSummary(blocks)}${flagged ? ` · ${flagged} quarantined` : ""}`
          : "calendar comes next"}
      </span>
    </div>`;

  el.querySelector(".remove").onclick = () => { group.travelers.splice(i, 1); renderRoster(); pushGroup(); };
  el.querySelectorAll("input, select, textarea").forEach((f) => {
    if (f.type === "file") return;
    f.onchange = () => { readCard(el, t); pushGroup(); };
  });
  return el;
}

function readCard(el, t) {
  seedNote = "";
  fromSample = false;   // they have made it theirs
  t.name = el.querySelector(".name").value.trim();
  t.home_airport = el.querySelector(".airport").value;
  t.budget_usd = parseInt(el.querySelector(".budget").value, 10) || 1000;
  t.likes = splitList(el.querySelector(".likes").value);
  t.dislikes = splitList(el.querySelector(".dislikes").value);
  t.must_have = el.querySelector(".musthave").value.trim();
}

const splitList = (s) => s.split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);

function calendarSummary(blocks) {
  if (!blocks || !blocks.length) return "";
  return `${blocks.length} commitments`;
}

/* ──────────────────────────────── dates ────────────────────────────────── */

const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"];
const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                      "Aug", "Sep", "Oct", "Nov", "Dec"];

// Parsed by hand rather than with Date(), which reads a bare YYYY-MM-DD as UTC
// and can shift the day by one depending on the reader's timezone.
function fmtDate(iso, withYear = true) {
  const [y, m, d] = String(iso).split("-").map(Number);
  if (!y || !m || !d) return String(iso);
  return `${MONTHS[m - 1]} ${d}${withYear ? `, ${y}` : ""}`;
}

// `short` abbreviates the month, for places like a table header where a range
// crossing into a new month would otherwise wrap onto two lines.
function fmtRange(fromIso, toIso, withYear = true, short = false) {
  const names = short ? MONTHS_SHORT : MONTHS;
  const [ay, am, ad] = String(fromIso).split("-").map(Number);
  const [by, bm, bd] = String(toIso).split("-").map(Number);
  if (!ay || !by) return `${fmtDate(fromIso)} – ${fmtDate(toIso)}`;
  const year = withYear ? `, ${ay}` : "";
  if (ay === by && am === bm) return `${names[am - 1]} ${ad}–${bd}${year}`;
  if (ay === by) return `${names[am - 1]} ${ad} – ${names[bm - 1]} ${bd}${year}`;
  return `${fmtDate(fromIso)} – ${fmtDate(toIso)}`;
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function renderRoster() {
  const host = $("travelers");
  host.innerHTML = "";
  if (!group.travelers.length) {
    host.innerHTML = `<p class="empty">No travelers yet. Load the sample group, or add people and upload their calendar exports.</p>`;
  } else {
    group.travelers.forEach((t, i) => host.appendChild(travelerCard(t, i)));
  }
  if (!document.getElementById("taglist")) {
    const dl = document.createElement("datalist");
    dl.id = "taglist";
    dl.innerHTML = TAGS.map((t) => `<option value="${t}">`).join("");
    document.body.appendChild(dl);
  }
  syncGate();
}

/* ───────────────────────────── the calendars ───────────────────────────── */

async function uploadCalendar(traveler, file) {
  fromSample = false;
  const fd = new FormData();
  fd.append("traveler_id", traveler.id || "");
  fd.append("name", traveler.name);
  fd.append("file", file);
  try {
    applyState(await api("/api/group/calendar", { method: "POST", body: fd }));
  } catch (err) {
    showError(err.message);
  }
}

function renderCalList() {
  const host = $("callist");
  if (!host) return;
  if (!group.travelers.length) {
    host.innerHTML = `<p class="empty">Add travelers on the previous step first.</p>`;
    return;
  }
  host.innerHTML = "";
  group.travelers.forEach((t) => {
    const blocks = t.busy_blocks || [];
    const flagged = blocks.filter((b) => b.flags && b.flags.length).length;
    const row = document.createElement("div");
    row.className = "calrow" + (blocks.length ? " done" : "");
    row.innerHTML = `
      <span class="calrow-who">${esc(t.name)}</span>
      <span class="calrow-state ${blocks.length ? (flagged ? "quarantined" : "loaded") : ""}">
        ${blocks.length
          ? `${calendarSummary(blocks)}${flagged ? ` · ${flagged} quarantined` : ""}`
          : "no calendar yet — treated as free all window"}
      </span>
      <label class="btn ghost small calrow-btn">
        ${blocks.length ? "Replace" : "Attach .ics"}
        <input type="file" accept=".ics,text/calendar" hidden />
      </label>`;
    row.querySelector("input[type=file]").onchange = (ev) => {
      const file = ev.target.files[0];
      if (file) uploadCalendar(t, file);
    };
    host.appendChild(row);
  });
}

async function pushGroup() {
  const payload = {
    travelers: group.travelers.map((t) => ({
      // The id is what links a traveler to the calendar they uploaded. Without
      // it the server falls back to matching on name, and renaming somebody
      // loses their calendar.
      id: t.id || "",
      name: t.name, home_airport: t.home_airport, budget_usd: t.budget_usd,
      likes: t.likes || [], dislikes: t.dislikes || [],
      must_have: t.must_have || "", lodging_tier: t.lodging_tier || "mid",
    })),
    nights: parseInt($("nights").value, 10) || 6,
    horizon_start: $("horizon-start").value,
    horizon_end: $("horizon-end").value,
    // Screening is not a user setting. The value is carried through from the
    // server so a roster edit cannot silently turn it off; only the safety
    // harness changes it, via the API.
    sanitize_calendars: group.sanitize_calendars !== false,
  };
  try { applyState(await api("/api/group", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload) })); }
  catch (err) { showError(err.message); }
}

function applyState(state) {
  // Any change to the roster, the calendars or the settings invalidates a
  // result that is already on screen.
  resultStale = true;
  group = state;
  // Survives a page reload, unlike a variable in here.
  fromSample = !!state.from_sample;
  $("nights").value = state.nights;
  $("horizon-start").value = state.horizon_start;
  $("horizon-end").value = state.horizon_end;
  const shield = $("shield");
  shield.textContent = state.sanitize_calendars ? "Defenses on" : "Defenses OFF";
  shield.className = "shield " + (state.sanitize_calendars ? "on" : "off");
  renderRoster();
  renderCalList();
  renderFlagged(state.flagged || []);
}

// The server sends a quarantined entry's span as "YYYY-MM-DD to YYYY-MM-DD".
function prettyDates(span) {
  const [from, to] = String(span).split(" to ");
  return to ? fmtRange(from, to) : fmtDate(from);
}

function renderFlagged(flagged) {
  const host = $("flagged");
  // The explanation lives on the About page; this only appears in the planning
  // flow when something was actually caught, because a real group uploading a
  // poisoned calendar has to find out where they are, not in a help page.
  $("screening-alert").hidden = !flagged.length;
  if (!flagged.length) { host.innerHTML = ""; return; }
  host.innerHTML = flagged.map((f) => `
    <div class="flag">
      <h4>Quarantined calendar entry — ${esc(f.traveler)}</h4>
      <div class="meta">${esc(prettyDates(f.dates))} · this text was withheld from every agent</div>
      <pre>${esc(f.title)}</pre>
      <div class="tripped">Tripped: ${f.tripped.map((t) => `<code>${esc(t)}</code>`).join(" · ")}</div>
    </div>`).join("");
}

/* ──────────────────────────────── the run ───────────────────────────────── */

const PHASES = 5;
let phaseCount = 0;

// Called whenever the trip page is opened.
function maybePlan() {
  if (planning || !canPlan()) return;
  if (!resultStale && lastResult) return;
  runPlan();
}

async function runPlan() {
  planning = true;
  $("error").hidden = true;
  $("results").hidden = true;
  $("progress").hidden = false;
  phaseCount = 0;
  $("bar-fill").style.width = "4%";
  $("phase").textContent = "Starting";
  $("btn-plan").disabled = true;

  try {
    const { job_id } = await api("/api/plan", { method: "POST" });
    let seen = "";
    for (;;) {
      await new Promise((r) => setTimeout(r, 1200));
      const run = await api(`/api/plan/${job_id}`);
      if (run.phase !== seen) {
        seen = run.phase;
        phaseCount = Math.min(phaseCount + 1, PHASES);
        $("phase").textContent = run.phase;
        $("bar-fill").style.width = `${(phaseCount / PHASES) * 100}%`;
      }
      if (run.status === "done") { render(run.result); break; }
      if (run.status === "error") { throw new Error(run.error); }
    }
  } catch (err) {
    showError(err.message);
  } finally {
    planning = false;
    $("progress").hidden = true;
    $("btn-plan").disabled = !canPlan();
    $("btn-plan").textContent = lastResult ? "Run it again" : "Find our trip";
  }
}

function showError(msg) {
  $("error").hidden = false;
  $("error").textContent = msg;
}

/* ──────────────────────────────── results ───────────────────────────────── */

// Fit runs upward, so the ramp does too: 10 is the warmest green, 0 the
// softest terracotta. Every cell also prints its number, so the matrix never
// depends on telling the colours apart.
function fitColor(n) {
  const stops = [[0,"--f0"],[2,"--f2"],[4,"--f4"],[6,"--f6"],[8,"--f8"],[10,"--f10"]];
  let pick = stops[0];
  for (const s of stops) if (n >= s[0]) pick = s;
  return getComputedStyle(document.documentElement).getPropertyValue(pick[1]).trim();
}

function render(result) {
  lastResult = result;
  resultStale = false;
  $("results").hidden = false;

  const d = result.decision;
  const winner = result.options.find((o) => o.option_id === d.winner_option_id) || result.options[0];

  $("d-headline").textContent = d.headline;
  $("d-why").textContent = d.why_this_one;
  // Every advocate already said what their person likes most about every
  // option. For the winner that is a ready-made pitch, one line per traveler,
  // and it costs nothing extra to show.
  $("d-loves").innerHTML = result.advocates.map((a) => {
    const v = a.verdicts.find((x) => x.option_id === d.winner_option_id);
    if (!v || !v.loves_most) return "";
    return `<li><span class="who">${esc(a.traveler)}</span> — ${esc(v.loves_most)}</li>`;
  }).join("") || `<li>Everyone is happy with this one.</li>`;

  $("d-flexes").innerHTML = (d.flexes || []).length
    ? d.flexes.map((c) => `<li><span class="who">${esc(c.traveler)}</span> — ${esc(c.flexed_on)}
        <span class="cost">${esc(c.the_numbers)}</span></li>`).join("")
    : `<li>Nobody had to flex — this one was everyone's favourite.</li>`;
  $("d-goodtoknow").innerHTML = (d.good_to_know || []).map((w) => `<li>${esc(w)}</li>`).join("")
    || `<li>Nothing to flag — you're good to go.</li>`;

  renderMatrix(result);
  renderOptions(result, winner);

  $("run-id").textContent = `run ${result.run_id}`;
  $("details").hidden = true;
  $("btn-details").textContent = "Show";
  renderSecurity(result.security);
  renderTokenomics(result);
  renderTrace(result.trace);

  $("panel-decision").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderMatrix(result) {
  const opts = result.options;
  const ranked = Object.fromEntries(result.ranking.ranked.map((r) => [r.option_id, r]));
  const win = result.ranking.winner;

  let head = `<tr><th></th>` + opts.map((o) =>
    `<th class="opt ${o.option_id === win ? "win" : ""}">
       <span class="city">${esc(o.city)}</span>
       <span class="when">${fmtRange(o.start, o.end, false, true)}</span></th>`).join("") + `</tr>`;

  const rows = result.advocates.map((a) => {
    const cells = opts.map((o) => {
      const v = a.verdicts.find((x) => x.option_id === o.option_id);
      const n = v ? v.fit : 0;
      const tip = v ? `${v.loves_most} — wish: ${v.one_wish}` : "no verdict";
      return `<td><div class="cell" style="background:${fitColor(n)}" title="${esc(tip)}">
        ${n}</div></td>`;
    }).join("");
    return `<tr><td class="rowname">${esc(a.traveler)}</td>${cells}</tr>`;
  }).join("");

  const worst = `<tr class="summary"><td class="rowname">Works for everyone<small>decides it</small></td>` +
    opts.map((o) => {
      const r = ranked[o.option_id] || {};
      return `<td><div class="cell ${o.option_id === win ? "win" : ""}">
        ${r.floor ?? "—"}+ · ${esc(r.floor_traveler || "—")}</div></td>`;
    }).join("") + `</tr>`;

  const cost = `<tr class="summary"><td class="rowname">Group cost</td>` +
    opts.map((o) => `<td><div class="cell ${o.option_id === win ? "win" : ""}">$${o.group_total_usd.toLocaleString()}</div></td>`).join("") + `</tr>`;

  $("matrix").innerHTML = head + rows + worst + cost;
}

function renderOptions(result, winner) {
  const ranked = Object.fromEntries(result.ranking.ranked.map((r) => [r.option_id, r]));
  const winId = result.ranking.winner;
  const winTotal = winner ? winner.group_total_usd : 0;
  const winFloor = ranked[winId] ? ranked[winId].floor : null;

  // The chosen trip is the whole page above this; repeating its card here adds
  // nothing. What a group actually wants at this point is the alternatives and
  // what picking one would cost them.
  const alts = result.ranking.ranked
    .filter((r) => r.option_id !== winId)
    .map((r) => result.options.find((o) => o.option_id === r.option_id))
    .filter(Boolean);

  $("alt-blurb").textContent = alts.length
    ? `${winner ? winner.city : "The chosen trip"} came out ahead of these. Here is what swapping to one would mean.`
    : "This was the only option that priced out for everyone.";

  $("options").innerHTML = alts.map((o) => {
    const r = ranked[o.option_id] || {};
    const diff = o.group_total_usd - winTotal;
    const money = diff === 0
      ? "same group cost"
      : `${diff > 0 ? "+" : "\u2212"}$${Math.abs(diff).toLocaleString()} for the group`;
    const floorGap = (winFloor !== null && r.floor !== undefined)
      ? (r.floor < winFloor
          ? `leaves ${esc(r.floor_traveler)} at ${r.floor} instead of ${winFloor}`
          : r.floor === winFloor
            ? `matches on the floor, at ${r.floor}`
            : `floor of ${r.floor}`)
      : "";

    const rows = o.per_person.map((p) => `
      <tr>
        <td>${esc(p.name)}${p.free_these_dates ? "" : ` <span class="away">busy</span>`}</td>
        <td>${p.lives_there ? `<span class="home">home</span>` : `$${p.flight_usd}`}</td>
        <td>$${p.lodging_share_usd}</td>
        <td class="${p.within_budget ? "" : "over"}">$${p.total_usd}${
          p.within_budget ? "" : ` (+${p.over_budget_usd})`}</td>
      </tr>`).join("");

    return `
      <div class="ocard">
        <span class="oid">OPTION ${o.option_id}</span>
        <h3>${esc(o.city)}</h3>
        <div class="when">${fmtRange(o.start, o.end)} · ${o.nights} nights · ${o.tier}</div>
        <p class="tradeoff"><strong>${money}</strong>${floorGap ? ` · ${floorGap}` : ""}</p>
        <p class="why">${esc(o.why)}</p>
        <table>
          <tr><th>Traveler</th><th>Flight</th><th>Bed</th><th>Total</th></tr>
          ${rows}
        </table>
        <div class="total"><span class="l">Group total</span><span class="n">$${o.group_total_usd.toLocaleString()}</span></div>
      </div>`;
  }).join("");
}

function renderSecurity(sec) {
  const host = $("security");
  if (!sec.quarantined_count) {
    host.innerHTML = `<div class="kv">
      <span class="k">Screening</span><span class="v ${sec.sanitizing_enabled ? "good" : ""}">${sec.sanitizing_enabled ? "on" : "OFF"}</span>
      <span class="k">Injection attempts</span><span class="v">none</span>
      <span class="k">Calendar text sent to agents</span><span class="v good">${sec.sanitizing_enabled ? "none" : "ALL OF IT"}</span>
    </div>
    <p class="note">Availability reached the agents as dates and names only. No tool in this
    app can book, reserve, or pay for anything.</p>`;
    return;
  }
  host.innerHTML = `<div class="kv">
      <span class="k">Screening</span><span class="v ${sec.sanitizing_enabled ? "good" : ""}">${sec.sanitizing_enabled ? "on" : "OFF"}</span>
      <span class="k">Entries quarantined</span><span class="v" style="color:var(--danger)">${sec.quarantined_count}</span>
    </div>` + sec.entries.map((e) => `
      <div class="flag">
        <h4>Blocked — ${esc(e.traveler)}</h4>
        <div class="meta">${esc(prettyDates(e.dates))}</div>
        <pre>${esc(e.quarantined_text)}</pre>
        <div class="tripped">${e.heuristics_tripped.map((t) => `<code>${esc(t)}</code>`).join(" · ")}</div>
      </div>`).join("") +
    `<p class="note">${sec.sanitizing_enabled
      ? "This text was never sent to any agent. The decision above was made without it."
      : "Screening was disabled for this run, so this text WAS sent to the agents. Compare the decision against a screened run."}</p>`;
}

async function renderTokenomics(result) {
  const t = await api(`/api/tokenomics/${result.run_id}`).catch(() => null);
  if (!t) return;
  const u = t.usage;
  $("tokenomics").innerHTML = `
    <div class="kv">
      <span class="k">Input tokens</span><span class="v">${u.input_tokens.toLocaleString()}</span>
      <span class="k">— of which cached</span><span class="v good">${u.cached_input_tokens.toLocaleString()}</span>
      <span class="k">Output tokens</span><span class="v">${u.output_tokens.toLocaleString()}</span>
      <span class="k">Model requests</span><span class="v">${u.requests}</span>
      <span class="k">Tool calls</span><span class="v">${t.tool_calls} <span class="good">(${t.cache_hits} served from cache)</span></span>
      <div class="sep"></div>
      <span class="k">Cost of this run</span><span class="v big">$${u.cost_usd.toFixed(4)}</span>
      <span class="k">Per user / month (${t.runs_per_user_per_month} runs)</span><span class="v">$${t.cost_per_user_per_month_usd.toFixed(4)}</span>
      <span class="k">100 users / month</span><span class="v">$${t.monthly_at_100_users_usd.toFixed(2)}</span>
      <span class="k">10,000 users / month</span><span class="v">$${t.monthly_at_10000_users_usd.toLocaleString(undefined,{minimumFractionDigits:2})}</span>
    </div>
    <p class="note">Measured, not estimated — these are the counts the gateway reported for this
    run. Price basis: $${t.price_per_mtok.input}/M input, $${t.price_per_mtok.cached_input}/M cached,
    $${t.price_per_mtok.output}/M output (${esc(t.price_source)}).</p>`;
}

function renderTrace(trace) {
  if (!trace || !trace.events) return;
  // The run id is on screen so a screenshot can be matched to the saved trace
  // in output/traces/, and so anyone reporting a bad plan can quote it.
  const head = `<div class="ev phase"><span class="t"></span><span class="a">run</span>
    <span class="d">${esc(trace.run_id)} · ${trace.elapsed_s}s · ${trace.events.length} steps</span></div>`;
  $("trace").innerHTML = head + trace.events.map((e) => {
    const detail = e.kind === "phase" ? e.result
      : e.kind === "tool_call" ? `${e.target}(${JSON.stringify(e.detail)})${e.cached ? " — cached" : ""}`
      : e.kind === "usage" ? `${e.detail.input_tokens} in / ${e.detail.output_tokens} out`
      : e.kind === "agent_done" ? "returned its answer"
      : typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail || e.result || "");
    return `<div class="ev ${e.cached ? "cached" : ""} ${e.kind === "phase" ? "phase" : ""}">
      <span class="t">${e.at}s</span><span class="a">${esc(e.actor)}</span>
      <span class="d">${esc(String(detail).slice(0, 400))}</span></div>`;
  }).join("");
}

/* ───────────────────────────────── paging ──────────────────────────────── */

// Two pages: the roster, then screening + the run + results. The second is
// locked until there is a group worth planning for, so the run button can
// never be reached in a state that would only produce an error.
let page = 0;   // 0 = the front door, 1 = the roster, 2 = screening + the run

const withCalendars = () =>
  group.travelers.filter((t) => (t.busy_blocks || []).length).length;

// Two gates: you need a group before calendars mean anything, and you need
// calendars before a plan means anything.
const canDoCalendars = () => group.travelers.length >= 2;
const canPlan = () => canDoCalendars() && withCalendars() >= 2;

const PAGES = [0, 1, 2, 3, 4];   // 0 home · 1 group · 2 calendars · 3 trip · 4 about
const STEPS = [1, 2, 3];

function showPage(n) {
  page = n;
  for (const i of PAGES) {
    $(`page-${i}`).classList.toggle("active", i === n);
  }
  for (const i of STEPS) $(`step-${i}`).classList.toggle("on", i === n);
  // The step rail belongs to the planning flow; the front door and the about
  // page are not steps in it.
  $("steps").hidden = n === 0 || n === 4;
  if (n === 3) maybePlan();
  $("nav-about").classList.toggle("on", n === 4);
  $("nav-home").classList.toggle("on", n !== 4);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function syncGate() {
  const haveGroup = canDoCalendars();
  const ready = canPlan();
  const withCal = withCalendars();
  const missing = group.travelers
    .filter((t) => !(t.busy_blocks || []).length)
    .map((t) => t.name);

  $("to-page-2").disabled = !haveGroup;
  $("step-2").disabled = !haveGroup;
  $("to-page-3").disabled = !ready;
  $("step-3").disabled = !ready;
  $("btn-plan").disabled = !ready;

  $("hint-1").textContent = seedNote || (haveGroup
    ? `${group.travelers.length} travelers.`
    : "Add at least two travelers to continue.");

  // Someone without a calendar is treated as free all window, which quietly
  // flatters every option. Say so rather than letting it pass unnoticed.
  $("hint-2").textContent = !ready
    ? "Attach at least two calendars to continue."
    : missing.length
      ? `${withCal} attached. ${missing.join(", ")} ${missing.length === 1 ? "has" : "have"} none — they will count as free all window.`
      : `All ${withCal} calendars attached.`;

  if (!haveGroup && page >= 2 && page <= 3) showPage(1);
  else if (!ready && page === 3) showPage(2);
}


/* ─────────────────────────── the party size ────────────────────────────── */

const MIN_PARTY = 2;
const MAX_PARTY = 12;
function partySize() {
  const raw = parseInt($("party-size").value, 10);
  if (Number.isNaN(raw)) return MIN_PARTY;
  return Math.min(MAX_PARTY, Math.max(MIN_PARTY, raw));
}

function syncParty() {
  const n = partySize();
  $("party-size").value = n;
  $("party-minus").disabled = n <= MIN_PARTY;
  $("party-plus").disabled = n >= MAX_PARTY;
}

// A card counts as filled once someone has typed into it or attached a
// calendar. Seeding must never quietly throw that away, so filled cards are
// always kept and blanks are only ever added.
function hasContent(t) {
  return (t.busy_blocks || []).length > 0
    || (t.must_have || "").trim() !== ""
    || (t.likes || []).length > 0
    || (t.dislikes || []).length > 0
    || !/^Traveler \d+$/.test((t.name || "").trim());
}

function blankTraveler(i) {
  return { name: `Traveler ${i}`, home_airport: "JFK", budget_usd: 1200,
           likes: [], dislikes: [], must_have: "", lodging_tier: "mid",
           busy_blocks: [] };
}

// Set when someone asks for a smaller quorum than they have already filled
// in, so the roster can explain why it did not shrink.
let seedNote = "";
// True while the roster is demo data nobody has touched. Real entries are
// never discarded to honour a number nudged on another screen; sample people
// are, because they are scenery.
let fromSample = false;

async function seedRoster(n) {
  const keep = fromSample ? [] : group.travelers.filter(hasContent);
  const seeded = keep.slice();
  for (let i = seeded.length; i < n; i += 1) seeded.push(blankTraveler(i + 1));
  seedNote = keep.length > n
    ? `You already have ${keep.length} travelers filled in, so nothing was removed.`
    : "";
  group.travelers = seeded;
  renderRoster();
  await pushGroup();
}

/* ──────────────────────────────── wiring ────────────────────────────────── */

// Fill exactly the number of places the user asked for, drawn at random from
// the twelve sample people — so the demo is not always the same five faces.
async function loadSample(attack = "none") {
  const count = group.travelers.length || partySize();
  try {
    applyState(await api(
      `/api/group/sample?attack=${attack}&count=${count}`, { method: "POST" }));
  } catch (err) { showError(err.message); }
}

$("btn-sample").onclick = () => loadSample();
// The button is on the About page, but the catch shows up in the flow, so
// take the reader there once the poisoned calendar is loaded.
$("btn-attack").onclick = async () => {
  await loadSample("overt");
  showPage(2);
};
$("alert-about").onclick = () => showPage(4);
$("btn-add").onclick = () => {
  fromSample = false;
  group.travelers.push({ name: `Traveler ${group.travelers.length + 1}`, home_airport: "JFK",
    budget_usd: 1200, likes: [], dislikes: [], must_have: "", lodging_tier: "mid", busy_blocks: [] });
  renderRoster(); pushGroup();
};
$("btn-plan").onclick = () => { if (!planning) runPlan(); };
$("brand-home").onclick = () => showPage(0);
$("nav-about").onclick = () => showPage(4);
$("hero-about").onclick = () => showPage(4);
$("nav-home").onclick = () => showPage(page === 4 ? 1 : page);
$("about-back").onclick = () => showPage(0);
$("to-home").onclick = () => showPage(0);
$("btn-start").onclick = async () => {
  await seedRoster(partySize());
  showPage(1);
};
$("party-minus").onclick = () => { $("party-size").value = partySize() - 1; syncParty(); };
$("party-plus").onclick  = () => { $("party-size").value = partySize() + 1; syncParty(); };
$("party-size").oninput  = syncParty;
$("party-size").onblur   = syncParty;
$("to-page-2").onclick = () => showPage(2);
$("to-page-3").onclick = () => showPage(3);
$("to-page-1").onclick = () => showPage(1);
$("btn-sample-cal").onclick = () => loadSample();
document.querySelectorAll(".step").forEach((b) => {
  b.onclick = () => { if (!b.disabled) showPage(Number(b.dataset.page)); };
});
$("btn-details").onclick = () => {
  const el = $("details");
  el.hidden = !el.hidden;
  $("btn-details").textContent = el.hidden ? "Show" : "Hide";
};
$("btn-trace").onclick = () => {
  const el = $("trace");
  el.hidden = !el.hidden;
  $("btn-trace").textContent = el.hidden ? "Show every step" : "Hide";
};
["nights", "horizon-start", "horizon-end"].forEach((id) => { $(id).onchange = pushGroup; });

(async function boot() {
  try {
    const state = await api("/api/state");
    $("foot-model").textContent = state.model;
    $("about-model").textContent = state.model;
    // Nothing is shown when the credential is fine. When it is missing the
    // banner says so, because "nothing happens and I don't know why" is the
    // worst way for someone running this for the first time to find out.
    if (state.provider === "none") {
      $("keywarn").classList.add("show");
      $("keywarn-detail").textContent = state.key_status;
    }
    applyState(state.group);
    if (group.travelers.length >= MIN_PARTY) {
      $("party-size").value = group.travelers.length;
    }
    syncParty();
    showPage(0);
  } catch (err) { showError(err.message); }
})();
