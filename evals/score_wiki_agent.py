"""
The definitive eval: the LIVE Claude agent (real tool-calling over the core) scored
against Wiki's clinician golden set (docs/sentinel_demo_patients_50), with the
deterministic core as a comparison row.

    .venv/bin/python evals/score_wiki_agent.py         # all 50 (≈50 Claude calls)
    .venv/bin/python evals/score_wiki_agent.py 8       # first 8 (smoke test)

Requires anthropic + ANTHROPIC_API_KEY (loaded from .env by review_agent).
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "core"))
sys.path.insert(0, os.path.join(HERE, "..", "agent"))
import clinical_core as core
import review_agent

WIKI = json.load(open(os.path.join(HERE, "..", "docs", "sentinel_demo_patients_50")))["patients"]
limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(WIKI)
WIKI = WIKI[:limit]

MED_CLASS = {"ramipril": "ACEi", "lisinopril": "ACEi", "enalapril": "ACEi", "perindopril": "ACEi",
             "losartan": "ARB", "candesartan": "ARB", "valsartan": "ARB", "irbesartan": "ARB",
             "dapagliflozin": "SGLT2i", "empagliflozin": "SGLT2i", "finerenone": "nsMRA",
             "atorvastatin": "statin", "simvastatin": "statin", "rosuvastatin": "statin",
             "amlodipine": "CCB", "furosemide": "loop", "metformin": "biguanide", "insulin": "insulin",
             "trimethoprim": "antibiotic", "cimetidine": "h2"}

def adapt(wp):
    ctx = " ".join(wp.get("context", [])).lower()
    labs = []
    for l in sorted(wp["labs"], key=lambda x: x["date"]):
        d = l["date"] + "-01" if len(l["date"]) == 7 else l["date"]
        lab = {"date": d, "egfr": l["eGFR"], "acr_mg_g": l["ACR"], "potassium_mmol_l": l["K"],
               "creatinine_mg_dl": round(0.9 * 75 / max(l["eGFR"], 5), 2)}
        if l.get("acute"): lab["flags"] = ["acute_illness"]
        labs.append(lab)
    latest = labs[-1]; lf = set(latest.get("flags", []))
    if any(w in ctx for w in ["trimethoprim", "cimetidine"]): lf.add("trimethoprim_course")
    if any(w in ctx for w in ["muscle mass", "amputation", "frail", "bodybuilder", "cachex"]): lf.add("low_muscle_mass")
    if lf: latest["flags"] = list(lf)
    p = {"id": wp["id"], "age": wp["demographics"]["age"], "sex": wp["demographics"]["sex"],
         "diabetes": wp["demographics"]["diabetes"], "problems": wp.get("context", []),
         "labs": labs, "medications": [{"name": m, "class": MED_CLASS.get(m, "other")} for m in wp["medications"]]}
    if "haematuria" in ctx: p["haematuria"] = True
    if "heart failure" in ctx or "hfref" in ctx: p["heart_failure"] = True
    if "pregnant" in ctx: p["pregnant"] = True
    if "dialysis" in ctx or "haemodialysis" in ctx: p["dialysis"] = True
    return p

KW = {"sglt2": ["sglt2"], "rasi": ["ras inhibitor", "acei", "arb", "rasi"],
      "finerenone": ["finerenone", "nonsteroidal mra", "nsmra"], "statin": ["statin"],
      "referral": ["referral", "nephrology"], "cystatin": ["cystatin", "muscle mass", "overestimat", "underestimat"]}
def kw_toks(text):
    t = text.lower(); return {k for k, kws in KW.items() if any(w in t for w in kws)}

def wiki_tokens(wp):
    e = wp["expected"]; out = set()
    for s in e.get("surface", []): out |= kw_toks(s.get("finding", ""))
    for a in e.get("proposed_actions", []):
        if a.get("type") == "draft_referral": out.add("referral")
        elif a.get("type") != "order_lab": out |= kw_toks(a.get("detail", ""))
    tj = e.get("trajectory", "").lower()
    if "rapid" in tj and not any(x in tj for x in ["sub-rapid", "not rapid", "no rapid", "non-rapid"]): out.add("trajectory")
    return out

def tokens_of(surface, suppress):
    """Normalise a {surface, suppress} result (core OR agent — same shape) to findings."""
    out = set()
    for s in surface:
        t = s.get("type"); d = (s.get("drug") or "").lower()
        if t in ("gap", "gap_gated"):
            out.add("sglt2" if "sglt2" in d else "rasi" if "ras" in d else
                    "finerenone" if "finerenone" in d else "statin" if "statin" in d else "?")
        elif t == "trajectory": out.add("trajectory")
        elif t == "referral": out.add("referral")
    for s in suppress:
        if s.get("type") in ("egfr_failure_mode", "pseudo_rise"): out.add("cystatin")
    return out

def prf(pairs):
    TP = sum(len(a & b) for a, b in pairs)
    FP = sum(len(a - b) for a, b in pairs)
    FN = sum(len(b - a) for a, b in pairs)
    p = TP / (TP + FP) if TP + FP else 1.0
    r = TP / (TP + FN) if TP + FN else 1.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)

core_pairs, agent_pairs = [], []
for i, wp in enumerate(WIKI):
    p = adapt(wp)
    wt = wiki_tokens(wp)
    r = core.review_patient(p)
    core_pairs.append((tokens_of(r["surface"], r["suppress"]), wt))
    sys.stderr.write(f"  [{i+1}/{len(WIKI)}] live agent reviewing {wp['id']} ...\n"); sys.stderr.flush()
    ag = review_agent.run_review(wp["id"], patient=p)
    agent_pairs.append((tokens_of(ag["surface"], ag["suppress"]), wt))

cp, cr, cf = prf(core_pairs)
ap, ar, af = prf(agent_pairs)
print(f"\n╔═══ Sentinel vs Wiki clinician golden set — n={len(WIKI)} ═══")
print(f"  {'':<34}{'precision':>11}{'recall':>10}{'F1':>9}")
print("  " + "-" * 64)
print(f"  {'Deterministic core':<34}{cp*100:>10.1f}%{cr*100:>9.1f}%{cf*100:>8.1f}%")
print(f"  {'LIVE Claude agent (tool-calling)':<34}{ap*100:>10.1f}%{ar*100:>9.1f}%{af*100:>8.1f}%")
print("  " + "-" * 64)
print("  Agent orchestrates the same core tools; the gap between the rows is agent overhead/error.\n")
