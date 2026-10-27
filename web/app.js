// FINN web app. No framework, no build step: hash routes render into <main> from the read-only API.
// Every number shown comes from the API unchanged; the client only formats, filters and links.

const CFG = window.FINN_CONFIG || {};
const API = String(CFG.apiBase || "").replace(/\/+$/, "");
const TIMEOUT_MS = Number(CFG.timeoutMs) || 45000;
const SLOW_MS = 4000;
const SETTINGS_KEY = "finn.settings.v1";
const DEFAULTS = { window: "24h", move_pct: 5, volume_x: 2, lookback: 20, watch: [], mute: [], portfolio: null };
const WINDOWS = [["24h", "24 h"], ["3d", "3 days"], ["7d", "7 days"], ["30d", "30 days"]];
const CATEGORY_LABELS = {
  results: "Results", "M&A": "M&A", management_change: "Management change", litigation: "Litigation",
  fund_raise: "Fund raise", pledging: "Pledge", credit_rating: "Credit rating", bonus_split: "Bonus / split",
  capex: "Capex", dividend: "Dividend", earnings_call: "Earnings call", press_release: "Press release",
  insider_trading: "Insider / SAST", investor_meetings: "Investor meetings", agm_egm: "AGM / EGM",
  postal_ballot: "Postal ballot", unclassified: "Compliance", needs_review: "Needs review",
  price_move: "Price move", volume_spike: "Unusual volume",
};
const VALIDATION = {
  golden_verified: ["Checked vs signed PDF", "Values match figures hand-transcribed from the signed results PDF."],
  integrity_checked: ["Identity-checked", "Accounting identities hold; not compared with the PDF by hand."],
  integrity_failed: ["Integrity failed", "An accounting identity failed; treat with caution."],
  unavailable: ["Unavailable", "No results could be ingested."],
};

// ---------------------------------------------------------------- utilities

const $main = () => document.getElementById("main");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (typeof u === "string" && /^https:\/\//i.test(u) ? u : null);
const ext = (u, label) => (safeUrl(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>` : `<span class="muted">${esc(label)}: no link</span>`);

function fmtTime(iso, zone = "Asia/Kolkata", suffix = "IST") {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return esc(iso);
  return new Intl.DateTimeFormat("en-GB", { timeZone: zone, day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(d) + " " + suffix;
}
const fmtUTC = (iso) => fmtTime(iso, "UTC", "UTC");
function fmtDay(isoDate) {
  if (!isoDate) return "—";
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" }).format(Date.UTC(y, m - 1, d));
}
function fmtCr(v) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!isFinite(n)) return esc(v);
  return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " cr";
}
function fmtPct(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  if (!isFinite(n)) return null;
  // Direction glyph only: a change is not labelled good or bad without context.
  return `${n > 0 ? "▲" : n < 0 ? "▼" : "•"} ${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}
const fmtNum = (v, d = 2) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d }));
function quarterBefore(isoDate, months) {
  const [y, m] = isoDate.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1 - months + 1, 0));       // last day of the month `months` earlier
  return t.toISOString().slice(0, 10);
}
const monthLabel = (isoDate) => new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", month: "short", year: "numeric" }).format(new Date(isoDate + "T00:00:00Z"));

const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch { return false; } },
};

function loadSettings() {
  const s = { ...DEFAULTS, ...(store.get(SETTINGS_KEY) || {}) };
  if (!WINDOWS.some(([k]) => k === s.window)) s.window = DEFAULTS.window;
  for (const k of ["watch", "mute"]) if (!Array.isArray(s[k])) s[k] = [];
  if (s.portfolio !== null && !Array.isArray(s.portfolio)) s.portfolio = null;
  return s;
}

const state = {
  settings: loadSettings(),
  filters: { priority: "all", category: "all", symbol: "all" },
  cache: new Map(),          // path -> {data, at}
  companies: null,
  lastInbox: null,
  route: 0,
};

// ---------------------------------------------------------------- API

class ApiError extends Error {
  constructor(kind, status, message, body) { super(message); this.kind = kind; this.status = status; this.body = body; }
}

async function getJSON(path) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  let res;
  try {
    res = await fetch(API + path, { signal: ctrl.signal, headers: { Accept: "application/json" } });
  } catch (e) {
    throw new ApiError(e.name === "AbortError" ? "timeout" : "network", 0, e.name === "AbortError"
      ? `No answer after ${Math.round(TIMEOUT_MS / 1000)} s.` : "The FINN server could not be reached.");
  } finally {
    clearTimeout(timer);
  }
  let body = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) throw new ApiError("http", res.status, (body && (body.reason || body.error)) || `HTTP ${res.status}`, body);
  if (body === null) throw new ApiError("parse", res.status, "The server answered, but not with FINN data.");
  return body;
}

// Fetch with a visible loading state; keeps the last good copy when a refresh fails.
async function load(path, label, { inline = null, preferCache = false } = {}) {
  const token = state.route;
  const cached = state.cache.get(path);
  if (preferCache && cached) return { data: cached.data, stale: null };
  const started = Date.now();
  let tick = null;
  if (!inline) {
    const paint = () => {
      if (token !== state.route) return;
      const s = Math.round((Date.now() - started) / 1000);
      const slow = Date.now() - started > SLOW_MS;
      $main().innerHTML = `<section class="state" data-testid="loading" aria-busy="true">
        <div class="spinner" aria-hidden="true"></div>
        <h2>${esc(label)}</h2>
        <p>${slow ? "Waking the FINN server. Free hosting sleeps when idle; the first request after a pause took about 24 s when measured." : "Fetching from the committed snapshot."}</p>
        <p class="small muted num" aria-live="off">${s} s</p></section>`;
    };
    paint();
    tick = setInterval(paint, 1000);
  }
  try {
    const data = await getJSON(path);
    state.cache.set(path, { data, at: new Date() });
    return { data, stale: null };
  } catch (err) {
    if (cached && err.kind !== "http") return { data: cached.data, stale: { err, at: cached.at } };
    throw err;
  } finally {
    if (tick) clearInterval(tick);
  }
}

function errorState(err, retry, what = "this view") {
  const s = err.status;
  let title = "Could not load " + what, body = esc(err.message);
  if (err.kind === "timeout") { title = "The server is taking too long"; body = "It may still be waking up. Retrying usually works within a minute."; }
  else if (err.kind === "network") { title = "Can't reach the FINN server"; body = "Check the connection, then retry. This is a connection problem, not an empty result."; }
  else if (s === 429) { title = "Too many requests"; body = "The server asked us to slow down. Wait a few seconds, then retry."; }
  else if (s >= 500) { title = "The server had a problem"; body = `HTTP ${s}: ${esc(err.message)}. Nothing was lost; retry.`; }
  else if (s === 404) { title = "Not available"; }
  const id = "retry-" + Math.random().toString(36).slice(2);
  setTimeout(() => { const b = document.getElementById(id); if (b) b.onclick = retry; });
  return `<section class="state" data-testid="error" role="alert">
    <h2>${title}</h2><p>${body}</p>
    <p class="small muted">Failure is not the same as "no events": FINN could not check.</p>
    <div class="btn-row" style="justify-content:center"><button class="btn" id="${id}" data-testid="retry">Retry</button></div></section>`;
}

const staleBanner = (stale) => stale ? `<div class="banner bad" role="status" data-testid="stale">Refresh failed (${esc(stale.err.message)}). Showing data loaded at ${esc(stale.at.toLocaleTimeString())}.</div>` : "";

function setFresh(f, snap) {
  const el = document.getElementById("fresh");
  if (!el) return;
  const parts = [];
  if (snap && snap.as_of) parts.push(`Snapshot <b>${esc(fmtDay(snap.as_of))}</b>`);
  if (f && f.announcements_retrieved_at) parts.push(`filings to <b>${esc(fmtTime(f.announcements_retrieved_at))}</b>`);
  if (f && f.last_price_session) parts.push(`prices EOD <b>${esc(fmtDay(f.last_price_session))}</b>`);
  if (parts.length) el.innerHTML = parts.join(" · ") + ` <span class="muted">· not live</span>`;
}

async function companies() {
  if (state.companies) return state.companies;
  const { data } = await load("/api/v1/companies", "Loading companies", { inline: true });
  state.companies = data;
  setFresh(null, data.snapshot);
  return data;
}

// ---------------------------------------------------------------- signals

function inboxPath(s) {
  const q = new URLSearchParams({ window: s.window, move_pct: s.move_pct, volume_x: s.volume_x, lookback: s.lookback });
  if (s.watch.length) q.set("watch", s.watch.join(","));
  if (s.mute.length) q.set("mute", s.mute.join(","));
  if (s.portfolio && s.portfolio.length) q.set("symbols", s.portfolio.join(","));
  return "/api/v1/signals?" + q.toString();
}

function whyLine(sig) {
  return sig.score_parts.map((p) => `${esc(p.rule)} +${p.points}`).join(" · ");
}

function miniResults(n) {
  if (!n || !n.rows || !n.rows.length) return "";
  return `<table class="minitable num"><thead><tr><th>${esc(monthLabel(n.period_end))}</th><th>Value</th><th>QoQ</th><th>YoY</th></tr></thead><tbody>${
    n.rows.filter((r) => r.status !== "not_applicable").slice(0, 4).map((r) => `<tr><td>${esc(r.label)}</td><td>${fmtCr(r.value_cr)}</td>
      <td>${fmtPct(r.qoq.pct) ?? "—"}</td><td>${fmtPct(r.yoy.pct) ?? "—"}</td></tr>`).join("")}</tbody></table>`;
}

function card(sig) {
  const when = sig.kind === "price" ? `Session ${fmtDay(sig.session_day)}` : fmtTime(sig.published_at);
  return `<a class="card ${esc(sig.priority)}" href="#/signal/${encodeURIComponent(sig.id)}" data-testid="signal-card"
      data-id="${esc(sig.id)}" data-symbol="${esc(sig.symbol)}" data-category="${esc(sig.category)}" data-priority="${esc(sig.priority)}">
    <div class="card-top"><span class="sym">${esc(sig.symbol)}</span><span class="chip ${esc(sig.priority)}">${esc(sig.priority)}</span>
      <span class="chip">${esc(sig.category_label)}</span><span>${esc(when)}</span><span class="score" title="attention score">${sig.score}</span></div>
    <p class="card-title">${esc(shortTitle(sig.title))}</p>
    <div class="why">Why surfaced: ${whyLine(sig)}</div>
    ${sig.numbers ? miniResults(sig.numbers) : ""}
  </a>`;
}

function applyFilters(list) {
  const f = state.filters;
  return list.filter((s) => (f.symbol === "all" || s.symbol === f.symbol)
    && (f.category === "all" || s.category === f.category)
    && (f.priority === "all" || (f.priority === "high" ? s.priority === "high" : s.priority !== "low")));
}

async function viewSignals({ preferCache = false } = {}) {
  const s = state.settings;
  let res;
  try { res = await load(inboxPath(s), "Loading your Signal Inbox", { preferCache }); }
  catch (err) { $main().innerHTML = errorState(err, render, "the Signal Inbox"); return; }
  const d = res.data;
  state.lastInbox = d;
  setFresh(d.freshness, d.snapshot);
  const all = d.signals;
  const shown = applyFilters(all);
  const folded = d.folded.filter((x) => state.filters.symbol === "all" || x.symbol === state.filters.symbol);
  const cats = [...new Set(all.map((x) => x.category))].sort();
  const syms = [...new Set([...all, ...d.folded].map((x) => x.symbol))].sort();
  const w = d.window;
  const winLabel = WINDOWS.find(([k]) => k === w.key)?.[1] ?? w.key;
  const opt = (v, label, cur) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(label)}</option>`;

  let list;
  if (!all.length) {
    list = `<section class="state panel" data-testid="empty"><h2>No material events in this window</h2>
      <p>None of your ${d.symbols.length} companies filed a ranked announcement or crossed a price or volume rule between
      ${esc(fmtTime(w.start))} and ${esc(fmtTime(w.end))}.</p>
      <p class="small muted">This is a checked result from the snapshot, not a loading failure.${d.counts.folded ? ` ${d.counts.folded} routine filing(s) are folded below.` : ""}</p>
      ${w.key !== "30d" ? `<div class="btn-row" style="justify-content:center"><button class="btn ghost" data-win="30d">Widen to 30 days</button></div>` : ""}</section>`;
  } else if (!shown.length) {
    list = `<section class="state panel" data-testid="filtered-empty"><h2>Nothing matches these filters</h2>
      <p>${all.length} signal(s) are hidden by the filters above.</p>
      <div class="btn-row" style="justify-content:center"><button class="btn ghost" id="clear-filters">Clear filters</button></div></section>`;
  } else {
    list = shown.map(card).join("");
  }

  $main().innerHTML = `${staleBanner(res.stale)}
    <p class="lede">What changed, why it matters, and the evidence behind it.</p>
    <p class="sub">Ranked NSE filings and price/volume rules for your ${d.symbols.length} holdings.</p>
    <div class="seg" role="group" aria-label="Digest window">${WINDOWS.map(([k, l]) =>
      `<button type="button" data-win="${k}" aria-pressed="${k === w.key}">${esc(l)}</button>`).join("")}</div>
    <div class="filters">
      <label>Priority<select id="f-priority" data-testid="f-priority">${opt("all", "All", state.filters.priority)}${opt("high", "High", state.filters.priority)}${opt("medium", "Medium+", state.filters.priority)}</select></label>
      <label>Category<select id="f-category" data-testid="f-category">${opt("all", "All", state.filters.category)}${cats.map((c) => opt(c, CATEGORY_LABELS[c] || c, state.filters.category)).join("")}</select></label>
      <label>Company<select id="f-symbol" data-testid="f-symbol">${opt("all", "All", state.filters.symbol)}${syms.map((c) => opt(c, c, state.filters.symbol)).join("")}</select></label>
    </div>
    <p class="summary" data-testid="summary"><b>${d.counts.high} high</b> · ${d.counts.ranked - d.counts.high} other ranked · ${d.counts.folded} routine folded${d.counts.muted ? ` · ${d.counts.muted} muted` : ""}
      <br><span class="muted">${esc(winLabel)} window: ${esc(fmtTime(w.start))} → ${esc(fmtTime(w.end))}, ending when the snapshot was built.</span></p>
    <div data-testid="signal-list">${list}</div>
    ${folded.length ? `<details class="fold" data-testid="folded"><summary>${folded.length} routine filing${folded.length > 1 ? "s" : ""} folded (compliance, meetings, procedure)</summary>
      ${folded.map((x) => `<div class="fold-item"><b>${esc(x.symbol)}</b> · ${esc(x.category_label)} · ${esc(fmtTime(x.published_at))}<br>${esc(shortTitle(x.title))}<br>${ext(x.source.document_url, "Filing")}</div>`).join("")}</details>` : ""}
    <section class="panel small">
      <h2>How this inbox ranks</h2>
      <p>${esc(d.ranking)}</p>
      <p class="muted">Price rules: |move| ≥ ${esc(d.settings.move_pct)}%; volume ≥ ${esc(d.settings.volume_x)}× the ${esc(d.settings.lookback)}-session average, on completed EOD sessions only.
      Rules run when you open FINN; FINN does not send push notifications.</p>
      ${priceCoverageNote(d)}
      <div class="btn-row"><a class="btn ghost" href="#/settings">Change thresholds</a></div>
    </section>`;

  for (const b of document.querySelectorAll("[data-win]")) b.onclick = () => { state.settings.window = b.dataset.win; saveSettings(); render(); };
  for (const [id, key] of [["f-priority", "priority"], ["f-category", "category"], ["f-symbol", "symbol"]]) {
    document.getElementById(id).onchange = (e) => { state.filters[key] = e.target.value; viewSignalsFromCache(); };
  }
  const cf = document.getElementById("clear-filters");
  if (cf) cf.onclick = () => { state.filters = { priority: "all", category: "all", symbol: "all" }; viewSignalsFromCache(); };
}

function priceCoverageNote(d) {
  const bad = d.price_coverage.filter((c) => c.volume_evaluable === false || !c.sessions);
  if (!bad.length) return "";
  return `<p class="muted" data-testid="price-gaps">Could not evaluate the volume rule for ${bad.map((c) => `${esc(c.symbol)} (${esc(c.reason || "no data")})`).join("; ")}.</p>`;
}

function viewSignalsFromCache() { viewSignals({ preferCache: true }); }   // filters are client-side: no new request

// ---------------------------------------------------------------- receipt

async function findSignal(id) {
  const all = (d) => d ? [...d.signals, ...d.folded] : [];
  let hit = all(state.lastInbox).find((x) => x.id === id);
  if (hit) return { sig: hit, inbox: state.lastInbox };
  const wide = { ...state.settings, window: "30d" };
  const { data } = await load(inboxPath(wide), "Loading the signal");
  hit = all(data).find((x) => x.id === id);
  return { sig: hit, inbox: data };
}

async function viewSignal(id) {
  let found;
  try { found = await findSignal(id); }
  catch (err) { $main().innerHTML = errorState(err, render, "this signal"); return; }
  const { sig, inbox } = found;
  if (!sig) {
    $main().innerHTML = `<a class="back" href="#/signals">‹ Signals</a><section class="state panel" data-testid="signal-missing">
      <h2>This signal is not in the current snapshot</h2><p>It may belong to an older snapshot, or your mute settings hide it.</p></section>`;
    return;
  }
  setFresh(inbox.freshness, inbox.snapshot);
  const co = (await companies().catch(() => null))?.companies?.find((c) => c.symbol === sig.symbol);
  const total = sig.score_parts.reduce((a, p) => a + p.points, 0);
  const src = sig.source || {};
  const n = sig.numbers;
  let numbers = "";
  if (n && n.rows.length) {
    numbers = `<section class="panel"><h2>Supporting numbers</h2>
      <p class="small muted">From the verified results card: quarter ended ${esc(fmtDay(n.period_end))}, ${esc(n.basis)}, XBRL published ${esc(fmtTime(n.xbrl_published_at))}.</p>
      ${metricsTable(n.rows, n.period_end)}<p class="small muted">${esc(n.comparison_basis)}.</p>
      <div class="link-row">${ext(n.xbrl_url, "XBRL filing")}</div></section>`;
  } else if (sig.calculation) {
    numbers = `<section class="panel"><h2>Calculation</h2><p class="calc num" data-testid="calc">${esc(sig.calculation)}</p>
      <dl class="kv num small"><dt>Session</dt><dd>${esc(fmtDay(sig.stats.day))} (close)</dd><dt>Previous</dt><dd>${esc(fmtDay(sig.stats.prev_day))}</dd>
      <dt>Close</dt><dd>${fmtNum(sig.stats.close)} (prev ${fmtNum(sig.stats.prev_close)})</dd>
      <dt>Volume</dt><dd>${fmtNum(sig.stats.volume, 0)}${sig.stats.avg_volume ? ` vs avg ${fmtNum(sig.stats.avg_volume, 0)} over ${sig.stats.lookback_used} sessions` : " (average not computable)"}</dd></dl></section>`;
  }
  $main().innerHTML = `<a class="back" href="#/signals">‹ Signals</a>
    <article data-testid="receipt">
    <div class="receipt-head"><div class="card-top"><span class="sym">${esc(sig.symbol)}</span><span class="chip ${esc(sig.priority)}">${esc(sig.priority)} priority</span><span class="chip">${esc(sig.category_label)}</span></div>
      <h1>${esc(shortTitle(sig.title))}</h1></div>
    <section class="panel"><h2>What happened</h2><p>${esc(sig.what_happened)}</p>
      ${sig.nse_subject ? `<p class="small"><span class="muted">Headline, verbatim:</span> “${esc(sig.title)}”</p>
      <p class="small muted">NSE subject: “${esc(sig.nse_subject)}”.</p>` : ""}</section>
    <section class="panel"><h2>Why FINN surfaced it</h2>
      <ul class="plain parts">${sig.score_parts.map((p) => `<li><span class="pts">+${p.points}</span><span><b>${esc(p.rule)}</b><br><span class="muted">${esc(p.why)}</span></span></li>`).join("")}
      <li class="total"><span class="pts">${total}</span><span>Attention score → ${esc(sig.priority)} priority${sig.routine ? " (routine: folded in the inbox)" : ""}</span></li></ul>
      <p class="small muted">Priority ranks how much attention this kind of event usually deserves. It is not a probability that the share price will move.</p></section>
    <section class="panel"><h2>Company and period</h2><dl class="kv">
      <dt>Company</dt><dd>${esc(co?.name || sig.company || sig.symbol)} (${esc(sig.symbol)})</dd>
      ${co?.sector ? `<dt>Sector</dt><dd>${esc(co.sector)} <span class="muted">(FINN grouping)</span></dd>` : ""}
      <dt>${sig.kind === "price" ? "Session" : "Period"}</dt><dd>${sig.kind === "price" ? esc(fmtDay(sig.session_day)) + " (completed EOD)" : n ? "Quarter ended " + esc(fmtDay(n.period_end)) : "Not stated by the filing metadata"}</dd></dl></section>
    ${numbers}
    <section class="panel"><h2>Evidence</h2><dl class="kv">
      <dt>Source</dt><dd>${sig.kind === "price" ? "Yahoo Finance daily chart (EOD)" : "NSE corporate announcement"}</dd>
      ${src.document_url ? `<dt>Document</dt><dd data-testid="document">${ext(src.document_url, "Open the filing")}</dd>` : ""}
      <dt>Listing</dt><dd>${ext(src.listing_url, sig.kind === "price" ? "Price feed request" : "NSE announcement search")}</dd>
      ${sig.published_at ? `<dt>Published</dt><dd>${esc(fmtTime(sig.published_at))}<br><span class="mono" data-testid="published-raw">${esc(sig.published_at)}</span></dd>` : `<dt>Session close</dt><dd>${esc(fmtTime(sig.event_time))}</dd>`}
      <dt>Retrieved</dt><dd>${esc(fmtUTC(src.retrieved_at))}<br><span class="mono" data-testid="retrieved-raw">${esc(src.retrieved_at)}</span></dd>
      <dt>Provenance</dt><dd>${esc(src.provenance)} <span class="muted">(served from the committed snapshot, not live)</span></dd>
      ${src.content_hash ? `<dt>sha256</dt><dd class="mono">${esc(src.content_hash.slice(0, 16))}…</dd>` : ""}
      ${sig.classification ? `<dt>Classified by</dt><dd>${esc(sig.classification.method.replace("_", " "))}</dd>` : ""}
    </dl></section>
    <section class="panel"><h2>What FINN doesn't know</h2><ul class="bul">${sig.unknowns.map((u) => `<li>${esc(u)}</li>`).join("")}</ul></section>
    <div class="btn-row"><a class="btn" href="#/company/${encodeURIComponent(sig.symbol)}" data-testid="open-research">Open ${esc(sig.symbol)} research →</a></div>
    </article>`;
}

// ---------------------------------------------------------------- research

async function viewResearch(query = "") {
  let data;
  try { data = (await load("/api/v1/companies", "Loading companies")).data; state.companies = data; }
  catch (err) { $main().innerHTML = errorState(err, render, "the company list"); return; }
  setFresh(null, data.snapshot);
  const groups = [["portfolio", "Your portfolio"], ["research", "Research set (outside the portfolio)"]];
  $main().innerHTML = `<p class="lede">Research a company from its own filings.</p>
    <p class="sub">${data.count} NSE companies are in this snapshot. Search by ticker or name.</p>
    <form id="search" role="search" class="field"><label for="q">Ticker or company</label>
      <input id="q" type="search" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="e.g. POLYCAB" value="${esc(query)}" data-testid="search"></form>
    <div id="search-msg" aria-live="polite"></div>
    ${groups.map(([g, title]) => `<section class="panel"><h2>${title}</h2><ul class="plain co-list" data-group="${g}">${
      data.companies.filter((c) => c.groups.includes(g)).map((c) => `<li data-sym="${esc(c.symbol)}" data-name="${esc((c.name || "").toLowerCase())}">
        <a href="#/company/${encodeURIComponent(c.symbol)}" data-testid="company-link"><span class="sym">${esc(c.symbol)}</span>
        <span class="nm">${esc(c.name || "")}${c.sector ? ` · ${esc(c.sector)}` : ""}</span>
        <span class="chip ${c.validation === "golden_verified" ? "acc" : ""}">${esc(monthLabel(c.latest_period_end || "1970-01-01"))}</span></a></li>`).join("")}</ul></section>`).join("")}`;
  const input = document.getElementById("q");
  const filter = () => {
    const q = input.value.trim().toLowerCase();
    let n = 0;
    for (const li of document.querySelectorAll(".co-list li")) {
      const hit = !q || li.dataset.sym.toLowerCase().includes(q) || li.dataset.name.includes(q);
      li.hidden = !hit; n += hit;
    }
    document.getElementById("search-msg").innerHTML = q && !n ? unsupportedMsg(input.value.trim().toUpperCase(), data.count) : "";
  };
  input.oninput = filter;
  document.getElementById("search").onsubmit = (e) => {
    e.preventDefault();
    const sym = input.value.trim().toUpperCase();
    if (!sym) return;
    const exact = data.companies.find((c) => c.symbol === sym);
    const visible = [...document.querySelectorAll(".co-list li:not([hidden])")];
    if (exact) location.hash = "#/company/" + encodeURIComponent(sym);
    else if (visible.length === 1) location.hash = "#/company/" + encodeURIComponent(visible[0].dataset.sym);
    else filter();
  };
  filter();
}

const unsupportedMsg = (sym, count) => `<div class="banner" data-testid="unsupported">“${esc(sym)}” is not in this snapshot.
  FINN serves the ${count} companies it has ingested and validated; research on other NSE tickers needs a snapshot rebuild
  (<span class="mono">python -m finn.snapshot build --symbols ${esc(sym)}</span>), which this phase does not run on demand.</div>`;

function metricsTable(rows, periodEnd) {
  const q = quarterBefore(periodEnd, 3), y = quarterBefore(periodEnd, 12);
  const delta = (c, label) => `<div class="d"><span class="dl">${label}</span>${c.status === "ok"
    ? `<span class="dv">${fmtPct(c.pct)}</span><span class="prev">from ${fmtCr(c.prev_cr)}</span>`
    : `<span class="dv muted">${esc(c.status === "not_applicable" ? "n/a" : c.status.replace(/_/g, " "))}</span>${c.note ? `<span class="prev">${esc(c.note)}</span>` : ""}`}</div>`;
  return `<div class="metrics num" data-testid="metrics"><div class="kicker">Quarter ended ${esc(fmtDay(periodEnd))}</div>${
    rows.map((r) => `<div class="mrow" data-metric="${esc(r.metric)}">
      <div class="mhead"><span class="lbl" data-testid="metric-label">${esc(r.label)}${r.status === "derived" ? '<span class="badge-derived" title="computed from filed values">derived</span>' : ""}</span>
        <span class="val" data-testid="metric-value">${r.status === "not_applicable" ? '<span class="muted">n/a</span>' : fmtCr(r.value_cr)}</span></div>
      ${r.status === "not_applicable" ? "" : `<div class="mdelta">${delta(r.qoq, `QoQ vs ${esc(monthLabel(q))}`)}${delta(r.yoy, `YoY vs ${esc(monthLabel(y))}`)}</div>`}
      ${r.formula ? `<div class="note mono">${esc(r.formula)}</div>` : ""}${r.note ? `<div class="note">${esc(r.note)}</div>` : ""}</div>`).join("")}</div>`;
}

// NSE prefixes most headlines with "<Company> has informed the Exchange about/regarding". Cards drop that
// boilerplate for density; the receipt always shows the verbatim headline.
function shortTitle(t) {
  const s = String(t || "").replace(/^.{2,90}? has (?:informed|submitted to) the Exchange (?:about|regarding|that)?\s*/i, "").replace(/^['‘]|['’]\.?$/g, "");
  return s ? s[0].toUpperCase() + s.slice(1) : t;
}

function resultsPanel(card) {
  const v = VALIDATION[card.validation?.level] || ["", ""];
  const src = card.rows[0]?.source || {};
  const checks = card.integrity || [];
  return `<section class="panel" data-testid="results-card"><h2>Latest results</h2>
    <p class="small"><b>Quarter ended ${esc(fmtDay(card.period_end))}</b> · ${esc(card.basis)} · ${card.taxonomy === "banking" ? "banking format" : "Ind-AS"}
      · <span class="chip ${card.validation?.level === "golden_verified" ? "acc" : ""}" title="${esc(v[1])}">${esc(v[0])}</span></p>
    ${metricsTable(card.rows, card.period_end)}
    ${card.ebitda_margin_pct ? `<p class="small">EBITDA margin <b class="num">${esc(Number(card.ebitda_margin_pct).toFixed(2))}%</b> <span class="muted">(EBITDA ÷ revenue, derived)</span></p>` : ""}
    ${card.taxonomy === "banking" ? `<p class="small muted">Banks are shown with bank metrics. FINN does not relabel total income as revenue or compute an EBITDA for a lender.</p>` : ""}
    <p class="small muted">${esc(card.comparison_basis)}.</p>
    ${checks.length ? `<details><summary class="small link-row">Integrity checks: ${checks.filter((c) => c.status === "pass").length}/${checks.length} pass</summary>
      <ul class="bul small">${checks.map((c) => `<li class="${c.status === "pass" ? "ok" : c.status === "warn" ? "warn" : "bad"}">${esc(c.status)}: ${esc(c.check)}${c.diff_crore ? ` (diff ${esc(c.diff_crore)} cr)` : ""}</li>`).join("")}</ul></details>` : ""}
    <dl class="kv small"><dt>Filed (NSE)</dt><dd>${esc(fmtTime(src.published_at))} <span class="mono">${esc(src.published_at || "")}</span></dd>
      <dt>Retrieved</dt><dd>${esc(fmtUTC(src.retrieved_at))}</dd><dt>Source</dt><dd>${ext(src.url, "XBRL filing")}</dd>
      <dt>Location</dt><dd class="mono">${esc(src.location || "")}</dd></dl></section>`;
}

function transcriptsPanel(t) {
  if (!t || t.status === "not_audited") {
    return `<section class="panel" data-testid="transcripts"><h2>Earnings-call transcripts</h2>
      <p class="small">Not retrieved for this company in the snapshot. Transcript inventory was audited for 3 companies (TCS, POLYCAB, HDFCBANK).</p></section>`;
  }
  return `<section class="panel" data-testid="transcripts"><h2>Earnings-call transcripts</h2>
    <p class="small"><b>${t.available} of ${t.requested}</b> target quarters available on NSE. Metadata only; transcript text is not stored.</p>
    <div>${t.quarters.map((q) => { const d = q.document; return `<div class="q-row"><span class="q">${esc(q.fiscal_quarter)}</span><span>
      ${q.status === "available" && d ? `${ext(d.url, `${d.pages} pages`)} · filed ${esc(fmtTime(d.broadcast_at))}<br><span class="muted">Quarter read from the text: “${esc(d.quarter_phrase || "")}” (p.${esc(d.quarter_page)})</span>`
        : `<span class="warn">${esc(q.status)}</span> ${esc(q.reason || "")}`}</span></div>`; }).join("")}</div></section>`;
}

const noGuidance = (why) => `<section class="panel" data-testid="guidance"><h2>Management guidance</h2>
  <p class="small"><b>Guidance analysis not yet available.</b> ${esc(cap(why || "FINN has not extracted or verified management commitments from these transcripts"))}. FINN shows none rather than a guessed list.</p></section>`;

// Verdict and stance wording. "Not reaffirmed" and "Can't be checked" are statements about the evidence, not about
// whether management will deliver.
const VERDICT = { met: ["Met", "ok"], partly_met: ["Partly met", "warn"], missed: ["Missed", "bad"], pending: ["Awaiting outcome", ""],
  not_reaffirmed: ["Not reaffirmed", "warn"], unverifiable: ["Can't be checked", "muted"] };
const STANCE = { restated: "Restated", tightened: "Tightened", reported: "Reported progress", explained: "Explained",
  not_restated: "Not restated", softened: "Softened", widened: "Widened", delayed: "Delayed" };
const cap = (t) => String(t || "").replace(/^./, (c) => c.toUpperCase());
const pageLink = (r) => ext(r.url ? `${r.url}#page=${r.page}` : null, `${r.quarter} transcript p.${r.page}`);

function said(r, who = "management") {
  return `<blockquote class="pq" data-testid="quote">“${esc(r.quote)}”</blockquote>
    <div class="note">${esc(r.speaker)} <span class="muted" title="${esc(r.role_evidence || "")}">(${esc(who)})</span> · ${esc(fmtTime(r.said_on))} · ${pageLink(r)}
      <span class="muted">· ${r.quote_check === "exact" ? "verbatim" : "verbatim after spacing/glyph repair"}</span></div>`;
}

function targetText(x) {
  const t = x.target, h = x.horizon || {};
  const u = (v) => (t.unit.startsWith("%") ? `${v}${t.unit}` : `${v} ${t.unit}`);
  const band = !t ? "" : t.high == null ? (t.low_exclusive ? `more than ${u(t.low)}` : `${u(t.low)} or more`) : t.unit.startsWith("%") ? `${t.low}% to ${u(t.high)}` : `${t.low} to ${u(t.high)}`;
  return [band, h.label ? `${h.label}${h.period_end && h.stated === false ? " (date inferred by FINN)" : ""}` : ""].filter(Boolean).join(" · ");
}

function computed(o) {
  if (o.method !== "computed") return `<p class="small"><b>Not computed.</b> ${esc(o.reason)}.</p>`;
  return `<p class="small"><b>Computed from filed results</b> <span class="muted">${esc(o.formula)}</span></p>
    <ul class="bul small num">${o.series.map((x) => `<li>Quarter ended ${esc(fmtDay(x.period_end))}: <b>${esc(x.value.toFixed(2))}%</b>
      <span class="muted">(EBITDA ${fmtCr(x.inputs_crore.ebitda)}, D&amp;A ${fmtCr(x.inputs_crore.dna)}, revenue ${fmtCr(x.inputs_crore.revenue)})</span></li>`).join("")}</ul>
    <p class="small">${esc(cap(o.reason))}.</p>`;
}

function promiseCard(x) {
  const [vl, vc] = VERDICT[x.verdict.status] || [x.verdict.status, ""];
  const f = x.follow_ups;
  return `<article class="pr-card" data-testid="promise" data-id="${esc(x.id)}" data-verdict="${esc(x.verdict.status)}">
    <div class="card-top"><span class="chip pv ${vc}" data-testid="verdict">${esc(vl)}</span><span class="small muted">${esc(x.kind.replace(/_/g, " "))}</span></div>
    <h3>${esc(x.title)}</h3>
    ${targetText(x) ? `<p class="small">${esc(targetText(x))}</p>` : ""}
    ${x.scope ? `<p class="small muted" data-testid="scope">Scope: ${esc(x.scope)}</p>` : ""}
    ${said(x.statement)}
    <p class="small pr-why" data-testid="verdict-reason"><b>Why ${esc(vl.toLowerCase())}:</b> ${esc(x.verdict.reason)}.</p>
    <details class="pr-more"><summary class="small link-row">Evidence: ${f.length} later statement${f.length === 1 ? "" : "s"}, calculation, FINN's reading</summary>
      <h4>What management said later</h4>
      ${f.length ? f.map((y) => `<div class="pr-follow" data-stance="${esc(y.stance)}"><span class="chip ${["softened", "widened", "delayed"].includes(y.stance) ? "medium" : ""}">${esc(STANCE[y.stance] || y.stance)}</span>
        ${y.prompted_by ? `<p class="note">Asked by ${esc(y.prompted_by.speaker)} (analyst, p.${esc(y.prompted_by.page)}): <i>“${esc(y.prompted_by.quote)}”</i></p>` : ""}
        ${said(y)}${y.note ? `<p class="note">${esc(y.note)}</p>` : ""}</div>`).join("")
        : `<p class="small muted">No later management statement on this was found in the audited calls. FINN does not treat silence as a change.</p>`}
      <h4>What FINN computed</h4>${computed(x.outcome)}
      <h4>FINN's reading</h4><p class="small" data-testid="interpretation">${esc(x.interpretation)}</p>
      ${x.audit_note ? `<p class="note">Audit note: ${esc(x.audit_note)}</p>` : ""}
    </details></article>`;
}

function promisesPanel(p) {
  if (p.status !== "ok" && p.status !== "stale") return noGuidance(p.reason);
  const c = p.counts || {};
  const order = ["missed", "not_reaffirmed", "partly_met", "met", "pending", "unverifiable"];
  const recs = [...p.records].sort((a, b) => order.indexOf(a.verdict.status) - order.indexOf(b.verdict.status));
  return `<section class="panel" data-testid="guidance"><h2>Promise Ledger</h2>
    <p class="small"><b>${p.records.length} management commitments</b> from ${p.transcripts.length} earnings calls${order.filter((k) => c[k]).map((k) => ` · ${c[k]} ${esc(VERDICT[k][0].toLowerCase())}`).join("")}.</p>
    ${p.stale ? `<p class="small warn" data-testid="ledger-stale">${esc(p.stale_reason)}.</p>` : ""}
    <p class="small muted">Each quote was found at the cited transcript page and attributed to a company speaker. Analysts' paraphrases are shown only as the question asked, never as guidance (${p.analyst_pointers} set aside). Selected and labelled by ${esc(p.ledger.audited_by)}.</p>
    <div>${recs.map(promiseCard).join("")}</div>
    ${p.excluded.length ? `<p class="small bad">${p.excluded.length} record(s) failed validation and are not shown.</p>` : ""}</section>`;
}

function filingsPanel(f) {
  if (!f) return "";
  const ranked = f.filings.filter((x) => !x.routine), routine = f.filings.filter((x) => x.routine);
  return `<section class="panel" data-testid="filings"><h2>NSE filings, last 30 days</h2>
    ${f.last_session ? `<p class="small">Last completed session ${esc(fmtDay(f.last_session.day))}: close <b class="num">${fmtNum(f.last_session.close)}</b> (${fmtPct(f.last_session.move_pct) ?? "—"}) <span class="muted">· Yahoo EOD</span></p>` : `<p class="small muted">No completed price sessions in the snapshot.</p>`}
    ${f.count ? "" : `<p class="small">No announcements in the stored window.</p>`}
    <ul class="plain">${ranked.slice(0, 12).map((x) => `<li class="f-row"><div class="card-top"><span class="chip">${esc(x.category_label)}</span><span>${esc(fmtTime(x.published_at))}</span></div>
      <div class="small">${esc(shortTitle(x.title))}</div><div class="small">${ext(x.document_url, "Filing")}</div></li>`).join("")}</ul>
    ${routine.length ? `<p class="small muted">${routine.length} routine filing(s) not listed.</p>` : ""}</section>`;
}

async function viewCompany(sym) {
  const token = state.route;
  $main().innerHTML = `<a class="back" href="#/research">‹ Research</a><section class="state" data-testid="loading"><div class="spinner"></div><h2>Loading ${esc(sym)}</h2><p class="small muted">Results, transcripts and filings from the snapshot.</p></section>`;
  const [co, results, trans, fil, prom] = await Promise.allSettled([
    companies(), getJSON(`/api/v1/companies/${encodeURIComponent(sym)}/results`),
    getJSON(`/api/v1/companies/${encodeURIComponent(sym)}/transcripts`), getJSON(`/api/v1/companies/${encodeURIComponent(sym)}/filings`),
    getJSON(`/api/v1/companies/${encodeURIComponent(sym)}/promises`)]);
  if (token !== state.route) return;
  const all = [results, trans, fil];
  const notFound = all.every((r) => r.status === "rejected" && r.reason.status === 404);
  if (notFound) {
    $main().innerHTML = `<a class="back" href="#/research">‹ Research</a><section class="panel" data-testid="unsupported-company">
      <h2>${esc(sym)} is not available</h2><p>${esc(results.reason.message)}</p>${unsupportedMsg(sym, co.value?.count ?? "the")}</section>`;
    return;
  }
  const failed = all.find((r) => r.status === "rejected" && r.reason.status !== 404);
  if (failed && all.every((r) => r.status === "rejected")) { $main().innerHTML = errorState(failed.reason, render, sym); return; }
  const c = co.value?.companies?.find((x) => x.symbol === sym);
  const sect = (r, fn, what) => r.status === "fulfilled" ? fn(r.value)
    : `<section class="panel"><h2>${what}</h2><p class="small ${r.reason.status === 404 ? "" : "bad"}">${esc(r.reason.message)}</p>
       ${r.reason.status === 404 ? "" : `<button class="btn ghost" data-retry>Retry</button>`}</section>`;
  $main().innerHTML = `<a class="back" href="#/research">‹ Research</a>
    <header class="co-head" data-testid="company"><div class="kicker">${esc(c?.sector || "")}${c?.groups?.includes("portfolio") ? " · in your portfolio" : c ? " · research set" : ""}</div>
      <h1>${esc(c?.name || sym)}</h1><p class="small muted">NSE: ${esc(sym)}${c?.sector ? " · sector is FINN's grouping" : ""}</p></header>
    ${sect(results, resultsPanel, "Latest results")}
    ${sect(trans, transcriptsPanel, "Earnings-call transcripts")}
    ${sect(prom, promisesPanel, "Promise Ledger")}
    ${sect(fil, filingsPanel, "NSE filings")}`;
  for (const b of document.querySelectorAll("[data-retry]")) b.onclick = render;
}

// ---------------------------------------------------------------- settings

function saveSettings() { return store.set(SETTINGS_KEY, state.settings); }

async function viewSettings() {
  const s = state.settings;
  let list = null;
  try { list = await companies(); } catch { /* the portfolio editor is optional */ }
  const portfolio = list ? list.companies.filter((c) => c.groups.includes("portfolio")).map((c) => c.symbol) : [];
  const chosen = new Set(s.portfolio || portfolio);
  const cats = ["results", "M&A", "management_change", "litigation", "fund_raise", "pledging", "credit_rating", "bonus_split",
    "capex", "dividend", "earnings_call", "press_release", "needs_review", "price_move", "volume_spike"];
  const box = (name, v, on, label) => `<label><input type="checkbox" name="${name}" value="${esc(v)}"${on ? " checked" : ""}>${esc(label)}</label>`;
  $main().innerHTML = `<a class="back" href="#/signals">‹ Signals</a>
    <form id="settings" data-testid="settings"><p class="lede">Alert rules</p>
    <p class="sub">Saved on this device. Rules are evaluated when you open FINN, on the snapshot's completed EOD sessions. FINN does not send push notifications.</p>
    <section class="panel">
      <div class="field"><label for="move_pct">Daily price move, %</label><input id="move_pct" name="move_pct" type="number" inputmode="decimal" min="0.5" max="50" step="0.5" value="${esc(s.move_pct)}" required>
        <span class="help">Flag a session whose close moved at least this much vs the previous close. Default 5%.</span></div>
      <div class="field"><label for="volume_x">Unusual volume, × average</label><input id="volume_x" name="volume_x" type="number" inputmode="decimal" min="1.1" max="20" step="0.1" value="${esc(s.volume_x)}" required>
        <span class="help">Flag volume at least this multiple of the recent average. Default 2×.</span></div>
      <div class="field"><label for="lookback">Average over, sessions</label><input id="lookback" name="lookback" type="number" inputmode="numeric" min="5" max="60" step="1" value="${esc(s.lookback)}" required>
        <span class="help">Completed sessions before the one being tested. Default 20. A ratio needs at least half of them.</span></div>
    </section>
    <section class="panel"><fieldset><legend>Watch: +15 points</legend><div class="checks">${cats.map((c) => box("watch", c, s.watch.includes(c), CATEGORY_LABELS[c])).join("")}</div></fieldset></section>
    <section class="panel"><fieldset><legend>Mute: hide from the inbox</legend><div class="checks">${cats.map((c) => box("mute", c, s.mute.includes(c), CATEGORY_LABELS[c])).join("")}</div></fieldset></section>
    ${portfolio.length ? `<section class="panel"><fieldset><legend>Companies in the inbox</legend><div class="checks">${portfolio.map((p) => box("portfolio", p, chosen.has(p), p)).join("")}</div></fieldset></section>` : ""}
    <p id="settings-msg" role="status" class="small"></p>
    <div class="btn-row"><button class="btn" type="submit" data-testid="save">Save rules</button><button class="btn ghost" type="button" id="reset">Reset defaults</button></div>
    </form>`;
  const form = document.getElementById("settings");
  form.onsubmit = (e) => {
    e.preventDefault();
    if (!form.reportValidity()) return;
    const fd = new FormData(form);
    const picked = fd.getAll("portfolio");
    state.settings = { ...state.settings, move_pct: Number(fd.get("move_pct")), volume_x: Number(fd.get("volume_x")),
      lookback: Math.round(Number(fd.get("lookback"))), watch: fd.getAll("watch"), mute: fd.getAll("mute"),
      portfolio: !portfolio.length || picked.length === portfolio.length ? null : picked };
    if (state.settings.portfolio && !state.settings.portfolio.length) {
      document.getElementById("settings-msg").textContent = "Keep at least one company in the inbox."; return;
    }
    const ok = saveSettings();
    document.getElementById("settings-msg").textContent = ok ? "Saved." : "Saved for this session only (this browser blocks storage).";
    location.hash = "#/signals";
  };
  document.getElementById("reset").onclick = () => { state.settings = { ...DEFAULTS }; saveSettings(); render(); };
}

// ---------------------------------------------------------------- router

async function render() {
  state.route += 1;
  const h = location.hash.replace(/^#/, "") || "/signals";
  const [, page, arg] = h.split("/");
  for (const a of document.querySelectorAll(".tabs a")) {
    const on = a.dataset.tab === (["research", "company"].includes(page) ? "research" : "signals");
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  window.scrollTo(0, 0);
  if (page === "signal" && arg) return viewSignal(decodeURIComponent(arg));
  if (page === "research") return viewResearch();
  if (page === "company" && arg) return viewCompany(decodeURIComponent(arg).toUpperCase());
  if (page === "settings") return viewSettings();
  return viewSignals();
}

window.addEventListener("hashchange", render);
render();
