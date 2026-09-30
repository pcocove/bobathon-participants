/* Bob Investigator — local UI. Vanilla JS, no build step.
   Every citation is a link: click → source drawer (cited line in context + verification),
   and from there "Open full document" / "Open original file" for human checking. */

const AGENT = new URLSearchParams(location.search).get("agent") === "guard" ? "guard" : "investigator";
const S = { state: null, view: "overview", suspect: null, logSince: 0, timeline: null, doc: null, riskFilter: {} };
const NAV = {
  investigator: [["overview", "Overview"], ["agent", "Agent (Bob)", "n-agent"], ["sweep", "Inconsistencies", "n-sweep"],
    ["suspects", "Suspects"], ["timeline", "Timeline"], ["security", "Security flaws", "n-sec"], ["tasks", "Tasks", "n-tasks"],
    ["docs", "Context docs"], ["verdict", "verdict.json"], ["search", "Search bundle"]],
  guard: [["overview", "Posture"], ["agent", "Agent (Bob)", "n-agent"], ["sweep", "Inconsistencies", "n-sweep"],
    ["risks", "Risk register", "n-risks"], ["rootcauses", "Root causes"], ["remediation", "Remediation plan"],
    ["tasks", "Tasks", "n-tasks"], ["docs", "Context docs"], ["search", "Search data"]],
};
const SEV_ORDER = { critical: 0, high: 1, medium: 2, low: 3 };
const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ICON = { INCRIMINATES: "🔴", WEAKLY_INCRIMINATES: "🟡", EXONERATES: "🟢", PROVES_INNOCENCE: "⚪", NEUTRAL: "·" };
const CLS_COLOR = { INCRIMINATES: "var(--red)", WEAKLY_INCRIMINATES: "var(--amber)", EXONERATES: "var(--green)", PROVES_INNOCENCE: "var(--slate)", NEUTRAL: "var(--ink-3)" };

function withAgent(path) {
  if (!path.startsWith("/api/")) return path;
  const [p, hash] = path.split("#");
  return p + (p.includes("?") ? "&" : "?") + "agent=" + AGENT + (hash ? "#" + hash : "");
}
async function api(path, opts = {}) {
  path = withAgent(path);
  const r = await fetch(path, opts.body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(opts.body) } : opts);
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
const person = (key) => (S.state?.case?.suspects || []).find((p) => p.handle === key || p.name === key);
const pname = (key) => person(key)?.name || key || "—";
const fmt = (iso) => { if (!iso) return "?"; const d = new Date(iso); return d.toLocaleString("de-CH", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); };

/* ------------------------------------------------------------ citations */
function viewerUrl(src, quote) {
  return `/view?agent=${AGENT}&src=${encodeURIComponent(src)}${quote ? `&quote=${encodeURIComponent(quote)}` : ""}`;
}
function rawUrl(src) {
  const path = src.replace(/:(\d+)(-\d+)?$/, "");
  const page = (src.match(/\.pdf:(\d+)$/) || [])[1];
  return `/api/raw?agent=${AGENT}&path=${encodeURIComponent(path)}${page ? `#page=${page}` : ""}`;
}
function statusMark(st) {
  if (!st || st === "unchecked") return "";
  if (st === "verified") return `<span class="st verified" title="exact quote found at this source">✓ verified</span>`;
  if (st === "ocr") return `<span class="st ocr" title="found in machine-read text — compare with the image">◐ OCR</span>`;
  if (st === "whitespace") return `<span class="st ocr" title="matches after whitespace normalisation">≈ verified</span>`;
  return `<span class="st bad">✗ ${esc(st)}</span>`;
}
function cite(e, opts = {}) {
  const q = e.quote || "";
  return `<div class="cite">
    <a class="src" data-src="${esc(e.source)}" data-quote="${esc(q)}" title="Show this line in context">${esc(e.source)}</a>
    ${statusMark(e.status) || "<span></span>"}
    <a class="faint" href="${viewerUrl(e.source, q)}" target="_blank" rel="noopener" title="Open the full document at this line">full doc ↗</a>
    <span class="q">${q ? "“" + esc(q.length > 220 ? q.slice(0, 219) + "…" : q) + "”" : ""}${e.note ? ` <span class="faint">— ${esc(e.note)}</span>` : ""}</span>
  </div>`;
}
function cites(list, limit = 99) {
  if (!list || !list.length) return `<div class="faint">no citation</div>`;
  return list.slice(0, limit).map((e) => cite(e)).join("");
}
document.addEventListener("click", async (ev) => {
  if (ev.target.id === "agent-stop") { api("/api/agent/stop", { body: {} }); return; }
  const dig = ev.target.closest("[data-dig]");
  if (dig) { ev.preventDefault(); ev.stopPropagation(); return agentDig(dig.dataset.dig); }
  const stp = ev.target.closest("[data-agent-step]");
  if (stp) { ev.preventDefault(); ev.stopPropagation(); return agentRun(stp.dataset.agentStep ? [stp.dataset.agentStep] : null); }
  const rv = ev.target.closest("[data-review]");
  if (rv) {
    ev.preventDefault(); ev.stopPropagation();
    const note = prompt(`Your note for ${rv.dataset.review} ${rv.dataset.id}:`);
    if (!note) return;
    try { await api("/api/review", { body: { id: rv.dataset.id, decision: rv.dataset.review, note } }); startPolling(); }
    catch (e) { alert(e.message); }
    return;
  }
  const a = ev.target.closest("[data-src]");
  if (a) { ev.preventDefault(); openSource(a.dataset.src, a.dataset.quote); return; }
  const nav = ev.target.closest("[data-view]");
  if (nav) { ev.preventDefault(); go(nav.dataset.view, nav.dataset.arg); }
});

async function openSource(src, quote) {
  const d = $("#drawer");
  d.classList.add("open"); d.setAttribute("aria-hidden", "false");
  $("#drawer-title").innerHTML = `${esc(src)}
    <div style="margin-top:6px;display:flex;gap:8px;flex-wrap:wrap">
      <a class="btn small" href="${viewerUrl(src, quote)}" target="_blank" rel="noopener">Open full document ↗</a>
      <a class="btn small" href="${rawUrl(src)}" target="_blank" rel="noopener">Open original file ↗</a>
    </div>`;
  $("#drawer-verify").innerHTML = "";
  $("#drawer-body").innerHTML = `<div class="empty">loading…</div>`;
  try {
    const v = await api(`/api/source?src=${encodeURIComponent(src)}&context=8${quote ? `&quote=${encodeURIComponent(quote)}` : ""}`);
    $("#drawer-body").innerHTML = renderSource(v, quote);
    if (v.verification) {
      const st = v.verification.status;
      $("#drawer-verify").innerHTML = `<div style="margin-top:6px">${statusMark(st)} <span class="faint">${esc(v.verification.detail || "")}${v.verification.suggestion ? " → " + esc(v.verification.suggestion) : ""}</span></div>`;
    }
    const hit = $("#drawer-body .hit");
    if (hit) hit.scrollIntoView({ block: "center" });
  } catch (e) {
    $("#drawer-body").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}
function highlight(text, quote) {
  const t = esc(text);
  if (!quote) return t;
  const q = esc(quote);
  const i = t.indexOf(q);
  return i < 0 ? t : t.slice(0, i) + "<mark>" + q + "</mark>" + t.slice(i + q.length);
}
function renderSource(v, quote) {
  if (v.error) return `<div class="empty">${esc(v.error)}</div>`;
  if (v.kind === "text") {
    return v.lines.map((l) => `<div class="src-line ${l.hit ? "hit" : ""}"><span class="n">${l.n}</span><span class="t">${l.hit ? highlight(l.text, quote) : esc(l.text)}</span></div>`).join("")
      + `<div class="faint" style="padding:8px 12px">line ${v.lines[0]?.n}–${v.lines.at(-1)?.n} of ${v.total}</div>`;
  }
  if (v.kind === "pdf") {
    return v.pages.map((p) => `<div class="${p.hit ? "hit" : ""}" style="padding:6px 12px">
      <div class="kicker">page ${p.page}${p.ocr ? " · OCR (image-only page — compare with the original)" : ""}</div>
      ${p.text.split("\n").map((ln) => `<div class="plain-line ${quote && ln.includes(quote) ? "hit" : ""}">${highlight(ln, quote)}</div>`).join("")}</div>`).join("");
  }
  if (v.kind === "xlsx") {
    return `<table>${v.rows.map((r) => `<tr class="${r.hit ? "hit" : ""}" style="${r.hit ? "background:var(--amber-bg)" : ""}"><td class="faint mono">${r.row}</td>${r.cells.map((c) => `<td>${highlight(c, quote)}</td>`).join("")}</tr>`).join("")}</table>`;
  }
  if (v.kind === "image") {
    return `<img src="${v.image}" alt="${esc(v.path)}"><div class="ocr-note">Text below is machine-read (OCR). The photo above is authoritative.</div>
      ${v.ocr_text.split("\n").map((ln) => `<div class="plain-line ${quote && ln.includes(quote) ? "hit" : ""}">${highlight(ln, quote)}</div>`).join("")}`;
  }
  return `<div class="empty">binary file</div>`;
}
$("#drawer-close").onclick = () => { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#drawer-close").click(); });

/* ------------------------------------------------------------ routing */
function go(view, arg) {
  S.view = view;
  if (view === "suspects" && arg) S.suspect = arg;
  if (view === "docs" && arg) S.doc = arg;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  location.hash = view + (arg ? ":" + arg : "");
  render();
  $("#main").focus();
}
function render() {
  const m = $("#main");
  if (!S.state || !(S.state.argue || S.state.posture)) {
    m.innerHTML = `<div class="empty">${S.state?.running ? "Pipeline running… first run reads ~480 files and takes a few seconds." : "No investigation yet — press “Re-run pipeline”."}${S.state?.error ? `<br><br><span class="cell-red">${esc(S.state.error)}</span>` : ""}</div>`;
    return;
  }
  const views = AGENT === "guard"
    ? { overview: guardOverview, agent: agentView, sweep: sweepView, risks: risksView, rootcauses: rootcausesView,
        remediation: remediationView, tasks: tasksView, docs: docsView, search: searchView }
    : { overview, agent: agentView, sweep: sweepView, security: securityView, suspects: suspectsView, timeline: timelineView, tasks: tasksView, docs: docsView, verdict: verdictView, search: searchView };
  (views[S.view] || views.overview)(m);
}

/* ------------------------------------------------------------ overview */
function overview(m) {
  const st = S.state, a = st.argue, cf = a.confidence_formula;
  const culprit = a.profiles.find((p) => p.key === a.culprit);
  const reds = st.findings.filter((f) => f.suspect === a.culprit && f.cls === "INCRIMINATES").sort((x, y) => y.score - x.score);
  const openH = st.tasks.filter((t) => t.kind === "human" && t.status === "open");
  const bl = st.baseline || {};
  const pb = st.playbook || [];
  const done = pb.filter((s) => s.complete).length;
  const rs = st.reviews_summary || {};
  m.innerHTML = `
  <div class="card" style="margin-bottom:14px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between">
    <div><div class="kicker">Mode: ${esc(st.mode || "agent")} · ${esc(a.basis || "")}</div>
      <div style="margin-top:4px">Playbook ${done}/${pb.length} steps done · proposals: ${rs.accepted || 0} accepted, ${rs.amended || 0} amended, ${rs.rejected || 0} rejected, <b>${rs.proposed || 0} awaiting review</b> · agent findings: ${(st.agent_findings || {}).accepted || 0}</div>
      <div class="faint" style="margin-top:2px">Tools-only baseline: <b>${esc(bl.culprit_name || "—")}</b> (${bl.confidence ?? "—"})${bl.culprit && bl.culprit !== a.culprit ? " — <span class='cell-red'>differs from the agent's verdict</span>" : ""}</div></div>
    <div style="display:flex;gap:8px"><a class="btn" data-view="agent">Open agent workspace</a><button class="btn primary" data-agent-step="">Let Bob work the playbook</button></div>
  </div>
  <div class="hero">
    <div class="card">
      <div class="kicker">Culprit</div>
      <div class="name">${esc(a.culprit_name || "—")}</div>
      <div style="display:flex;align-items:center;gap:10px;margin:8px 0">
        <div class="bar" style="flex:1"><span style="width:${Math.round(a.confidence * 100)}%"></span></div>
        <b>${a.confidence.toFixed(2)}</b>
      </div>
      <div class="chips">${cf.pillars.map((p) => `<span class="chip red">${esc(p)}</span>`).join("")}<span class="chip">margin ${cf.margin.toFixed(2)}</span>${cf.override != null ? `<span class="chip amber">human override</span>` : ""}</div>
      <div class="faint" style="margin-top:8px;font-size:12.5px">confidence = min(0.95, 0.5 + 0.08·pillars + 0.10·min(margin, 2.5)) − penalties
        ${cf.penalties.length ? "<br>penalties: " + cf.penalties.map((p) => `${esc(p.title)} (−${p.minus})`).join("; ") : ""}</div>
      <h3>Why — every claim links to its source</h3>
      ${reds.map((f) => `<div class="finding"><div class="f-head"><span class="f-title">${ICON[f.cls]} ${esc(f.title)}</span><span class="f-meta">${f.id}</span></div>
        <div class="f-claim">${esc(f.claim)}</div>${cites(f.evidence, 3)}</div>`).join("")}
    </div>
    <div class="grid">
      <div class="card"><div class="kicker">Pipeline</div>
        <div class="stepper" style="margin-top:8px">${st.stages.filter((s, i, arr) => arr.findIndex((x) => x.stage === s.stage) === i).map((s) => `<div class="step"><b>${esc(s.stage)}</b><span>${esc(s.detail)}</span></div>`).join("")}</div>
      </div>
      <div class="card"><div class="kicker">Misleading suspects — explained</div>
        ${a.misleading.length ? a.misleading.map((k) => {
          const route = st.findings.find((f) => f.suspect === k && f.explains);
          const sus = st.findings.find((f) => f.key === route?.explains);
          return `<div style="margin-top:8px"><a data-view="suspects" data-arg="${esc(k)}"><b>${esc(pname(k))}</b></a>
            <div class="f-claim">🟡 ${esc(sus?.claim || "")}</div>${sus ? cites(sus.evidence, 1) : ""}
            <div class="f-claim">🟢 ${esc(route?.title || "")}</div>${route ? cites(route.evidence, 3) : ""}</div>`;
        }).join("") : `<div class="faint">none</div>`}
      </div>
      ${st.security ? `<div class="card"><div class="kicker">Remaining security flaws</div>
        <div><b>${st.security.open}</b> still open · <b class="cell-red">${st.security.incident_open.length}</b> exposed by this incident</div>
        ${st.security.risks.filter((r) => r.incident && r.state !== "addressed").slice(0, 4).map((r) => `<div style="margin-top:4px"><span class="sev ${r.severity}">${r.severity}</span> ${esc(r.title)}</div>`).join("")}
        <div style="margin-top:8px"><a data-view="security">See all, with root causes and remediations →</a></div></div>` : ""}
      <div class="card"><div class="kicker">Waiting for a person</div>
        ${openH.length ? openH.map((t) => `<div><a data-view="tasks">${esc(t.id)}</a> · p${t.priority} · ${esc(t.title)}</div>`).join("") : `<div class="faint">all human decisions made</div>`}
      </div>
    </div>
  </div>
  <h2>Constraint matrix</h2>
  <div class="table-wrap"><table>
    <tr><th>Suspect</th><th>Score</th><th>Presence (op window)</th><th>Route to the secret</th><th>Withheld-fact echo</th><th>Own account</th><th>Link</th><th>Verdict</th></tr>
    ${a.profiles.slice().sort((x, y) => y.score - x.score).map((p) => `<tr class="clickable" data-view="suspects" data-arg="${esc(p.key)}">
      <td><b>${esc(p.name)}</b>${p.misleading ? ` <span class="chip amber">misleading</span>` : ""}</td>
      <td class="mono">${p.score >= 0 ? "+" : ""}${p.score.toFixed(2)}</td>
      <td class="${p.presence === "on site" ? "cell-red" : p.presence === "excluded" ? "cell-green" : ""}">${esc(p.presence)}</td>
      <td class="${p.knowledge === "route" ? "cell-amber" : ""}">${esc(p.knowledge)}</td>
      <td class="${p.echo === "unexplained" ? "cell-red" : p.echo === "explained" ? "cell-green" : ""}">${esc(p.echo)}</td>
      <td class="${p.statement === "contradicted" ? "cell-red" : p.statement === "consistent" ? "cell-green" : ""}">${esc(p.statement)}</td>
      <td>${esc(p.link)}</td><td><span class="badge ${p.verdict}">${p.verdict}</span></td></tr>`).join("")}
  </table></div>`;
}

/* ------------------------------------------------------------ sweep */
function sweepView(m) {
  const st = S.state;
  const cats = {};
  st.hints.forEach((h) => { (cats[h.category] = cats[h.category] || []).push(h); });
  const issues = st.issues.filter((i) => i.kind === "sweep");
  m.innerHTML = `<h1>Inconsistency sweep</h1>
  <p class="muted">Runs first. Hints are places where a source warns about itself; inconsistencies are two records of the same thing that disagree. Each is fixed with evidence, explained, or handed to a person — before any argument is built.</p>
  <h2>Hints in the sources</h2>
  <div class="grid two">${Object.entries(cats).map(([c, hs]) => `<div class="card"><div class="kicker">${esc(c)} · ${hs.length}</div>
    ${hs.slice(0, 5).map((h) => h.source.startsWith("brief:") ? `<div class="cite"><span class="src faint">${esc(h.source)}</span><span class="q">“${esc(h.quote.slice(0, 160))}”</span></div>` : cite(h)).join("")}</div>`).join("")}</div>
  <h2>Inconsistencies (${issues.length})</h2>
  ${issues.map((i) => `<div class="finding">
    <div class="f-head"><span class="f-title">${esc(i.id)} · ${esc(i.title)}</span>
      <span><span class="badge ${i.severity}">${i.severity}</span> <span class="badge ${i.resolution}">${i.resolution}</span></span></div>
    <div class="f-claim">${esc(i.observation)}</div>
    ${i.fix ? `<div class="f-reason"><b>Fix:</b> ${esc(i.fix)}</div>` : ""}
    ${i.effect ? `<div class="f-reason"><b>Effect:</b> ${esc(i.effect)}</div>` : ""}
    ${reviewLine(i, ["accept", "reject", "escalate"])}
    ${cites(i.evidence)}</div>`).join("")}`;
}

/* ------------------------------------------------------------ suspects */
function findingCard(f) {
  const w = Math.min(100, Math.abs(f.score) * 100);
  return `<div class="finding ${f.status}">
    <div class="f-head"><span class="f-title">${ICON[f.cls]} ${esc(f.title)}</span>
      <span class="f-meta">${esc(f.id)} · ${esc(f.constraint)} · ${esc(f.reliability)} <span class="weight" title="weighted score ${f.score}"><i style="width:${w}%;background:${CLS_COLOR[f.cls]}"></i></span> ${f.score >= 0 ? "+" : ""}${f.score.toFixed(2)}</span></div>
    <div class="f-claim">${esc(f.claim)}</div>
    ${f.reasoning ? `<div class="f-reason">${esc(f.reasoning)}</div>` : ""}
    ${(f.caveats || []).map((c) => `<div class="caveat">⚠ ${esc(c)}</div>`).join("")}
    ${(f.history || []).map((h) => `<div class="caveat">↓ ${esc(h)}</div>`).join("")}
    ${reviewLine(f, ["accept", "reject"])}
    ${cites(f.evidence)}
    <div class="f-meta" style="margin-top:4px">${esc(f.analyzer)} · ${esc(f.provenance)} · stage ${esc(f.stage)}</div>
  </div>`;
}
function reviewLine(x, options) {
  const r = x.review || (S.state.reviews || {})[x.key];
  let badge;
  if (r) {
    const cls = r.decision === "reject" ? "high" : r.decision === "escalate" ? "open" : "fixed";
    badge = `<span class="badge ${cls}">${esc(r.decision)} · ${esc(r.by)}</span> <span class="faint">${esc(r.note || "")}</span>`;
  } else if (x.stage === "bob" || x.stage === "human") {
    badge = `<span class="badge fixed">added by ${esc(x.provenance)}</span>`;
  } else if (x.status === "proposed" || (x.kind && !r)) {
    badge = `<span class="badge open">proposed — awaiting review</span>`;
  } else badge = "";
  const acts = options.map((o) => `<button class="btn small" data-review="${o}" data-id="${esc(x.id)}" title="record your own decision">${o}</button>`).join("");
  return `<div class="opts" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:6px 0">${badge}
    <span style="margin-left:auto;display:flex;gap:6px">${acts}<button class="btn small primary" data-dig="${esc(x.id)}">Dig deeper with Bob</button></span></div>`;
}
function suspectsView(m) {
  const st = S.state, a = st.argue;
  const list = a.profiles.slice().sort((x, y) => y.score - x.score);
  const key = S.suspect || list[0].key;
  const p = a.profiles.find((x) => x.key === key) || list[0];
  const fs = st.findings.filter((f) => f.suspect === p.key).sort((x, y) => Math.abs(y.score) - Math.abs(x.score));
  const byC = {};
  fs.forEach((f) => (byC[f.constraint] = byC[f.constraint] || []).push(f));
  const verdictEntry = (st.verdict?.suspects || []).find((s) => s.name === p.name);
  const triples = fs.filter((f) => f.cls === "WEAKLY_INCRIMINATES" || f.cls === "INCRIMINATES").map((s) => {
    let pw = fs.find((f) => f.explains === s.key);
    if (!pw && s.constraint === "lead") pw = fs.find((f) => f.cls === "EXONERATES" || f.cls === "PROVES_INNOCENCE");
    return { s, pw };
  });
  const info = person(p.key) || {};
  m.innerHTML = `<div class="split">
    <div class="slist">${list.map((x) => `<div class="sitem ${x.key === p.key ? "active" : ""}" data-view="suspects" data-arg="${esc(x.key)}">
      <div class="row"><b>${esc(x.name)}</b><span class="badge ${x.verdict}">${x.verdict}</span></div>
      <div class="row faint"><span>${esc(x.presence)}</span><span class="mono">${x.score >= 0 ? "+" : ""}${x.score.toFixed(2)}</span></div></div>`).join("")}</div>
    <div>
      <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center">
        <h1>${esc(p.name)} <span class="badge ${p.verdict}">${p.verdict}</span></h1>
        <span style="display:flex;gap:6px"><button class="btn small" data-agent-step="suspect:${esc(p.key)}">Bob: work this suspect</button>
        <button class="btn small primary" data-dig="${esc(p.name)}">Dig deeper with Bob</button></span></div>
      ${p.draft ? `<div class="card" style="margin:8px 0"><div class="kicker">Agent's verdict draft (${esc(p.draft.by)})</div>${esc(p.draft.verdict)} — ${esc(p.draft.reasoning)} <span class="faint">${esc((p.draft.cites || []).join(", "))}</span></div>` : ""}
      <div class="muted">${esc(info.title || "")} · handle <code>${esc(info.handle || "—")}</code> · plate ${esc((info.plates || []).join(", ") || "—")} · card ${esc((info.card_last4 || []).join(", ") || "—")}</div>
      <div class="chips" style="margin:10px 0">
        <span class="chip ${p.presence === "on site" ? "red" : p.presence === "excluded" ? "green" : ""}">presence: ${esc(p.presence)}</span>
        <span class="chip ${p.knowledge === "route" ? "amber" : ""}">route to the secret: ${esc(p.knowledge)}</span>
        <span class="chip ${p.echo === "unexplained" ? "red" : p.echo === "explained" ? "green" : ""}">withheld-fact echo: ${esc(p.echo)}</span>
        <span class="chip ${p.statement === "contradicted" ? "red" : p.statement === "consistent" ? "green" : ""}">own account: ${esc(p.statement)}</span>
        <span class="chip">link: ${esc(p.link)}</span>
      </div>
      ${verdictEntry ? `<div class="card"><div class="kicker">In verdict.json</div><div>${esc(verdictEntry.reasoning)}</div>${cites(verdictEntry.evidence.map((e) => ({ source: e.source, quote: e.quote, note: e.claim, status: "verified" })))}</div>` : ""}
      ${triples.length ? `<h2>Suspicion → paperwork → judgement</h2>${triples.map(({ s, pw }) => `<div class="triple">
        <span class="k">Suspicion</span><div>${ICON[s.cls]} ${esc(s.title)} — ${esc(s.claim)}${s.evidence[0] ? cite(s.evidence[0]) : ""}</div>
        <span class="k">Paperwork</span><div>${pw ? `${ICON[pw.cls]} ${esc(pw.title)}${pw.evidence[0] ? cite(pw.evidence[0]) : ""}` : `<span class="faint">none found</span>`}</div>
        <span class="k">Judgement</span><div>${pw ? "Explained — weight lowered, not erased." : s.cls === "INCRIMINATES" ? "<b class='cell-red'>Stands.</b>" : "Stands, low weight."}</div></div>`).join("")}` : ""}
      ${Object.entries(byC).map(([c, list]) => `<h2>${esc(c)}</h2>${list.map(findingCard).join("")}`).join("")}
    </div></div>`;
}

/* ------------------------------------------------------------ timeline */
async function timelineView(m) {
  m.innerHTML = `<h1>Timeline</h1><p class="muted">Per-suspect records around the operation window, on the swept (clock-corrected) view. Click any mark to open its source line.</p><div class="empty">loading…</div>`;
  if (!S.timeline) S.timeline = await api("/api/timeline?hours=14");
  const T = S.timeline;
  const t0 = +new Date(T.from), t1 = +new Date(T.to);
  const W = 1100, left = 150, right = 20, rowH = 44, top = 34;
  const H = top + T.lanes.length * rowH + 20;
  const x = (iso) => left + ((+new Date(iso) - t0) / (t1 - t0)) * (W - left - right);
  let ticks = "";
  for (let t = Math.ceil(t0 / 36e5) * 36e5; t <= t1; t += 2 * 36e5) {
    const d = new Date(t);
    ticks += `<line x1="${x(d)}" x2="${x(d)}" y1="${top - 6}" y2="${H - 14}" stroke="var(--line)"/><text x="${x(d)}" y="${top - 12}" font-size="10" text-anchor="middle">${d.toLocaleString("de-CH", { weekday: "short", hour: "2-digit", minute: "2-digit" })}</text>`;
  }
  const marks = T.lanes.map((ln, i) => {
    const y = top + i * rowH + rowH / 2;
    const ms = ln.events.map((e) => {
      const X = x(e.t);
      const tip = esc(`${fmt(e.t)} · ${e.kind} · ${e.text}${e.fix ? " · " + e.fix + " (raw " + e.raw + ")" : ""}${e.degraded ? " · degraded read" : ""}`);
      const common = `data-src="${esc(e.source)}" data-tip="${tip}" style="cursor:pointer"`;
      if (e.kind === "card") { const away = e.city && e.city !== T.site; return `<circle cx="${X}" cy="${y - 8}" r="5" fill="${away ? "var(--green)" : "var(--ink-2)"}" ${common}/>`; }
      if (e.kind === "garage") { const up = (e.direction || "").startsWith("ein") || e.direction === "entry"; return `<path d="M${X - 5},${y + (up ? 4 : -2)} L${X + 5},${y + (up ? 4 : -2)} L${X},${y + (up ? -4 : 6)} Z" fill="${up ? "var(--red)" : "var(--accent)"}" ${e.degraded ? 'stroke="var(--amber)" stroke-width="2"' : ""} ${common}/>`; }
      if (e.kind === "slack") return `<rect x="${X - 4}" y="${y + 6}" width="8" height="8" rx="2" fill="var(--amber)" ${common}/>`;
      if (e.kind === "calendar") { const X2 = e.end ? x(e.end) : X + 4; return `<rect x="${X}" y="${y + 16}" width="${Math.max(3, X2 - X)}" height="4" fill="var(--slate)" ${common}/>`; }
      return "";
    }).join("");
    return `<text x="8" y="${y + 4}" font-size="12">${esc(ln.name)}</text><line x1="${left}" x2="${W - right}" y1="${y + 22}" y2="${y + 22}" stroke="var(--line)"/>${ms}`;
  }).join("");
  m.innerHTML = `<h1>Timeline</h1><p class="muted">Per-suspect records around the operation window (shaded), on the swept view: barrier times are clock-corrected; hover shows the raw value. Click any mark to open its source line.</p>
  <div class="tl-legend"><span>● card (green = away from ${esc(T.site)})</span><span style="color:var(--red)">▲ garage entry</span><span style="color:var(--accent)">▼ garage exit</span><span style="color:var(--amber)">■ chat</span><span style="color:var(--slate)">▬ calendar</span><span>▒ blackout / operation window</span></div>
  <div class="tl-wrap"><svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
    <rect x="${x(T.blackout[0])}" y="${top - 6}" width="${x(T.blackout[1]) - x(T.blackout[0])}" height="${H - top - 8}" fill="var(--blackout)"/>
    <rect x="${x(T.op[0])}" y="${top - 6}" width="${x(T.op[1]) - x(T.op[0])}" height="${H - top - 8}" fill="var(--op)"/>
    ${ticks}${marks}</svg></div>
  <h2>Witness sightings resolved in the sweep</h2>
  ${(T.sightings || []).map((s) => `<div class="cite"><a class="src" data-src="${esc(s.source)}">${esc(s.source)}</a><span class="q">${fmt(s.t)} — car ${esc(s.plate)} (${esc(s.holder)}), matched on ${esc(s.why.join(", "))}; barrier log: ${esc(s.state)}${s.ocr ? " · OCR" : ""}</span></div>`).join("") || `<div class="faint">none</div>`}`;
  const tip = $("#tooltip");
  m.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mousemove", (ev) => { tip.textContent = el.dataset.tip; tip.style.left = ev.clientX + 12 + "px"; tip.style.top = ev.clientY + 12 + "px"; tip.style.opacity = 1; });
    el.addEventListener("mouseleave", () => (tip.style.opacity = 0));
  });
}

/* ------------------------------------------------------------ tasks */
function tasksView(m) {
  const st = S.state;
  const human = st.tasks.filter((t) => t.kind === "human"), agent = st.tasks.filter((t) => t.kind === "agent");
  const reads = (t) => t.read.map((r) => cite({ source: r.source, quote: r.quote, note: r.note })).join("");
  m.innerHTML = `<h1>Tasks</h1>
  <p class="muted">Human tasks are judgement calls — your decision is saved and the pipeline re-runs with it. Agent tasks are mechanical and can be handed to Bob; anything Bob adds is verified against the bundle before it counts. Every pointer opens the source.</p>
  <div class="grid two">
  <div><h2>Human (${human.filter((t) => t.status === "open").length} open)</h2>
  ${human.map((t) => `<div class="task ${t.status}" data-key="${esc(t.key)}">
    <div class="f-head"><b>${esc(t.id)} · ${esc(t.title)}</b><span class="badge ${t.status === "open" ? "open" : "fixed"}">${t.status === "open" ? "p" + t.priority : "✓ " + esc(t.resolution.decision)}</span></div>
    <div class="f-reason"><b>Why a person:</b> ${esc(t.why)}</div>
    <div class="f-claim"><b>${esc(t.question)}</b></div>
    ${reads(t)}
    ${t.status === "open" ? `<textarea placeholder="note (optional)"></textarea>
      ${t.topic === "calibration" ? `<input type="number" step="0.01" min="0.05" max="0.95" placeholder="value, e.g. 0.85" class="val">` : ""}
      ${t.topic === "ocr" ? `<input type="text" placeholder="corrected text (if 'correct')" class="txt" style="width:100%;margin-top:6px">` : ""}
      <div class="opts">${t.options.map((o) => `<button class="btn small" data-resolve="${esc(o)}" title="${esc(t.effect[o] || "")}">${esc(o)}</button>`).join("")}</div>`
    : `<div class="f-meta">${esc(t.resolution.by)} · ${esc(t.resolution.at)} ${t.resolution.note ? "· " + esc(t.resolution.note) : ""} <button class="btn small" data-reopen>reopen</button></div>`}
  </div>`).join("")}</div>
  <div><h2>Agent / Bob (${agent.filter((t) => t.status === "open").length} open)</h2>
  <div class="card" style="margin-bottom:10px;font-size:13px">Bob CLI: ${st.bob.installed ? "installed " + esc(st.bob.version) : "not installed"} · headless: ${st.bob.headless ? "yes" : "no — " + esc(st.bob.why_not_headless)}</div>
  ${agent.map((t) => `<div class="task" data-key="${esc(t.key)}">
    <div class="f-head"><b>${esc(t.id)} · ${esc(t.title)}</b><span class="badge ${t.priority === 1 ? "high" : "low"}">p${t.priority}</span></div>
    <div class="f-reason">${esc(t.why)}</div><div class="f-claim">${esc(t.question)}</div>${reads(t)}
    <div class="opts"><button class="btn small" data-bob>Send to Bob</button></div><div class="bob-out"></div></div>`).join("")}</div></div>`;
  m.querySelectorAll("[data-resolve]").forEach((b) => b.onclick = async () => {
    const card = b.closest(".task");
    const body = { decision: b.dataset.resolve, note: card.querySelector("textarea")?.value || "", value: card.querySelector(".val")?.value, text: card.querySelector(".txt")?.value };
    await api(`/api/task/${card.dataset.key}/resolve`, { body });
    card.style.opacity = .5; startPolling();
  });
  m.querySelectorAll("[data-reopen]").forEach((b) => b.onclick = async () => { await api(`/api/task/${b.closest(".task").dataset.key}/reopen`, { body: {} }); startPolling(); });
  m.querySelectorAll("[data-bob]").forEach((b) => b.onclick = async () => {
    const card = b.closest(".task"), out = card.querySelector(".bob-out");
    out.innerHTML = `<div class="faint">asking Bob…</div>`;
    const r = await api(`/api/task/${card.dataset.key}/bob`, { body: {} });
    if (r.dispatched) { out.innerHTML = `<div class="faint">Bob is working — watch the log; the pipeline re-runs when Bob finishes.</div>`; startPolling(); }
    else out.innerHTML = `<div class="caveat">${esc(r.error || "")}</div><div class="f-meta">Run <code>bob chat</code> in the repo, pick the <b>Investigator</b> mode and paste:</div><pre class="prompt">${esc(r.prompt || "")}</pre><button class="btn small" data-copy>Copy prompt</button>`;
    const c = out.querySelector("[data-copy]"); if (c) c.onclick = () => navigator.clipboard.writeText(r.prompt);
  });
}

/* ------------------------------------------------------------ docs */
function mdToHtml(md) {
  const lines = md.split("\n"); let html = "", i = 0;
  const inline = (s) => esc(s)
    .replace(/`([^`]+?\.(?:md|txt|json|csv|mbox|ics|pdf|xlsx|jpg)(?::\d+(?:-\d+)?)?)`/g, (m0, src) => `<a class="src mono" data-src="${src}">${src}</a>`)
    .replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\*([^*]+)\*/g, "<i>$1</i>");
  while (i < lines.length) {
    const l = lines[i];
    if (l.startsWith("```")) { let j = i + 1, buf = []; while (j < lines.length && !lines[j].startsWith("```")) buf.push(lines[j++]); html += `<pre>${esc(buf.join("\n"))}</pre>`; i = j + 1; continue; }
    if (/^#{1,4} /.test(l)) { const n = l.match(/^#+/)[0].length; html += `<h${n}>${inline(l.slice(n + 1))}</h${n}>`; i++; continue; }
    if (l.startsWith("|")) { const rows = []; while (i < lines.length && lines[i].startsWith("|")) rows.push(lines[i++]);
      const cells = (r) => r.replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => c.replace(/\\\|/g, "|").trim());
      html += "<table>" + rows.filter((r) => !/^\|[\s\-:|]+\|$/.test(r)).map((r, k) => "<tr>" + cells(r).map((c) => `<${k ? "td" : "th"}>${inline(c).replace(/&lt;br&gt;/g, "<br>")}</${k ? "td" : "th"}>`).join("") + "</tr>").join("") + "</table>"; continue; }
    if (l.startsWith("> ")) { html += `<blockquote>${inline(l.slice(2))}</blockquote>`; i++; continue; }
    if (/^\s*- /.test(l)) { html += "<ul>"; while (i < lines.length && /^\s*- /.test(lines[i])) html += `<li>${inline(lines[i++].replace(/^\s*- /, ""))}</li>`; html += "</ul>"; continue; }
    if (l.trim()) html += `<p>${inline(l)}</p>`;
    i++;
  }
  return html;
}
async function docsView(m) {
  const docs = S.state.docs;
  const name = S.doc || docs[0];
  m.innerHTML = `<h1>Context documents</h1><p class="muted">Regenerated on every run — the automated counterpart of the manual Context folder. Citations are links.</p>
    <div class="docs-list">${docs.map((d) => `<a class="btn small ${d === name ? "primary" : ""}" data-view="docs" data-arg="${esc(d)}">${esc(d.replace(/^\d+_/, "").replace(".md", ""))}</a>`).join("")}</div><div class="md card">loading…</div>`;
  const text = await api(`/api/doc?name=${encodeURIComponent(name)}`);
  $(".md", m).innerHTML = mdToHtml(text);
}

/* ------------------------------------------------------------ verdict */
function verdictView(m) {
  const st = S.state, v = st.verdict, ver = st.verification || { rows: [] };
  const status = {}; ver.rows.forEach((r) => (status[r.source + "|" + r.quote] = r.status));
  m.innerHTML = `<h1>verdict.json</h1>
  <p class="muted">The investigator's own verdict, built only from quotes found at their source in the bundle as received; re-verified after writing: <b>${ver.total}</b> quotes → ${esc(JSON.stringify(ver.counts))}. File: <code>investigation/output/verdict.json</code> · export with <code>src/investigate export</code></p>
  <div class="card" style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center"><span><b>${esc(v.culprit)}</b> · confidence <b>${v.confidence}</b> · team <code>${esc(v.team)}</code></span><a class="btn primary small" href="/api/verdict.json" download="verdict.json">Download verdict.json</a></div>
  <h2>Every verdict file in the repo, checked against the bundle</h2><div id="vfiles" class="faint">checking…</div>
  <h2>The investigator's verdict</h2>
  ${v.suspects.map((s) => `<div class="finding"><div class="f-head"><span class="f-title">${esc(s.name)}</span><span class="badge ${s.verdict}">${s.verdict}</span></div>
    <div class="f-claim">${esc(s.reasoning)}</div>
    ${s.evidence.map((e) => cite({ source: e.source, quote: e.quote, note: e.claim, status: status[e.source + "|" + e.quote] })).join("")}</div>`).join("")}
  <h2>Raw</h2><pre class="prompt">${esc(JSON.stringify(v, null, 2))}</pre>`;
  api("/api/verdict-files").then((r) => {
    $("#vfiles").innerHTML = r.files.map((f, k) => f.error ? `<div class="caveat">${esc(f.path)}: ${esc(f.error)}</div>` : `
      <div class="finding"><div class="f-head"><span class="f-title"><code>${esc(f.path)}</code> — ${esc(f.culprit)} · ${f.confidence}</span>
        <span class="badge ${f.report.all_verified ? "fixed" : "high"}">${f.report.all_verified ? "✓ all " + f.report.total + " quotes verified" : esc(JSON.stringify(f.report.counts))}</span></div>
        <div class="f-meta">${Object.entries(f.verdicts).map(([n, x]) => `${esc(n)}: ${esc(x)}`).join(" · ")}</div>
        <details style="margin-top:6px"><summary class="faint">show every citation</summary>
        ${f.report.rows.map((row) => cite({ source: row.suggestion && row.status !== "verified" ? row.source : row.source, quote: row.quote, note: row.suspect + (row.suggestion ? " → " + row.suggestion : ""), status: row.status })).join("")}</details></div>`).join("");
  }).catch((e) => ($("#vfiles").textContent = e.message));
}

/* ------------------------------------------------------------ search */
function searchView(m) {
  m.innerHTML = `<h1>Search the bundle</h1><p class="muted">Regex over every line, page, row and OCR text. Each hit is a citation you can open and check.</p>
    <div class="search-row"><input id="q" placeholder="e.g. scratch-02 | green volvo | owner of record" autofocus>
    <select id="in"><option value="">all sources</option>${[...new Set(S.state.inventory.map((r) => r.path.includes("/") ? r.path.split("/")[0] + "/" : r.path))].map((p) => `<option>${esc(p)}</option>`).join("")}</select>
    <button class="btn primary" id="go">Search</button></div><div id="hits"></div>`;
  const run = async () => {
    const q = $("#q").value.trim(); if (!q) return;
    try {
      const r = await api(`/api/search?q=${encodeURIComponent(q)}&in=${encodeURIComponent($("#in").value)}`);
      $("#hits").innerHTML = r.hits.length ? r.hits.map((h) => `<div class="search-hit"><a class="src mono" data-src="${esc(h.source)}">${esc(h.source)}</a><span>${esc(h.text.trim().slice(0, 260))}${h.ocr ? ' <span class="st ocr">OCR</span>' : ""} <a class="faint" href="${viewerUrl(h.source)}" target="_blank">full doc ↗</a></span></div>`).join("") : `<div class="empty">no hits</div>`;
    } catch (e) { $("#hits").innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };
  $("#go").onclick = run; $("#q").onkeydown = (e) => e.key === "Enter" && run();
}

/* ------------------------------------------------------------ state & polling */
async function load() {
  S.state = await api("/api/state");
  S.timeline = null;
  $("#bundle-label").textContent = S.state.bundle ? "bundle: " + S.state.bundle.replace(/^.*\/(?=[^/]+\/[^/]+$)/, "…/") : "";
  const b = S.state.bob;
  const bp = $("#bob-pill");
  bp.textContent = b.installed ? `Bob ${b.version || ""} · ${b.headless ? "headless" : "interactive"}` : "Bob not installed";
  bp.className = "pill " + (b.installed ? "ok" : "");
  bp.title = b.why_not_headless || "bob run available";
  const open = (S.state.tasks || []).filter((t) => t.status === "open");
  $("#n-tasks").textContent = open.length ? open.length : "";
  $("#n-sweep").textContent = (S.state.issues || []).filter((i) => i.kind === "sweep").length || "";
  if ($("#n-sec") && S.state.security) $("#n-sec").textContent = S.state.security.open || "";
  if ($("#n-risks") && S.state.posture) $("#n-risks").textContent = S.state.posture.open || "";
  const pb = S.state.playbook || [];
  $("#n-agent").textContent = S.state.agent?.busy ? "working…" : pb.length ? `${pb.filter((s) => s.complete).length}/${pb.length}` : "";
  if (S.state.agent?.busy) { S.agent.run = S.state.agent.run; pollAgent(); }
  setRunPill(S.state.running, S.state.error);
  render();
}
function setRunPill(running, error) {
  const p = $("#run-pill");
  p.textContent = running ? "running…" : error ? "error" : "up to date";
  p.className = "pill " + (running ? "run" : error ? "err" : "ok");
  $("#run-btn").disabled = !!running;
}
let polling = null;
function startPolling() {
  if (polling) return;
  polling = setInterval(async () => {
    const r = await api(`/api/log?since=${S.logSince}`);
    S.logSince = r.next;
    if (r.lines.length) { const el = $("#log"); el.textContent += r.lines.join("\n") + "\n"; el.scrollTop = el.scrollHeight; }
    setRunPill(r.running, r.error);
    if (!r.running) { clearInterval(polling); polling = null; await load(); }
  }, 700);
}
$("#run-btn").onclick = async () => { await api("/api/run", { body: {} }); startPolling(); };

function buildChrome() {
  $("#nav-links").innerHTML = NAV[AGENT].map(([v, label, cnt]) =>
    `<a data-view="${v}">${label}${cnt ? ` <span class="count" id="${cnt}"></span>` : ""}</a>`).join("");
  $("#legend").innerHTML = AGENT === "guard"
    ? `<span class="sev critical">critical</span><span class="sev high">high</span><span class="sev medium">medium</span><span class="sev low">low</span>`
    : `<span>🔴 incriminates</span><span>🟡 weakly</span><span>🟢 exonerates</span><span>⚪ proves innocence</span>`;
  $("#brand-title").textContent = AGENT === "guard" ? "Bob Security Guard" : "Bob Investigator";
  document.title = AGENT === "guard" ? "Bob Security Guard" : "Bob Investigator";
  $("#agent-switch").innerHTML = `<a href="/?agent=investigator" class="${AGENT === "investigator" ? "on" : ""}">Investigator</a>` +
    `<a href="/?agent=guard" class="${AGENT === "guard" ? "on" : ""}">Security Guard</a>`;
}
function fromHash() {
  const [v, arg] = (location.hash.slice(1) || "overview").split(":");
  S.view = v; if (arg) { if (v === "suspects") S.suspect = arg; if (v === "docs") S.doc = arg; }
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === S.view));
}
window.addEventListener("hashchange", () => {
  const cur = S.view + (S.view === "suspects" && S.suspect ? ":" + S.suspect : S.view === "docs" && S.doc ? ":" + S.doc : "");
  if (location.hash.slice(1) !== cur) { fromHash(); render(); }
});
(async function init() {
  buildChrome();
  fromHash();
  await load();
  startPolling();
})();


/* ------------------------------------------------------------ agent workspace */
S.agent = { run: null, since: 0, events: [], timer: null, runs: [] };

async function agentRun(steps) {
  const depth = $("#agent-depth")?.value || "normal";
  const redo = $("#agent-redo")?.checked || false;
  const r = await api("/api/agent/run", { body: { steps, depth, redo } });
  if (!r.started) { alert(r.error || "could not start"); return; }
  S.agent = { ...S.agent, run: r.run, since: 0, events: [] };
  go("agent"); pollAgent();
}
async function agentDig(target) {
  const question = prompt(`What should Bob find out about ${target}? (leave empty for "is this right, and what else does the bundle say?")`, "");
  if (question === null) return;
  const r = await api("/api/agent/dig", { body: { target, question: question || null } });
  if (!r.started) { alert(r.error || "could not start"); return; }
  S.agent = { ...S.agent, run: r.run, since: 0, events: [] };
  go("agent"); pollAgent();
}
function pollAgent() {
  if (S.agent.timer) return;
  S.agent.timer = setInterval(async () => {
    try {
      const r = await api(`/api/agent/events?run=${encodeURIComponent(S.agent.run || "")}&since=${S.agent.since}`);
      if (!S.agent.run) S.agent.run = r.run;
      if (r.events.length) { S.agent.events.push(...r.events); S.agent.since = r.next; if (S.view === "agent") renderTrace(); }
      $("#agent-status") && ($("#agent-status").innerHTML = agentStatusHtml(r.busy, r.error));
      if (!r.busy) { clearInterval(S.agent.timer); S.agent.timer = null; await load(); startPolling(); }
    } catch (e) { /* keep polling */ }
  }, 1500);
}
function agentStatusHtml(busy, error) {
  return busy ? `<span class="pill run">Bob is working · run ${esc(S.agent.run || "")}</span> <button class="btn small" id="agent-stop">Stop</button>`
    : error ? `<span class="pill err">${esc(error)}</span>` : `<span class="pill ok">idle</span>`;
}
const CITE_RX = /([\w./-]+\.(?:md|txt|json|csv|mbox|ics|pdf|xlsx|jpg)(?::\d+(?:-\d+)?)?)/g;
function linkCites(text) { return esc(text).replace(CITE_RX, (m) => `<a class="src mono" data-src="${m}">${m}</a>`); }
function renderTrace() {
  const el = $("#trace"); if (!el) return;
  const stick = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  el.innerHTML = S.agent.events.map((e) => {
    const step = e.step ? `<span class="chip">${esc(e.step)}</span>` : "";
    if (e.type === "prompt") return `<details class="ev ev-prompt"><summary>${step} orchestrator → Bob</summary><pre class="prompt">${esc(e.text)}</pre></details>`;
    if (e.type === "message") return `<div class="ev ev-msg">${step}<b>Bob</b><div class="md">${mdToHtml(e.text)}</div></div>`;
    if (e.type === "thought") return `<details class="ev"><summary class="faint">${step} Bob is thinking…</summary><pre class="prompt">${esc(e.text)}</pre></details>`;
    if (e.type === "tool_call") return `<div class="ev ev-cmd">${step}<code>$ ${esc(e.command || e.title || "")}</code></div>`;
    if (e.type === "tool_result") return `<details class="ev ev-out"><summary class="faint">output${e.status ? " · " + esc(e.status) : ""} (${(e.output || "").split("\n").length} lines)</summary><pre class="prompt">${linkCites(e.output || "")}</pre></details>`;
    if (e.type === "permission") return e.allowed ? "" : `<div class="ev cell-red">${step} ✗ denied: <code>${esc(e.command || e.title || "")}</code> — ${esc(e.why || "")}</div>`;
    if (e.type === "system") return `<div class="ev ev-sys">${step} ${esc(e.text)}${(e.missing || []).length ? `<ul>${e.missing.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`;
    if (e.type === "plan") return `<div class="ev ev-sys">${step} plan: ${(e.entries || []).map((x) => esc(x.content || "")).join(" · ")}</div>`;
    if (e.type === "stop") return `<div class="ev faint">${step} turn ended (${esc(e.reason)})</div>`;
    return "";
  }).join("") || `<div class="empty">No agent run yet. Start the playbook or dig into something.</div>`;
  if (stick) el.scrollTop = el.scrollHeight;
}
async function agentView(m) {
  const st = S.state, pb = st.playbook || [], ag = st.agent || {};
  const bl = st.baseline || {}, a = st.argue || {};
  if (!S.agent.runs.length) { try { S.agent.runs = (await api("/api/agent/runs")).runs; } catch (e) {} }
  if (!S.agent.run && (ag.run || S.agent.runs[0])) S.agent.run = ag.run || S.agent.runs[0].run;
  m.innerHTML = `<h1>Agent workspace</h1>
  <p class="muted">Tools propose, Bob decides. Bob works each playbook step through the CLI over ACP (your Bob login) in the <b>${AGENT === "guard" ? "securityguard" : "investigator"}</b> mode: he reviews every proposal with a note, digs deeper, adds ${AGENT === "guard" ? "risks the scanner missed" : "findings"} (quotes verified) and ${AGENT === "guard" ? "makes the remediations specific" : "drafts the verdict"}. Only <code>${AGENT === "guard" ? "src/guard" : "src/investigate"} …</code> commands and edits in <code>investigation/notes/</code> are allowed; everything else is denied and shown here.</p>
  <div class="card" style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between">
    <span style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <label>Depth <select id="agent-depth"><option>quick</option><option selected>normal</option><option>deep</option></select></label>
      <label class="faint"><input type="checkbox" id="agent-redo"> redo finished steps</label>
      <button class="btn primary" data-agent-step="">Run the whole playbook</button>
      <label>Mode <select id="agent-mode"><option ${st.mode === "agent" ? "selected" : ""}>agent</option><option ${st.mode === "autopilot" ? "selected" : ""}>autopilot</option></select></label>
    </span>
    <span id="agent-status">${agentStatusHtml(ag.busy, ag.error)}</span>
  </div>
  <div class="grid two" style="margin-top:12px">
    ${AGENT === "guard" ? `<div class="card"><div class="kicker">Posture so far</div>
      <div><b>${st.posture.open}</b> open risks · confirmed by Bob: <b>${st.posture.confirmed_by_agent}</b> of ${st.posture.risks}</div>
      <div class="faint">${Object.entries(st.posture.by_severity).map(([k, v]) => `${k} ${v}`).join(" · ")}</div></div>`
    : `<div class="card"><div class="kicker">Verdict so far</div>
      <div><b>Agent:</b> ${esc(a.culprit_name || "—")} (${a.confidence}) <span class="faint">${esc(a.basis || "")}</span></div>
      <div><b>Tools only:</b> ${esc(bl.culprit_name || "—")} (${bl.confidence ?? "—"})</div>
      ${a.agent_confidence ? `<div class="faint">Bob proposes confidence ${a.agent_confidence.value}: ${esc(a.agent_confidence.why)}</div>` : ""}</div>`}
    <div class="card"><div class="kicker">Runs</div>
      <select id="agent-runs">${S.agent.runs.map((r) => `<option value="${esc(r.run)}" ${r.run === S.agent.run ? "selected" : ""}>${esc(r.run)} · ${r.events} events · ${esc(r.steps.join(", ").slice(0, 80))}</option>`).join("") || "<option>none yet</option>"}</select></div>
  </div>
  <div style="display:grid;grid-template-columns:minmax(260px,340px) 1fr;gap:14px;margin-top:14px" class="agent-grid">
    <div class="slist">${pb.map((s) => `<div class="sitem">
      <div class="row"><b>${s.complete ? "✓" : s.status === "in_progress" ? "▶" : s.status === "incomplete" ? "…" : "○"} ${esc(s.title)}</b>
        <button class="btn small" data-agent-step="${esc(s.id)}" title="Bob works this step">Run</button></div>
      <div class="faint" style="font-size:12px">${esc(s.status)} · ${s.missing.length} open${s.summary ? " · " + esc(s.summary) : ""}</div></div>`).join("")}</div>
    <div class="card" style="padding:0"><div id="trace" class="trace"></div></div>
  </div>`;
  $("#agent-mode").onchange = async (e) => { await api("/api/mode", { body: { mode: e.target.value } }); startPolling(); };
  $("#agent-runs").onchange = (e) => { S.agent = { ...S.agent, run: e.target.value, since: 0, events: [] }; clearInterval(S.agent.timer); S.agent.timer = null; pollAgent(); };
  renderTrace();
  if (S.agent.run && (!S.agent.events.length || ag.busy)) pollAgent();
}


/* ------------------------------------------------------------ security (shared) */
function riskCard(f, actions = true) {
  const m = f.meta || {};
  return `<div class="finding ${f.status}">
    <div class="f-head"><span class="f-title"><span class="sev ${m.severity}">${esc(m.severity)}</span> <span class="state ${m.state}">${esc(m.state)}</span> ${esc(f.title)}</span>
      <span class="f-meta">${esc(f.id)} · ${esc(m.category)}${m.incident ? ' · <b class="cell-red">exposed by the incident</b>' : ""}</span></div>
    <div class="f-claim">${esc(f.claim)}</div>
    ${f.reasoning ? `<div class="f-reason"><b>Why it matters:</b> ${esc(f.reasoning)}</div>` : ""}
    ${(f.history || []).map((h) => `<div class="caveat">↳ ${esc(h)}</div>`).join("")}
    ${actions ? reviewLine(f, ["accept", "reject"]) : `<div class="opts" style="margin:6px 0">${f.review ? `<span class="badge ${f.review.decision === "reject" ? "high" : "fixed"}">${esc(f.review.decision)} · ${esc(f.review.by)}</span> ` : ""}<a class="btn small" href="/?agent=guard#risks">Triage in the Security Guard →</a></div>`}
    ${cites(f.evidence)}
  </div>`;
}
function sevBar(bySev) {
  const col = { critical: "var(--red)", high: "#e8743b", medium: "var(--amber)", low: "var(--slate)" };
  const tot = Object.values(bySev).reduce((a, b) => a + b, 0) || 1;
  return `<div class="sevbar">${Object.entries(bySev).map(([k, v]) => `<span title="${k} ${v}" style="width:${v / tot * 100}%;background:${col[k]}"></span>`).join("")}</div>`;
}
function guardOverview(m) {
  const st = S.state, p = st.posture;
  const risks = st.findings.filter((f) => (f.meta || {}).kind === "risk" && f.status !== "withdrawn");
  const open = risks.filter((f) => ["open", "check"].includes(f.meta.state)).sort((a, b) => SEV_ORDER[a.meta.severity] - SEV_ORDER[b.meta.severity]);
  const rcs = st.issues.filter((i) => i.kind === "rootcause");
  const rems = st.issues.filter((i) => i.kind === "remediation").sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]);
  const pb = st.playbook || [], rs = st.reviews_summary || {};
  m.innerHTML = `
  <div class="card" style="margin-bottom:14px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between">
    <div><div class="kicker">Proactive scan · no suspects · as of ${esc((p.as_of || "").slice(0, 10))} · mode ${esc(st.mode)}</div>
      <div style="margin-top:4px">Playbook ${pb.filter((s) => s.complete).length}/${pb.length} steps · risks confirmed by Bob: <b>${p.confirmed_by_agent}</b> of ${p.risks} · <b>${rs.proposed || 0} awaiting review</b></div></div>
    <div style="display:flex;gap:8px"><a class="btn" data-view="agent">Open agent workspace</a><button class="btn primary" data-agent-step="">Let Bob run the security playbook</button></div>
  </div>
  <div class="hero">
    <div class="card">
      <div class="kicker">Open risks</div>
      <div class="name">${p.open} <span class="faint" style="font-size:16px">of ${p.risks}</span></div>
      ${sevBar(p.by_severity)}
      <div class="chips">${Object.entries(p.by_severity).map(([k, v]) => `<span class="sev ${k}">${k} ${v}</span>`).join(" ")}</div>
      <h3>Most urgent — every claim links to its source</h3>
      ${open.slice(0, 5).map(riskCard).join("")}
    </div>
    <div class="grid">
      <div class="card"><div class="kicker">Exposed by the incident under investigation</div>
        ${p.incident_linked.length ? risks.filter((f) => f.meta.incident).map((f) => `<div style="margin-top:6px"><span class="sev ${f.meta.severity}">${f.meta.severity}</span> <a data-view="risks">${esc(f.id)}</a> ${esc(f.title)}</div>`).join("") : `<div class="faint">no investigation linked yet — run the Investigator first</div>`}
        <div style="margin-top:8px"><a href="/?agent=investigator#security">Open in the Investigator →</a></div></div>
      <div class="card"><div class="kicker">Why these exist — process misdesign</div>
        ${rcs.map((i) => `<div style="margin-top:6px"><span class="sev ${i.severity}">${i.severity}</span> <a data-view="rootcauses">${esc(i.id)}</a> ${esc(i.title)} <span class="faint">(${i.affects.length} risk${i.affects.length === 1 ? "" : "s"})</span></div>`).join("")}</div>
      <div class="card"><div class="kicker">Do first</div>
        ${rems.slice(0, 3).map((i) => `<div style="margin-top:6px"><a data-view="remediation">${esc(i.id)}</a> ${esc(i.title.replace("Remediate: ", ""))}<div class="faint">${esc(i.fix)}</div></div>`).join("")}</div>
    </div>
  </div>`;
}
function risksView(m) {
  const st = S.state, F = S.riskFilter;
  let risks = st.findings.filter((f) => (f.meta || {}).kind === "risk" && f.status !== "withdrawn");
  const cats = [...new Set(risks.map((f) => f.meta.category))].sort();
  risks = risks.filter((f) => (!F.sev || f.meta.severity === F.sev) && (!F.state || f.meta.state === F.state) &&
    (!F.cat || f.meta.category === F.cat) && (!F.inc || f.meta.incident) && (!F.review || (F.review === "proposed" ? f.status === "proposed" : f.status !== "proposed")));
  risks.sort((a, b) => SEV_ORDER[a.meta.severity] - SEV_ORDER[b.meta.severity] || a.id.localeCompare(b.id));
  const sel = (k, opts, label) => `<label>${label} <select data-f="${k}"><option value="">all</option>${opts.map((o) => `<option ${F[k] === o ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
  m.innerHTML = `<h1>Risk register</h1><p class="muted">Every risk the scanner proposed or Bob added, with severity, whether it is still open, and the exact lines behind it. Also as <code>security/output/risk_register.csv</code>.</p>
  <div class="filters">${sel("sev", ["critical", "high", "medium", "low"], "Severity")}${sel("state", ["open", "check", "addressed"], "State")}${sel("cat", cats, "Category")}${sel("review", ["proposed", "reviewed"], "Review")}
    <label><input type="checkbox" data-f="inc" ${F.inc ? "checked" : ""}> exposed by the incident</label><span class="faint">${risks.length} shown</span></div>
  ${risks.map(riskCard).join("") || `<div class="empty">nothing matches</div>`}`;
  m.querySelectorAll("[data-f]").forEach((el) => el.onchange = () => { S.riskFilter[el.dataset.f] = el.type === "checkbox" ? el.checked : el.value; risksView(m); });
}
function rootcausesView(m) {
  const st = S.state;
  const risks = Object.fromEntries(st.findings.map((f) => [f.key, f]));
  m.innerHTML = `<h1>Root causes — how the process lets this happen</h1><p class="muted">A risk is a symptom; the root cause is the process design that keeps producing it. Each is proposed from the data's own evidence of the failure (pressure, deferral, missing owner, default-open settings, re-filed tickets) and needs Bob's review.</p>
  ${st.issues.filter((i) => i.kind === "rootcause").map((i) => `<div class="finding">
    <div class="f-head"><span class="f-title"><span class="sev ${i.severity}">${i.severity}</span> ${esc(i.id)} · ${esc(i.title)}</span></div>
    <div class="f-claim">${esc(i.observation)}</div>
    <div class="f-reason"><b>Process fix:</b> ${esc(i.fix)}</div>
    <div class="f-meta">Produces: ${i.affects.map((k) => risks[k] ? `<a data-view="risks">${esc(risks[k].id)}</a>` : "").join(" ")}</div>
    ${reviewLine(i, ["accept", "reject"])}
    ${cites(i.evidence)}</div>`).join("")}`;
}
function remediationView(m) {
  const st = S.state;
  const risks = Object.fromEntries(st.findings.map((f) => [f.key, f]));
  const rems = st.issues.filter((i) => i.kind === "remediation").sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]);
  const part = (obs, key, next) => { const a = obs.indexOf(key + ":"); if (a < 0) return ""; const b = next ? obs.indexOf(next + ":") : -1; return obs.slice(a + key.length + 1, b > a ? b : undefined).trim(); };
  m.innerHTML = `<h1>Remediation plan</h1><p class="muted">Standard practice mapped onto this organisation's open risks, ordered by severity. Bob makes each plan specific (accounts, rooms, tickets, owners); an accountable person approves it in <a data-view="tasks">Tasks</a>.</p>
  ${rems.map((i, n) => {
    const appr = st.tasks.find((t) => t.subject === i.key);
    return `<div class="finding">
    <div class="f-head"><span class="f-title">${n + 1}. <span class="sev ${i.severity}">${i.severity}</span> ${esc(i.id)} · ${esc(i.title.replace("Remediate: ", ""))}</span>
      <span class="f-meta">${appr ? `approval ${esc(appr.id)}: ${appr.resolution ? esc(appr.resolution.decision) : "open"}` : ""}</span></div>
    <div class="plan"><b>Now</b><span>${esc(part(i.observation, "NOW", "CONTROL"))}</span>
      <b>Control</b><span>${esc(part(i.observation, "CONTROL", "PROCESS"))}</span>
      <b>Process</b><span>${esc(part(i.observation, "PROCESS", "OWNER"))}</span>
      <b>Owner</b><span>${esc(part(i.observation, "OWNER", "Applies to").replace(/\.$/, ""))}</span>
      <b>Verify</b><span>${esc(i.effect.replace(/^Verify:\s*/, ""))}</span></div>
    <div class="f-meta">Risks: ${i.affects.map((k) => risks[k] ? `<a data-view="risks">${esc(risks[k].id)}</a>` : "").join(" ")}</div>
    ${reviewLine(i, ["accept", "reject"])}
    ${cites(i.evidence, 3)}</div>`;
  }).join("")}`;
}
function securityView(m) {
  const sec = S.state.security;
  if (!sec) { m.innerHTML = `<div class="empty">No security scan in this run.</div>`; return; }
  const card = (r) => riskCard({ ...r, meta: { severity: r.severity, state: r.state, category: r.category, incident: r.incident }, status: "active", history: [], stage: "analyse", kind: null, provenance: "guard" }, false);
  const inc = sec.risks.filter((r) => r.incident && r.state !== "addressed");
  const rest = sec.risks.filter((r) => !r.incident && r.state !== "addressed");
  m.innerHTML = `<h1>Remaining security flaws</h1>
  <p class="muted">The Security Guard's scanner run on the same data. IDs match the Security Guard, where Bob triages them — <a href="/?agent=guard">open the Security Guard →</a></p>
  <div class="card">${sec.open} open · ${Object.entries(sec.by_severity).map(([k, v]) => `<span class="sev ${k}">${k} ${v}</span>`).join(" ")}${sevBar(sec.by_severity)}</div>
  <h2>Exposed by this incident and still open (${inc.length})</h2>${inc.map(card).join("") || `<div class="faint">none</div>`}
  <h2>Process misdesign behind them</h2>${sec.rootcauses.map((rc) => `<div class="finding"><div class="f-title"><span class="sev ${rc.severity}">${rc.severity}</span> ${esc(rc.id)} · ${esc(rc.title)}</div><div class="f-reason"><b>Process fix:</b> ${esc(rc.fix)}</div>${cites(rc.evidence, 3)}</div>`).join("")}
  <h2>Remediations</h2>${sec.remediations.sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]).map((r) => `<div class="finding"><div class="f-title"><span class="sev ${r.severity}">${r.severity}</span> ${esc(r.id)} · ${esc(r.title.replace("Remediate: ", ""))}</div>
    <div class="plan"><b>Now</b><span>${esc(r.plan.now || "")}</span><b>Owner</b><span>${esc(r.plan.owner || "")}</span><b>Verify</b><span>${esc(r.plan.verify || "")}</span></div></div>`).join("")}
  <h2>Everything else still open (${rest.length})</h2>${rest.map(card).join("")}`;
}
