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
};
const SUPPRESS_LABEL = {
  already_optimised: "Already optimised", not_indicated: "Not indicated",
  gated_hold: "Held — unsafe now", non_steady_state: "Non–steady-state",
  resolved_aki: "Resolved AKI", pseudo_rise: "Pseudo-rise",
  egfr_failure_mode: "eGFR unreliable", no_progression: "Stable — no progression",
  no_referral: "No referral criterion", not_ckd: "Not CKD",
};

// Narrow renal panel only — the bloods that drive CKD staging. No FBC / unrelated bloods.
const RESULTS = [
  { key: "creatinine_mg_dl",   label: "Creatinine",     unit: "mg/dL",         ref: "0.6–1.3", step: 0.01, lo: 0, hi: 3,  flag: (v) => (v > 1.3 ? "H" : v < 0.6 ? "L" : "") },
  { key: "egfr",               label: "eGFR",           unit: "mL/min/1.73m²", ref: "> 60",    step: 1,    lo: 15, hi: 95, flag: (v) => (v < 60 ? "L" : "") },
  { key: "acr_mg_g",           label: "Urine ACR",      unit: "mg/g",          ref: "< 30",    step: 1,    lo: 0, hi: 700, flag: (v) => (v >= 30 ? "H" : "") },
  { key: "potassium_mmol_l",   label: "Potassium",      unit: "mmol/L",        ref: "3.5–5.3", step: 0.1,  lo: 3.5, hi: 6.2, flag: (v) => (v > 5.3 ? "H" : v < 3.5 ? "L" : "") },
];

const fmtDate = (d) => new Date(d).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sortedLabs = (p) => [...p.labs].sort((a, b) => a.date.localeCompare(b.date));
const topLine = (p) => (!p.expected.ckd ? "Not CKD" : p.expected.surface.length ? p.expected.surface[0].summary : "Reviewed — no action");

// ---------------------------------------------------------------------------
function Sparkline({ values, flags, thresholds, lo, hi }) {
  const W = 96, H = 26, P = 3;
  const min = Math.min(lo, ...values), max = Math.max(hi, ...values);
  const x = (i) => P + (values.length === 1 ? 0.5 : i / (values.length - 1)) * (W - 2 * P);
  const y = (v) => P + (1 - (v - min) / (max - min || 1)) * (H - 2 * P);
  const steady = values.map((v, i) => (flags[i] ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mini">
      {(thresholds || []).map((t) => t >= min && t <= max && (
        <line key={t} className="mini-grid" x1={P} x2={W - P} y1={y(t)} y2={y(t)} />
      ))}
      <polyline className="mini-line" points={steady} fill="none" />
      {values.map((v, i) => (
        <circle key={i} cx={x(i)} cy={y(v)} r={flags[i] ? 2.6 : 2.2} className={flags[i] ? "mini-flag" : "mini-pt"} />
      ))}
    </svg>
  );
}

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
              <th className="trend">Trend</th>
              {labs.map((l, i) => (
                <th key={i} className={i === lastIdx ? "col latest-h" : "col"}>
                  {editing
                    ? <input type="date" className="date-in" value={l.date} onChange={(e) => onDate(i, e.target.value)} />
                    : <>{fmtDate(l.date)}{flaggedCol[i] && <span className="warn-flag" title="confounded — excluded from slope">⚠</span>}</>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {RESULTS.map((a) => (
              <tr key={a.key}>
                <td className="an"><strong>{a.label}</strong><span className="unit">{a.unit}</span></td>
                <td className="ref">{a.ref}</td>
                <td className="trend">
                  <Sparkline values={labs.map((l) => l[a.key])} flags={flaggedCol} thresholds={a.key === "egfr" ? [30, 60] : []} lo={a.lo} hi={a.hi} />
                  <button className="trend-btn" onClick={() => onTrend(a.key)}>See trend ↗</button>
                </td>
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

  async function runReview() {
    setPhase("analyzing"); setResult(null); setSteps(0); setReferral(null); setPrescribed([]); setStale(false);
    const ordered = [...labs].sort((a, b) => a.date.localeCompare(b.date));
    const r = await fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patient_id: patient.id, labs: ordered }) }).then((x) => x.json());
    setResult(r);
    for (let i = 1; i <= r.trace.length; i++) { await sleep(360); setSteps(i); }
    await sleep(240);
    setPhase("done");
    setRanAt(new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }));
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
      <header className="detail-head">
        <div>
          <h2>{patient.name}</h2>
          <p className="sub">{patient.age}{patient.sex} · MRN {patient.id.toUpperCase()}</p>
        </div>
        <span className="stage-chip" style={{ borderColor: t.color, color: t.color }}>
          CKD {patient.expected.stage || "—"} · {t.label}
        </span>
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
              <h4>Problem list</h4>
              <div className="chips">{(patient.comorbidities || []).map((c) => <span key={c} className="chip">{c}</span>)}</div>
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
          {stale ? (
            <>
              <button className="run" onClick={runReview} disabled={phase === "analyzing"}>
                {phase === "analyzing" ? "Re-analyzing…" : "▶ Re-run Sentinel review"}</button>
              <span className="run-stale">● record changed since last review</span>
            </>
          ) : phase === "analyzing"
            ? <span className="run-analyzing">◐ Sentinel is analyzing the record against KDIGO 2024…</span>
            : <span className="run-ok">✓ Reviewed {ranAt} · modify any result to re-run</span>}
        </div>
      </div>

      {result && (
        <div className="trace">
          <div className="trace-head"><span className="pulse" data-run={phase === "analyzing"} />
            <h4>Agent activity — checking the record against the guideline logic</h4></div>
          {result.trace.slice(0, phase === "done" ? result.trace.length : steps).map((s, i) => (
            <div className="trace-row" key={i}><code>{s.tool}</code><span className="arrow">→</span><span>{s.summary}</span></div>
          ))}
          {phase === "analyzing" && steps < result.trace.length && <div className="trace-row dim">…</div>}
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
                    <p className="cite">📖 {s.citation}</p>
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
            </div>

            <div className="col moat">
              <h3 className="col-h">Considered &amp; withheld<span className="moat-count">{result.suppress.length}</span></h3>
              <p className="moat-intro">What Sentinel deliberately did <em>not</em> surface — each mapped to the guideline that makes it safe.</p>
              {result.suppress.map((s, i) => (
                <div className="card suppress" key={i}>
                  <div className="card-top"><span className="tag muted">{SUPPRESS_LABEL[s.type] || s.type}</span>
                    <span className="drug muted">{s.item}</span></div>
                  <p className="card-body muted">{s.reason}</p>
                  <p className="cite muted">📖 {s.citation}</p>
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
export default function App() {
  const [patients, setPatients] = useState(null);
  const [err, setErr] = useState(null);
  const [id, setId] = useState(null);

  useEffect(() => {
    fetch("/api/patients").then((r) => r.json()).then((d) => setPatients(d.patients))
      .catch(() => setErr("Backend not reachable — run  python3 server/app.py"));
  }, []);

  const rows = useMemo(() => {
    if (!patients) return [];
    return [...patients].sort((a, b) => TIER[tierOf(a)].rank - TIER[tierOf(b)].rank
      || b.expected.surface.length - a.expected.surface.length);
  }, [patients]);

  const selected = patients && patients.find((p) => p.id === id);
  const needAction = patients ? patients.filter((p) => p.expected.surface.length).length : 0;

  return (
    <div className={`split ${id ? "has-detail" : ""}`}>
      <aside className="left">
        <div className="left-head">
          <div><h1>Sentinel</h1>
            <p className="sub">{patients ? `${patients.length}-patient panel` : "loading…"} · KDIGO 2024</p></div>
          <div className="stat"><span className="stat-num">{needAction}</span><span className="stat-label">need action</span></div>
        </div>
        {err && <p className="err">{err}</p>}
        <div className="patient-list">
          {rows.map((p) => {
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

      {selected ? <EHRReview key={selected.id} patient={selected} /> : (
        <section className="right empty-detail">
          <div><p className="hint-title">Open a patient file</p>
            <p className="hint">Sentinel pre-sifts each record against KDIGO 2024 and surfaces what a 10-minute visit would miss — then lets you act on it.</p></div>
        </section>
      )}
    </div>
  );
}
