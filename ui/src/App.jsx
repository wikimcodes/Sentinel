import { useState, useEffect, useMemo } from "react";

const TIER = {
  red:    { label: "Very high", color: "#c1121f", rank: 0 },
  orange: { label: "High",      color: "#e07a00", rank: 1 },
  yellow: { label: "Moderate",  color: "#c9a400", rank: 2 },
  green:  { label: "Low",       color: "#2a9d5c", rank: 3 },
  none:   { label: "Not CKD",   color: "#8a8f98", rank: 4 },
};
const tierOf = (p) => p.expected.risk_tier || "none";

const SURFACE = {
  trajectory: { label: "Longitudinal catch", color: "#e07a00" },
  gap:        { label: "Treatment gap",       color: "#3b6fd4" },
  gap_gated:  { label: "Indicated — gated",   color: "#e07a00" },
  safety:     { label: "Safety",              color: "#c1121f" },
  referral:   { label: "Referral",            color: "#7a4fd0" },
  monitor:    { label: "Confirm first",       color: "#d97706" },
};
const SUPPRESS_LABEL = {
  already_optimised: "Already optimised", not_indicated: "Not indicated",
  gated_hold: "Held — unsafe now", non_steady_state: "Non–steady-state",
  resolved_aki: "Resolved AKI", pseudo_rise: "Pseudo-rise",
  egfr_failure_mode: "eGFR unreliable", no_progression: "Stable — no progression",
  no_referral: "No referral criterion", not_ckd: "Not CKD",
  provisional_defer: "Deferred — confirm CKD first",
};

// Narrow renal panel only — the bloods that drive CKD staging. No FBC / unrelated bloods.
const RESULTS = [
  { key: "creatinine_mg_dl",   label: "Creatinine",     unit: "mg/dL",         ref: "0.6–1.3", step: 0.01, lo: 0, hi: 3,  flag: (v) => (v > 1.3 ? "H" : v < 0.6 ? "L" : "") },
  { key: "egfr",               label: "eGFR",           unit: "mL/min/1.73m²", ref: "≥ 90",    step: 1,    lo: 15, hi: 95, flag: (v) => (v < 60 ? "L" : "") },
  { key: "acr_mg_g",           label: "Urine ACR",      unit: "mg/g",          ref: "< 30",    step: 1,    lo: 0, hi: 700, flag: (v) => (v >= 30 ? "H" : "") },
  { key: "potassium_mmol_l",   label: "Potassium",      unit: "mmol/L",        ref: "3.5–5.3", step: 0.1,  lo: 3.5, hi: 6.2, flag: (v) => (v > 5.3 ? "H" : v < 3.5 ? "L" : "") },
];

const fmtDate = (d) => new Date(d).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sortedLabs = (p) => [...p.labs].sort((a, b) => a.date.localeCompare(b.date));
const topLine = (p) => (!p.expected.ckd ? "Not CKD" : p.expected.surface.length ? p.expected.surface[0].summary : "Reviewed — no action");

// A free-text problem is "already coded" when one of the computed diagnosis codes expresses it.
const codedAlready = (c, codes) => {
  const cl = c.toLowerCase();
  const blob = (codes || []).map((x) => x.label.toLowerCase()).join(" ");
  if (cl.includes("chronic kidney")) return blob.includes("chronic kidney");
  if (cl.includes("hypertension"))   return blob.includes("hypertens");
  if (cl.includes("diabetes"))       return blob.includes("diabet");
  if (cl.includes("albumin"))        return blob.includes("albumin");
  return false;
};

// SystmOne-style investigations grid: rows = tests, columns = dates.
function ResultsTable({ labs, editing, onEdit, onDate, onAddTest, onToggleEdit, onTrend }) {
  const lastIdx = labs.length - 1;
  const flaggedCol = labs.map((l) => !!(l.flags && l.flags.length));
  return (
    <div className="results">
      <div className="results-bar">
        <span className="results-title">Renal panel · last {labs.length} results</span>
        {editing
          ? <div className="results-actions">
              <button className="mini-btn" onClick={onAddTest}>＋ Add test date</button>
              <button className="mini-btn primary" onClick={onToggleEdit}>Done</button>
            </div>
          : <button className="mini-btn" onClick={onToggleEdit}>Add / modify results</button>}
      </div>
      <div className="results-scroll">
        <table>
          <thead>
            <tr>
              <th className="an">Investigation</th>
              <th className="ref">Reference</th>
              {labs.map((l, i) => (
                <th key={i} className={i === lastIdx ? "col latest-h" : "col"}>
                  {editing
                    ? <input type="date" className="date-in" value={l.date} onChange={(e) => onDate(i, e.target.value)} />
                    : <>{fmtDate(l.date)}{flaggedCol[i] && <span className="warn-flag" title="confounded — excluded from slope">⚠</span>}</>}
                </th>
              ))}
              <th className="trend-h" />
            </tr>
          </thead>
          <tbody>
            {RESULTS.map((a) => (
              <tr key={a.key}>
                <td className="an"><strong>{a.label}</strong><span className="unit">{a.unit}</span></td>
                <td className="ref">{a.ref}</td>
                {labs.map((l, i) => {
                  const v = l[a.key];
                  const fl = a.flag(v);
                  return (
                    <td key={i} className={`col ${i === lastIdx ? "latest" : ""} ${flaggedCol[i] ? "conf" : ""}`}>
                      {editing
                        ? <input type="number" step={a.step} value={v} onChange={(e) => onEdit(i, a.key, e.target.value)} />
                        : <span className="val">{v}{fl && <span className={`fl fl-${fl.toLowerCase()}`}>{fl}</span>}</span>}
                    </td>
                  );
                })}
                <td className="trend-cell">
                  <button className="trend-btn" onClick={() => onTrend(a.key)}>See trend ↗</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="results-note">
        {editing ? "Edit any value, change a date, or add a new test — then close and re-run Sentinel."
                 : "H / L = outside reference range. ⚠ = flagged non–steady-state (acute illness / drug effect). Use Add / modify to enter a new result."}
      </p>
    </div>
  );
}

// Threshold reference lines per analyte (status colours, always text-labelled).
const TREND_REFS = {
  egfr:             [{ v: 60, label: "G3 (< 60)", color: "var(--warn)" }, { v: 30, label: "G4 (< 30)", color: "var(--miss)" }],
  acr_mg_g:         [{ v: 30, label: "A2 (≥ 30)", color: "var(--warn)" }, { v: 300, label: "A3 (≥ 300)", color: "var(--miss)" }],
  potassium_mmol_l: [{ v: 5.5, label: "gate (≥ 5.5)", color: "var(--miss)" }],
  creatinine_mg_dl: [{ v: 1.3, label: "upper normal", color: "var(--warn)" }],
};
function niceTicks(min, max, n = 5) {
  const span = max - min || 1;
  const raw = span / (n - 1);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 0.001; v += step) out.push(Math.round(v * 100) / 100);
  return out;
}

function TrendModal({ analyteKey, labs, onClose }) {
  const a = RESULTS.find((x) => x.key === analyteKey);
  const refs = TREND_REFS[analyteKey] || [];
  useEffect(() => {
    const h = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const pts = labs.map((l, i) => ({ i, date: l.date, v: l[analyteKey], flag: !!(l.flags && l.flags.length) }));
  const vals = pts.map((p) => p.v).concat(refs.map((r) => r.v));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo || 1) * 0.12; lo -= pad; hi += pad;
  const W = 660, H = 360, mL = 56, mR = 108, mT = 24, mB = 46;
  const px = (i) => mL + (pts.length === 1 ? 0.5 : i / (pts.length - 1)) * (W - mL - mR);
  const py = (v) => mT + (1 - (v - lo) / (hi - lo || 1)) * (H - mT - mB);
  const yticks = niceTicks(lo, hi, 5).filter((t) => t >= lo && t <= hi);
  const line = pts.filter((p) => !p.flag).map((p) => `${px(p.i)},${py(p.v)}`).join(" ");

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{a.label} — trend <span className="modal-unit">{a.unit}</span></h3>
          <button className="modal-x" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={`${a.label} over time`}>
          {yticks.map((t) => (
            <g key={t}>
              <line className="axis-grid" x1={mL} x2={W - mR} y1={py(t)} y2={py(t)} />
              <text className="axis-lbl" x={mL - 9} y={py(t) + 4} textAnchor="end">{t}</text>
            </g>
          ))}
          {refs.map((r) => (r.v >= lo && r.v <= hi) && (
            <g key={r.label}>
              <line className="ref-line" x1={mL} x2={W - mR} y1={py(r.v)} y2={py(r.v)} style={{ stroke: r.color }} />
              <text className="ref-lbl" x={W - mR + 7} y={py(r.v) + 4} style={{ fill: r.color }}>{r.label}</text>
            </g>
          ))}
          <line className="axis" x1={mL} x2={mL} y1={mT} y2={H - mB} />
          <line className="axis" x1={mL} x2={W - mR} y1={H - mB} y2={H - mB} />
          {pts.map((p) => (
            <text key={p.i} className="axis-lbl" x={px(p.i)} y={H - mB + 18} textAnchor="middle">{fmtDate(p.date)}</text>
          ))}
          <polyline className="chart-line" points={line} fill="none" />
          {pts.map((p) => (
            <g key={p.i}>
              <circle cx={px(p.i)} cy={py(p.v)} r={p.flag ? 5.5 : 5} className={p.flag ? "chart-flag" : "chart-pt"} />
              <text className="pt-val" x={px(p.i)} y={py(p.v) - 11} textAnchor="middle">{p.v}</text>
            </g>
          ))}
        </svg>
        <p className="modal-note">
          Line fits steady-state values only.{pts.some((p) => p.flag) ? " ○ Ringed points are confounded (acute illness / drug effect) and excluded from the slope." : ""}
        </p>
      </div>
    </div>
  );
}

// Minimal renderer: **bold** and "- " bullets, so agent answers read cleanly.
function RichText({ text }) {
  return (text || "").split(/\n+/).filter((l) => l.trim()).map((ln, i) => {
    const bullet = /^\s*[-•*]\s+/.test(ln);
    const body = ln.replace(/^\s*[-•*]\s+/, "");
    const parts = body.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((p, j) =>
      /^\*\*[^*]+\*\*$/.test(p) ? <strong key={j}>{p.slice(2, -2)}</strong> : <span key={j}>{p}</span>);
    return <p key={i} className={bullet ? "rt-li" : "rt-p"}>{parts}</p>;
  });
}

// ---------------------------------------------------------------------------
function EHRReview({ patient }) {
  const [labs, setLabs] = useState(() => sortedLabs(patient).map((l) => ({ ...l })));
  const [tab, setTab] = useState("overview");     // overview | results
  const [editing, setEditing] = useState(false);
  const [phase, setPhase] = useState("analyzing"); // analyzing | done
  const [result, setResult] = useState(null);
  const [steps, setSteps] = useState(0);
  const [stale, setStale] = useState(false);
  const [ranAt, setRanAt] = useState(null);
  const [referral, setReferral] = useState(null);
  const [refLoading, setRefLoading] = useState(false);
  const [prescribed, setPrescribed] = useState([]);
  const [trendKey, setTrendKey] = useState(null);
  const [live, setLive] = useState(false);
  const [liveTrace, setLiveTrace] = useState([]);
  const [askQ, setAskQ] = useState("");
  const [askThread, setAskThread] = useState([]);
  const [askLoading, setAskLoading] = useState(false);
  const [sms, setSms] = useState(null);
  const [notifying, setNotifying] = useState(false);
  const [askOpen, setAskOpen] = useState(false);

  const t = TIER[tierOf(patient)];

  useEffect(() => { runReview(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const markStale = () => { if (phase === "done") setStale(true); };
  function editLab(i, field, value) { setLabs((ls) => ls.map((l, j) => (j === i ? { ...l, [field]: Number(value) } : l))); markStale(); }
  function setDate(i, value) { setLabs((ls) => ls.map((l, j) => (j === i ? { ...l, date: value } : l))); markStale(); }
  function addTest() {
    const last = labs[labs.length - 1];
    const today = new Date().toISOString().slice(0, 10);
    setLabs((ls) => [...ls, { date: today, egfr: last.egfr, acr_mg_g: last.acr_mg_g,
      potassium_mmol_l: last.potassium_mmol_l, creatinine_mg_dl: last.creatinine_mg_dl }]);
    markStale();
  }

  const stamp = () => new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

  async function runReview() {
    setPhase("analyzing"); setResult(null); setSteps(0); setReferral(null); setPrescribed([]);
    setStale(false); setLiveTrace([]); setSms(null);
    const ordered = [...labs].sort((a, b) => a.date.localeCompare(b.date));

    if (live) {   // stream the real Claude tool-calling loop
      try {
        const resp = await fetch("/api/review-stream", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ patient_id: patient.id, labs: ordered }) });
        const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = "";
        for (;;) {
          const { done, value } = await reader.read(); if (done) break;
          buf += dec.decode(value, { stream: true });
          let idx;
          while ((idx = buf.indexOf("\n\n")) >= 0) {
            const dl = buf.slice(0, idx).split("\n").find((l) => l.startsWith("data:")); buf = buf.slice(idx + 2);
            if (!dl) continue;
            const ev = JSON.parse(dl.slice(5).trim());
            if (ev.type === "tool") setLiveTrace((tr) => [...tr, ev]);
            else if (ev.type === "result") setResult(ev.result);
            else if (ev.type === "error") throw new Error(ev.error);
          }
        }
      } catch {
        const r = await fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ patient_id: patient.id, labs: ordered }) }).then((x) => x.json());
        setResult(r);
      }
      setPhase("done"); setRanAt(stamp()); return;
    }

    const r = await fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patient_id: patient.id, labs: ordered }) }).then((x) => x.json());
    setResult(r);
    for (let i = 1; i <= r.trace.length; i++) { await sleep(360); setSteps(i); }
    await sleep(240); setPhase("done"); setRanAt(stamp());
  }

  async function submitAsk(e) {
    e.preventDefault(); if (!askQ.trim() || askLoading) return;
    const q = askQ; setAskQ(""); setAskLoading(true);
    const ordered = [...labs].sort((a, b) => a.date.localeCompare(b.date));
    try {
      const r = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patient_id: patient.id, labs: ordered, question: q }) }).then((x) => x.json());
      setAskThread((th) => [...th, { q, a: r.answer, tools: r.tools }]);
    } catch { setAskThread((th) => [...th, { q, a: "Sentinel is unavailable.", tools: [] }]); }
    setAskLoading(false);
  }

  async function notifyPatient() {
    setNotifying(true);
    try {
      const r = await fetch("/api/notify-patient", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patient_id: patient.id }) }).then((x) => x.json());
      setSms(r);
    } catch { setSms(null); }
    setNotifying(false);
  }

  async function generateReferral() {
    setRefLoading(true);
    const r = await fetch("/api/referral", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patient_id: patient.id, labs }) }).then((x) => x.json());
    setReferral(r); setRefLoading(false);
  }
  async function prescribe(drug) {
    const r = await fetch("/api/prescribe", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patient_id: patient.id, drug }) }).then((x) => x.json());
    setPrescribed((p) => [...p, { drug, message: r.message }]);
  }

  const surface = result ? [...result.surface].sort((a, b) => (a.priority || 9) - (b.priority || 9)) : [];

  return (
    <section className="right open">
      <header className="patient-banner">
        <div className="pb-av">{patient.name.split(" ").map((s) => s[0]).join("").slice(0, 2)}</div>
        <div className="pb-id">
          <h2>{patient.name}</h2>
          <div className="pb-fields">
            <span><label>Age/Sex</label>{patient.age} {patient.sex === "M" ? "Male" : "Female"}</span>
            <span><label>DOB</label>{`01 Jan ${new Date().getFullYear() - patient.age}`}</span>
            <span><label>MRN</label>{patient.id.toUpperCase()}</span>
            <span><label>NHS</label>{`485 ${(patient.age * 37) % 900 + 100} ${(patient.age * 113) % 9000 + 1000}`}</span>
          </div>
        </div>
        <div className="pb-flags">
          <span className="pb-chip allergy" title="No known drug allergies">NKDA</span>
          {patient.diabetes && <span className="pb-chip">Diabetic</span>}
          {patient.pregnant && <span className="pb-chip warn">⚠ Pregnant</span>}
          {patient.dialysis && <span className="pb-chip warn">⚠ Dialysis</span>}
          <span className="stage-chip" style={{ borderColor: t.color, color: t.color }}>
            CKD {patient.expected.stage || "—"} · {t.label}
          </span>
        </div>
      </header>

      {/* ---------- EHR record: tabbed ---------- */}
      <div className="tabs">
        <button className={`tab ${tab === "overview" ? "active" : ""}`} onClick={() => setTab("overview")}>Overview</button>
        <button className={`tab ${tab === "results" ? "active" : ""}`} onClick={() => setTab("results")}>Recent results</button>
      </div>

      {tab === "overview" ? (
        <div className="ehr">
          <div className="ehr-grid">
            <div className="ehr-box">
              <h4>Problem list <span className="coded-hint" title="Diagnoses auto-coded from the computed stage — SNOMED CT (clinical) + ICD-10 (billing), resolved via a FHIR terminology server in production">SNOMED CT · ICD-10</span></h4>
              <div className="problems">
                {(patient.expected.codes || []).map((c) => (
                  <div key={c.label} className="prob-row">
                    <span className="prob-name">{c.label}</span>
                    <span className="prob-codes">
                      {c.snomed && <code title="SNOMED CT — clinical terminology">SNOMED {c.snomed}</code>}
                      <code title="ICD-10 — classification / billing">ICD-10 {c.icd10}</code>
                    </span>
                  </div>
                ))}
                {(patient.comorbidities || [])
                  .filter((c) => !codedAlready(c, patient.expected.codes))
                  .map((c) => (
                    <div key={c} className="prob-row">
                      <span className="prob-name">{c}</span>
                      <span className="prob-uncoded">uncoded</span>
                    </div>
                  ))}
                {(patient.expected.codes || []).length === 0 && (patient.comorbidities || []).length === 0 && (
                  <div className="none">None recorded</div>
                )}
              </div>
            </div>
            <div className="ehr-box">
              <h4>Current medications</h4>
              <ul className="meds">
                {patient.medications.map((m) => <li key={m.name}><strong>{m.name}</strong> {m.dose}</li>)}
                {prescribed.map((p) => <li key={p.drug} className="new"><strong>{p.drug}</strong> · started today ✓</li>)}
                {patient.medications.length === 0 && prescribed.length === 0 && <li className="none">None recorded</li>}
              </ul>
            </div>
          </div>
          <div className="ehr-box">
            <h4>Recent encounters</h4>
            <ul className="encounters">
              {(patient.encounters || []).map((e, i) => (
                <li key={i}><span className="enc-date">{fmtDate(e.date)}</span>
                  <span className="enc-type">{e.type}</span><span className="enc-sum">{e.summary}</span></li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <div className="ehr">
          <div className="ehr-box">
            <ResultsTable labs={labs} editing={editing} onEdit={editLab} onDate={setDate}
              onAddTest={addTest} onToggleEdit={() => setEditing((e) => !e)} onTrend={setTrendKey} />
          </div>
        </div>
      )}

      {/* ---------- Sentinel agent layer ---------- */}
      <div className="agent-band">
        <div className="band-head">
          <span className="band-mark">SENTINEL</span>
          <span className="band-desc">between-visit review · agent augmentation over the record</span>
        </div>
        <div className="runbar">
          <button className="run" onClick={runReview} disabled={phase === "analyzing"}>
            {phase === "analyzing" ? (live ? "Claude working…" : "Analyzing…") : phase === "done" ? "▶ Re-run" : "▶ Run Sentinel"}
          </button>
          <label className="live-toggle" title="Run the real Claude tool-calling agent instead of the deterministic core">
            <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} disabled={phase === "analyzing"} />
            ⚡ Live Claude agent
          </label>
          <span className="run-status">
            {phase === "analyzing"
              ? <span className="run-analyzing">◐ {live ? "Claude is planning and calling the core tools…" : "checking the record against KDIGO 2024…"}</span>
              : stale ? <span className="run-stale">● record changed — re-run</span>
              : phase === "done" ? <span className="run-ok">✓ Reviewed {ranAt} · {result?.engine}</span> : null}
          </span>
        </div>
      </div>

      {(result || liveTrace.length > 0) && (
        <div className="trace">
          <div className="trace-head"><span className="pulse" data-run={phase === "analyzing"} />
            <h4>Agent activity — checking the record against the guideline logic</h4>
            <span className={`engine ${(result?.engine || "").startsWith("Claude") || (live && !result) ? "live" : ""}`}>{result?.engine || "Claude agent (live tool-calling)"}</span></div>
          {(phase === "analyzing" && live ? liveTrace : (result ? result.trace.slice(0, phase === "done" ? result.trace.length : steps) : [])).map((s, i) => (
            <div className="trace-row" key={i}><code>{s.tool}</code><span className="arrow">→</span><span>{s.summary}</span></div>
          ))}
          {phase === "analyzing" && <div className="trace-row dim">…</div>}
        </div>
      )}

      {phase === "done" && result && (
        <>
          <div className="brief">
            <div className="brief-headline">{result.brief.headline}</div>
            <div className="brief-buckets">
              <Bucket title="What was missed" items={result.brief.missed} tone="miss" />
              <Bucket title="Needs attention" items={result.brief.attention} tone="warn" />
              <Bucket title="Working (reassurance)" items={result.brief.working} tone="ok" suppress />
              <Bucket title="Ruled out — why not flagged" items={result.brief.ruled_out} tone="mute" suppress />
            </div>
          </div>

          <div className="cols">
            <div className="col">
              <h3 className="col-h">Ranked actions</h3>
              {surface.length === 0 && <p className="empty">No action — reviewed and clear.</p>}
              {surface.map((s, i) => {
                const m = SURFACE[s.type] || { label: s.type, color: "#888" };
                const done = prescribed.find((p) => p.drug === s.drug);
                return (
                  <div className="card action" key={i} style={{ borderLeftColor: m.color }}>
                    <div className="card-top"><span className="tag" style={{ background: m.color }}>{m.label}</span>
                      {s.drug && <span className="drug">{s.drug}</span>}</div>
                    <p className="card-body">{s.summary}</p>
                    <a className="cite" href={s.citation.url} target="_blank" rel="noopener noreferrer">
                      <span className="cite-chip">Source</span>{s.citation.text}</a>
                    {s.type === "gap" && (done
                      ? <p className="done-msg">✓ {done.message}</p>
                      : <button className="act" onClick={() => prescribe(s.drug)}>Prescribe {s.drug}</button>)}
                    {s.type === "referral" && (referral
                      ? <div className="letter-wrap">
                          <div className="letter-src">generated {referral.source === "claude" ? "live by Claude" : "from template"}</div>
                          <pre className="letter">{referral.letter}</pre></div>
                      : <button className="act" onClick={generateReferral} disabled={refLoading}>
                          {refLoading ? "Generating…" : "Generate referral letter"}</button>)}
                  </div>
                );
              })}
              <div className="card action outreach" style={{ borderLeftColor: "#7a4fd0" }}>
                <div className="card-top"><span className="tag" style={{ background: "#7a4fd0" }}>Patient outreach</span></div>
                <p className="card-body">Invite the patient to book a review appointment.</p>
                {sms ? (
                  <div className="sms-mock">
                    <div className="sms-head">✓ Message sent to {sms.to}</div>
                    <div className="sms-bubble">{sms.message}</div>
                    <div className="sms-foot">{sms.source === "claude" ? "written live by Sentinel" : "template"} · patient can reply BOOK to schedule</div>
                  </div>
                ) : (
                  <button className="act" onClick={notifyPatient} disabled={notifying}>
                    {notifying ? "Sending…" : "✉ Message patient to book"}</button>
                )}
              </div>
            </div>

            <div className="col moat">
              <h3 className="col-h">Considered &amp; withheld<span className="moat-count">{result.suppress.length}</span></h3>
              <p className="moat-intro">What Sentinel deliberately did <em>not</em> surface — each mapped to the guideline that makes it safe.</p>
              {result.suppress.map((s, i) => (
                <div className="card suppress" key={i}>
                  <div className="card-top"><span className="tag muted">{SUPPRESS_LABEL[s.type] || s.type}</span>
                    <span className="drug muted">{s.item}</span></div>
                  <p className="card-body muted">{s.reason}</p>
                  <a className="cite muted" href={s.citation.url} target="_blank" rel="noopener noreferrer">
                    <span className="cite-chip">Source</span>{s.citation.text}</a>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {trendKey && (
        <TrendModal analyteKey={trendKey}
          labs={[...labs].sort((a, b) => a.date.localeCompare(b.date))}
          onClose={() => setTrendKey(null)} />
      )}

      {/* Floating Ask Sentinel agent */}
      <div className="ask-fab">
        {askOpen && (
          <div className="ask-panel">
            <div className="ask-panel-head">
              <span className="ap-mark">S</span>
              <div className="ap-title"><strong>Ask Sentinel</strong><small>{patient.name} · reasons over the tools</small></div>
              <button className="ap-x" onClick={() => setAskOpen(false)} aria-label="Close">✕</button>
            </div>
            <div className="ask-panel-body">
              {askThread.length === 0 && !askLoading && (
                <p className="ap-hint">Ask anything about this patient — e.g. <em>“Would an ACE inhibitor be safe here?”</em> or <em>“What if her K⁺ were 5.6?”</em></p>
              )}
              {askThread.map((qa, i) => (
                <div className="qa" key={i}>
                  <p className="qa-q">{qa.q}</p>
                  <div className="qa-a"><RichText text={qa.a} /></div>
                  {qa.tools && qa.tools.length ? <p className="qa-tools">Reasoned via {[...new Set(qa.tools)].join(" · ")}</p> : null}
                </div>
              ))}
              {askLoading && <p className="qa-a dim">Sentinel is reasoning through the tools…</p>}
            </div>
            <form className="ask-panel-form" onSubmit={submitAsk}>
              <input value={askQ} onChange={(e) => setAskQ(e.target.value)} placeholder="Ask about this patient…" autoFocus />
              <button type="submit" disabled={askLoading || !askQ.trim()}>➤</button>
            </form>
          </div>
        )}
        <button className={`fab-btn ${askOpen ? "on" : ""}`} onClick={() => setAskOpen((o) => !o)} title="Ask Sentinel">
          {askOpen ? "✕" : "S"}
        </button>
      </div>
    </section>
  );
}

function Bucket({ title, items, tone, suppress }) {
  return (
    <div className={`bucket ${tone}`}>
      <div className="bucket-h">{title}<span>{items.length}</span></div>
      {items.length === 0 && <p className="bucket-empty">—</p>}
      {items.map((s, i) => (
        <p className="bucket-item" key={i}>
          {suppress ? (SUPPRESS_LABEL[s.type] || s.type) + " · " + s.item
            : (s.drug || (s.type === "trajectory" ? "eGFR trajectory" : s.type === "referral" ? "Nephrology referral" : s.item || s.type))}
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
const Arrow = () => (
  <marker id="ah" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">
    <path d="M0,0 L7,3 L0,6 Z" className="ah" />
  </marker>
);

function ArchitectureView() {
  const tools = ["stage_patient", "egfr_trajectory", "evaluate_medications", "referral", "suppression_rules"];
  const principles = [
    ["Deterministic core, not RAG", "Guideline logic is encoded as testable thresholds the agent cannot override — stronger than retrieving text and hoping."],
    ["Suppression is the moat", "Knowing what NOT to surface is the scarce resource; it's first-class logic, shown to the clinician with its reason."],
    ["Validated end-to-end", "The eval harness scores the core (F1 92.7%) and the live agent (F1 89.8%) against a clinician's golden set."],
    ["Scales with model intelligence", "Swap in the next model; reasoning, judgment and computer-use all improve — the product gets better for free."],
  ];
  return (
    <section className="right open story">
      <header className="detail-head"><div>
        <h2>Agent architecture</h2>
        <p className="sub">Sentinel plans and orchestrates; a deterministic core owns every number</p>
      </div></header>

      <div className="diagram-wrap">
        <svg viewBox="0 0 760 552" className="diagram" role="img" aria-label="Sentinel agent architecture">
          <defs><Arrow /></defs>
          {/* spine */}
          <line x1="380" y1="74" x2="380" y2="114" className="edge" markerEnd="url(#ah)" />
          <line x1="380" y1="244" x2="380" y2="284" className="edge" markerEnd="url(#ah)" />
          <line x1="380" y1="348" x2="380" y2="384" className="edge" markerEnd="url(#ah)" />
          <line x1="380" y1="440" x2="380" y2="472" className="edge" markerEnd="url(#ah)" />
          {/* agent <-> core */}
          <line x1="534" y1="158" x2="564" y2="158" className="edge" markerEnd="url(#ah)" />
          <line x1="564" y1="200" x2="534" y2="200" className="edge" markerEnd="url(#ah)" />
          <text x="549" y="150" className="elbl" textAnchor="middle">calls</text>
          <text x="549" y="216" className="elbl" textAnchor="middle">numbers</text>
          {/* eval -> agent */}
          <line x1="184" y1="180" x2="226" y2="180" className="edge dash" markerEnd="url(#ah)" />

          <g><rect x="280" y="24" width="200" height="50" rx="12" className="node" />
            <text x="380" y="46" className="nt" textAnchor="middle">EHR record</text>
            <text x="380" y="63" className="ns" textAnchor="middle">FHIR · GP Connect · SMART launch</text></g>

          <g><rect x="226" y="114" width="308" height="128" rx="16" className="node agent" />
            <text x="380" y="144" className="nt big" textAnchor="middle">Sentinel Agent</text>
            <text x="380" y="167" className="ns" textAnchor="middle">plans · calls tools · composes the review</text>
            <text x="380" y="184" className="ns" textAnchor="middle">reasons, but never does the arithmetic</text>
            <text x="380" y="216" className="loop" textAnchor="middle">plan → call → observe → compose ⟳</text></g>

          <g><rect x="564" y="98" width="186" height="220" rx="14" className="cluster" />
            <text x="657" y="116" className="clbl" textAnchor="middle">DETERMINISTIC CORE</text>
            {tools.map((t, i) => (
              <g key={t}><rect x="576" y={126 + i * 36} width="162" height="28" rx="8" className="node tool" />
                <text x="657" y={144 + i * 36} className="tt" textAnchor="middle">{t}</text></g>
            ))}</g>

          <g><rect x="24" y="140" width="160" height="82" rx="12" className="node eval" />
            <text x="104" y="164" className="nt" textAnchor="middle">Eval harness</text>
            <text x="104" y="184" className="ns" textAnchor="middle">core F1 92.7%</text>
            <text x="104" y="200" className="ns" textAnchor="middle">agent F1 89.8%</text>
            <text x="104" y="216" className="ns" textAnchor="middle">vs clinician gold</text></g>

          <g><rect x="242" y="284" width="276" height="60" rx="14" className="node" />
            <text x="380" y="309" className="nt" textAnchor="middle">Ranked actions · Suppression</text>
            <text x="380" y="328" className="ns" textAnchor="middle">+ draft referral, each with a KDIGO citation</text></g>

          <g><rect x="254" y="384" width="252" height="56" rx="14" className="node human" />
            <text x="380" y="408" className="nt" textAnchor="middle">Clinician — accept / override</text>
            <text x="380" y="426" className="ns" textAnchor="middle">decision support, not autonomous prescribing</text></g>

          <g><rect x="206" y="472" width="348" height="58" rx="14" className="node" />
            <text x="380" y="497" className="nt" textAnchor="middle">Write-back</text>
            <text x="380" y="516" className="ns" textAnchor="middle">FHIR ServiceRequest/Task · CDS Hooks · computer use</text></g>
        </svg>
      </div>

      <div className="arch-principles">
        {principles.map(([h, p]) => <div className="pr" key={h}><h4>{h}</h4><p>{p}</p></div>)}
      </div>
    </section>
  );
}

const PERSONAS = [
  { key: "amara", name: "Dr. Amara", role: "Panel GP", job: "“Show me which patients changed between visits, so I spend my minutes on the ones who matter.”", jtbd: ["Stratify", "Catch the slow decline"] },
  { key: "bola", name: "Nurse Bola", role: "Care coordinator", job: "“Give me a prioritised worklist — who needs a lab, a titration, or a referral — so nothing slips.”", jtbd: ["Close the gap", "Draft the escalation"] },
  { key: "chen", name: "Dr. Chen", role: "Nephrology reviewer", job: "“Show me the reasoning and the ruled-out confounders, so I can trust or overrule in seconds.”", jtbd: ["Withhold (suppression)", "Respect safety gates"] },
];

function FrameworkView() {
  // persona -> job -> eval mapping for the diagram
  const P = [{ n: "Dr. Amara", r: "Panel GP", cls: "amara", y: 78 },
             { n: "Nurse Bola", r: "Coordinator", cls: "bola", y: 210 },
             { n: "Dr. Chen", r: "Reviewer", cls: "chen", y: 330 }];
  const J = [{ j: "Stratify", p: 0, ev: "C1 · staging", y: 44 },
             { j: "Catch decline", p: 0, ev: "C2 · progression", y: 104 },
             { j: "Close the gap", p: 1, ev: "C4 · gap fire", y: 178 },
             { j: "Draft escalation", p: 1, ev: "C7 · referral", y: 238 },
             { j: "Withhold", p: 2, ev: "C3/C5 · suppression", y: 312 },
             { j: "Safety gate", p: 2, ev: "C6 · gating", y: 372 }];
  return (
    <section className="right open story">
      <header className="detail-head"><div>
        <h2>Persona · jobs-to-be-done framework</h2>
        <p className="sub">Who it's for → what they need done → how each is measured</p>
      </div></header>

      <div className="diagram-wrap">
        <svg viewBox="0 0 760 420" className="diagram" role="img" aria-label="Persona to jobs to evals mapping">
          <defs><Arrow /></defs>
          <text x="95" y="22" className="clbl" textAnchor="middle">PERSONA</text>
          <text x="380" y="22" className="clbl" textAnchor="middle">JOB TO BE DONE</text>
          <text x="670" y="22" className="clbl" textAnchor="middle">EVAL</text>
          {/* connectors */}
          {J.map((job, i) => (
            <g key={i}>
              <path d={`M172,${P[job.p].y} C230,${P[job.p].y} 240,${job.y} 300,${job.y}`} className={`edge fw-${P[job.p].cls}`} fill="none" />
              <line x1="470" y1={job.y} x2="586" y2={job.y} className="edge" markerEnd="url(#ah)" />
            </g>
          ))}
          {/* personas */}
          {P.map((p, i) => (
            <g key={i}><rect x="20" y={p.y - 32} width="152" height="64" rx="14" className={`node persona-node ${p.cls}`} />
              <text x="96" y={p.y - 6} className="nt" textAnchor="middle">{p.n}</text>
              <text x="96" y={p.y + 13} className="ns" textAnchor="middle">{p.r}</text></g>
          ))}
          {/* jobs */}
          {J.map((job, i) => (
            <g key={i}><rect x="300" y={job.y - 17} width="170" height="34" rx="9" className="node" />
              <text x="385" y={job.y + 4} className="tt" textAnchor="middle">{job.j}</text></g>
          ))}
          {/* evals */}
          {J.map((job, i) => (
            <text key={i} x="590" y={job.y + 4} className="fw-ev">{job.ev}</text>
          ))}
        </svg>
      </div>

      <div className="fw-insight">
        <strong>Dr. Chen decides adoption.</strong> A GP is impressed by a risk grid; a reviewer only trusts a tool that demonstrably knows what <em>not</em> to say. That's why Chen owns suppression and safety — and why a naive engine scores well for the easy persona (high recall) but collapses on the hard one.
      </div>

      <div className="persona-grid">
        {PERSONAS.map((p) => (
          <div className={`persona ${p.key}`} key={p.key}>
            <div className="persona-h"><strong>{p.name}</strong><span>{p.role}</span></div>
            <p className="persona-job">{p.job}</p>
            <div className="persona-jtbd">{p.jtbd.map((j) => <span key={j} className="jchip">{j}</span>)}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
function EvalDashboard() {
  const [d, setD] = useState(null);
  useEffect(() => { fetch("/api/evals").then((r) => r.json()).then(setD).catch(() => setD({ error: true })); }, []);
  if (!d) return <section className="right"><p className="hint" style={{ margin: 24 }}>Computing evals against the golden set…</p></section>;
  if (d.error) return <section className="right"><p className="err">Backend not reachable.</p></section>;
  const maxF1 = Math.max(...d.rows.map((r) => r.f1));
  return (
    <section className="right open eval-page">
      <header className="detail-head">
        <div>
          <h2>How good is Sentinel?</h2>
          <p className="sub">Scored against {d.against} · n={d.n}</p>
        </div>
      </header>

      <div className="moat-cards">
        <div className="moat-card bad">
          <span className="moat-big">{d.false_alarm.naive}%</span>
          <span className="moat-cap">naive rule engine<br />false-alarm rate</span>
        </div>
        <span className="moat-arrow">→</span>
        <div className="moat-card good">
          <span className="moat-big">{d.false_alarm.sentinel}%</span>
          <span className="moat-cap">Sentinel<br />false-alarm rate</span>
        </div>
        <p className="moat-say">The moat. A naive engine cries wolf on nearly half its alerts — clinicians switch those off. Sentinel's <strong>suppression layer</strong> is what closes the gap.</p>
      </div>

      <div className="eval-table">
        <div className="eval-th"><span>Approach</span><span className="num">Precision</span><span className="num">Recall</span><span className="num">F1</span></div>
        {d.rows.map((r, i) => (
          <div className={`eval-row ${r.tone}`} key={i}>
            <div className="eval-name"><strong>{r.name}</strong><span className="eval-sub">{r.sub}</span></div>
            <span className="num">{r.precision}%</span>
            <span className="num">{r.recall}%</span>
            <span className="num f1">
              <span className="bar"><span className="bar-fill" style={{ width: `${(r.f1 / maxF1) * 100}%` }} /></span>
              {r.f1}%{r.measured && <span className="measured">live</span>}
            </span>
          </div>
        ))}
      </div>
      <p className="eval-foot">Staging accuracy <strong>{d.staging_accuracy}%</strong> · CKD-gate accuracy <strong>{d.ckd_gate_accuracy}%</strong> · core &amp; naive rows computed live just now; the agent row is 50 real Claude tool-calling runs.</p>

      <div className="eval-explain">
        <h3 className="col-h">What the numbers mean</h3>
        <div className="ex-grid">
          <div className="ex"><h4>Precision</h4><p>When Sentinel flags something, how often the clinician agrees. High precision = it doesn't nag.</p></div>
          <div className="ex"><h4>Recall</h4><p>Of everything the clinician would flag, how much Sentinel catches. High recall = nothing important slips.</p></div>
          <div className="ex"><h4>False-alarm</h4><p>The share of alerts that are wrong — the reason clinicians disable tools. Sentinel's suppression cuts it from {d.false_alarm.naive}% to {d.false_alarm.sentinel}%.</p></div>
          <div className="ex"><h4>Why the agent row matters</h4><p>The <strong>live Claude agent</strong> — planning and calling the core tools, doing no arithmetic itself — scores F1 {d.rows[2].f1}% against clinician cases it never saw, within a few points of the deterministic core. The agent is validated, not just the core.</p></div>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
export default function App() {
  const [patients, setPatients] = useState(null);
  const [err, setErr] = useState(null);
  const [id, setId] = useState(null);
  const [view, setView] = useState("panel");   // panel | architecture | framework | evals
  const [q, setQ] = useState("");

  useEffect(() => {
    fetch("/api/patients").then((r) => r.json()).then((d) => setPatients(d.patients))
      .catch(() => setErr("Backend not reachable — run  python3 server/app.py"));
  }, []);

  const rows = useMemo(() => {
    if (!patients) return [];
    const trigDate = (p) => (p.trigger && p.trigger.date) || "";
    // Default worklist order is "most recent" — newest between-visit trigger first —
    // then sickest, then most open actions.
    return [...patients].sort((a, b) => trigDate(b).localeCompare(trigDate(a))
      || TIER[tierOf(a)].rank - TIER[tierOf(b)].rank
      || b.expected.surface.length - a.expected.surface.length);
  }, [patients]);

  const selected = patients && patients.find((p) => p.id === id);
  const needAction = patients ? patients.filter((p) => p.expected.surface.length).length : 0;
  const shown = rows.filter((p) => !q || p.name.toLowerCase().includes(q.toLowerCase()) || p.id.toLowerCase().includes(q.toLowerCase()));

  return (
    <div className="app-shell">
      <header className="appbar">
        <div className="brand"><span className="logo-mark">S</span><h1>Sentinel</h1></div>
        <nav className="topnav">
          {[["panel", "Worklist"], ["architecture", "Architecture"], ["framework", "Framework"], ["evals", "Evals"]].map(([v, label]) => (
            <button key={v} className={view === v ? "active" : ""} onClick={() => setView(v)}>{label}</button>
          ))}
        </nav>
        <div className="appbar-right">
          <div className="searchbox">
            <span className="mag">⌕</span>
            <input placeholder="Search patients…" value={q} onChange={(e) => { setQ(e.target.value); setView("panel"); }} />
          </div>
          <div className="userchip"><span className="user-av">RA</span><span className="user-meta"><strong>Dr. Rao</strong><small>Family Medicine</small></span></div>
        </div>
      </header>

      <div className="split">
        {view === "panel" && (
          <aside className="left">
            <div className="worklist-head">
              <div><h3>CKD worklist</h3><p className="sub">{patients ? `${shown.length} patients` : "loading…"}</p></div>
              <div className="stat"><span className="stat-num">{needAction}</span><span className="stat-label">need action</span></div>
            </div>
            {err && <p className="err">{err}</p>}
            <div className="patient-list">
              {shown.map((p) => {
                const tt = TIER[tierOf(p)]; const acts = p.expected.surface.length;
                return (
                  <button key={p.id} className={`row ${p.id === id ? "sel" : ""}`} onClick={() => setId(p.id)}>
                    <span className="dot" style={{ background: tt.color }} />
                    <span className="row-main"><span className="row-name">{p.name}</span>
                      <span className="row-line">{topLine(p)}</span></span>
                    <span className="row-right"><span className="row-stage">{p.expected.stage || "G2 A1"}</span>
                      <span className={`row-badge ${acts ? "act" : "quiet"}`}>{acts || "✓"}</span></span>
                  </button>
                );
              })}
            </div>
          </aside>
        )}

        {view === "evals" ? <EvalDashboard /> : view === "architecture" ? <ArchitectureView /> : view === "framework" ? <FrameworkView /> : selected ? <EHRReview key={selected.id} patient={selected} /> : (
          <section className="right empty-detail">
            <div><p className="hint-title">Select a patient</p>
              <p className="hint">Sentinel pre-sifts each record against KDIGO 2024 and surfaces what a 10-minute visit would miss — then lets you act on it.</p></div>
          </section>
        )}
      </div>
    </div>
  );
}
