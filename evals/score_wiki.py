"""
Measure Sentinel's deterministic core against Wiki's 50-patient golden set
(docs/sentinel_demo_patients_50). Wiki's schema differs from ours, so we adapt each
record to the core's input, run core.review_patient, normalise both sides to a
comparable set of clinical findings, and score precision/recall/F1 + staging.

    .venv/bin/python evals/score_wiki.py          # summary
    .venv/bin/python evals/score_wiki.py -v       # + per-patient divergences

No API calls — this scores the deterministic core (the agent orchestrates the same core).
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "core"))
import clinical_core as core

WIKI = json.load(open(os.path.join(HERE, "..", "docs", "sentinel_demo_patients_50")))["patients"]
VERBOSE = "-v" in sys.argv

MED_CLASS = {
    "ramipril": "ACEi", "lisinopril": "ACEi", "enalapril": "ACEi", "perindopril": "ACEi",
    "losartan": "ARB", "candesartan": "ARB", "valsartan": "ARB", "irbesartan": "ARB",
    "dapagliflozin": "SGLT2i", "empagliflozin": "SGLT2i",
    "finerenone": "nsMRA",
    "atorvastatin": "statin", "simvastatin": "statin", "rosuvastatin": "statin",
    "amlodipine": "CCB", "furosemide": "loop", "metformin": "biguanide", "insulin": "insulin",
    "trimethoprim": "antibiotic", "cimetidine": "h2",
}

def adapt(wp):
    ctx = " ".join(wp.get("context", [])).lower()
    labs = []
    for l in sorted(wp["labs"], key=lambda x: x["date"]):
        d = l["date"] + "-01" if len(l["date"]) == 7 else l["date"]
        lab = {"date": d, "egfr": l["eGFR"], "acr_mg_g": l["ACR"], "potassium_mmol_l": l["K"]}
        if l.get("acute"):
            lab["flags"] = ["acute_illness"]
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

def toks(text):
    t = text.lower(); return {k for k, kws in KW.items() if any(w in t for w in kws)}

def wiki_tokens(wp):
    e = wp["expected"]; out = set()
    for s in e.get("surface", []): out |= toks(s.get("finding", ""))
    for a in e.get("proposed_actions", []):
        if a.get("type") == "draft_referral": out.add("referral")
        elif a.get("type") != "order_lab": out |= toks(a.get("detail", ""))
    tj = e.get("trajectory", "").lower()
    if "rapid" in tj and not any(x in tj for x in ["sub-rapid", "not rapid", "no rapid", "non-rapid"]):
        out.add("trajectory")
    return out

def core_tokens(p):
    r = core.review_patient(p); out = set()
    for s in r["surface"]:
        if s["type"] in ("gap", "gap_gated"):
            d = (s.get("drug") or "").lower()
            out.add("sglt2" if "sglt2" in d else "rasi" if "ras" in d else
                    "finerenone" if "finerenone" in d else "statin" if "statin" in d else "?")
        elif s["type"] == "trajectory": out.add("trajectory")
        elif s["type"] == "referral": out.add("referral")
    for s in r["suppress"]:
        if s["type"] in ("egfr_failure_mode", "pseudo_rise"): out.add("cystatin")
    return out, r

TP = FP = FN = stage_ok = ckd_ok = 0
mism = []
for wp in WIKI:
    p = adapt(wp)
    ct, r = core_tokens(p)
    wt = wiki_tokens(wp)
    tp, fp, fn = ct & wt, ct - wt, wt - ct
    TP += len(tp); FP += len(fp); FN += len(fn)
    exp = wp["expected"]
    ckd_ok += (r["ckd"] == exp.get("is_ckd"))
    stage_ok += (str(r["stage"]) == str(exp.get("stage")))
    if fp or fn:
        mism.append((wp["id"], sorted(fp), sorted(fn),
                     " ".join(wp.get("context", []))[:38]))

prec = TP / (TP + FP) if TP + FP else 1.0
rec = TP / (TP + FN) if TP + FN else 1.0
f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
n = len(WIKI)
print(f"\n╔═══ Sentinel core vs Wiki golden set — n={n} ═══")
print(f"  Finding precision   {prec*100:5.1f}%   (of what core surfaced, how much Wiki agrees)")
print(f"  Finding recall      {rec*100:5.1f}%   (of Wiki's findings, how much core caught)")
print(f"  Finding F1          {f1*100:5.1f}%")
print(f"  Staging accuracy    {stage_ok/n*100:5.1f}%   ({stage_ok}/{n})")
print(f"  CKD-gate accuracy   {ckd_ok/n*100:5.1f}%   ({ckd_ok}/{n})")
print(f"  divergent patients  {len(mism)}/{n}")
if VERBOSE:
    print("\n  id            core-extra (FP)          missed (FN)              context")
    print("  " + "-" * 92)
    for i, (pid, fp, fn, ctx) in enumerate(mism):
        print(f"  {pid:13} {str(fp):24} {str(fn):24} {ctx}")
print()
