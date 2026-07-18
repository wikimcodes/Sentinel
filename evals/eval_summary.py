"""
Eval summary for the app's Eval tab. Computes — live and deterministically — how a
naive rule engine and Sentinel's core score against Wiki's clinician golden set, and
carries the (expensive, pre-measured) live-Claude-agent result.

compute() returns a JSON-able dict the /api/evals endpoint serves.
"""
import json, os, sys, re
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "core"))
import clinical_core as core

_STAGE_RE = re.compile(r"G[1-5][ab]?|A[1-3]", re.I)
def _norm_stage(s):
    """Canonical 'G# A#' token. Wiki authors annotate a stage with clinical
    caveats — 'G3b A2 (provisional, unconfirmed)', 'G3a A2 (face value,
    creatinine-based)'. The stage is identical; only the note differs. Compare
    on the KDIGO token so an annotated stage isn't scored as a staging error."""
    return " ".join(m.group(0).upper() for m in _STAGE_RE.finditer(str(s or "")))

def _stage_match(review, exp):
    """Staging agreement. If both the core and the reference agree the patient is
    not CKD, there is no CKD to stage — that is agreement, not a staging error
    (the CKD determination is scored separately as CKD-gate accuracy). Otherwise
    compare on the normalised KDIGO token."""
    if not review["ckd"] and not exp.get("is_ckd"):
        return True
    return _norm_stage(review["stage"]) == _norm_stage(exp.get("stage"))

WIKI = json.load(open(os.path.join(HERE, "..", "docs", "sentinel_demo_patients_50")))["patients"]

MED_CLASS = {"ramipril": "ACEi", "lisinopril": "ACEi", "enalapril": "ACEi", "perindopril": "ACEi",
             "losartan": "ARB", "candesartan": "ARB", "valsartan": "ARB", "irbesartan": "ARB",
             "dapagliflozin": "SGLT2i", "empagliflozin": "SGLT2i", "finerenone": "nsMRA",
             "atorvastatin": "statin", "simvastatin": "statin", "rosuvastatin": "statin",
             "amlodipine": "CCB", "furosemide": "loop", "metformin": "biguanide", "insulin": "insulin",
             "trimethoprim": "antibiotic", "cimetidine": "h2"}
KW = {"sglt2": ["sglt2"], "rasi": ["ras inhibitor", "acei", "arb", "rasi"],
      "finerenone": ["finerenone", "nonsteroidal mra", "nsmra"], "statin": ["statin"],
      "referral": ["referral", "nephrology"], "cystatin": ["cystatin", "muscle mass", "overestimat", "underestimat"]}

# Pre-measured on 50 live Claude tool-calling runs (evals/score_wiki_agent.py).
AGENT_MEASURED = {"precision": 91.7, "recall": 88.0, "f1": 89.8}


def adapt(wp):
    ctx = " ".join(wp.get("context", [])).lower()
    labs = []
    for l in sorted(wp["labs"], key=lambda x: x["date"]):
        d = l["date"] + "-01" if len(l["date"]) == 7 else l["date"]
        lab = {"date": d, "egfr": l["eGFR"], "acr_mg_g": l["ACR"], "potassium_mmol_l": l["K"]}
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

def wiki_tokens(wp):
    def kw(t): tl = t.lower(); return {k for k, ws in KW.items() if any(w in tl for w in ws)}
    e = wp["expected"]; out = set()
    for s in e.get("surface", []): out |= kw(s.get("finding", ""))
    for a in e.get("proposed_actions", []):
        if a.get("type") == "draft_referral": out.add("referral")
        elif a.get("type") != "order_lab": out |= kw(a.get("detail", ""))
    tj = e.get("trajectory", "").lower()
    if "rapid" in tj and not any(x in tj for x in ["sub-rapid", "not rapid", "no rapid", "non-rapid"]): out.add("trajectory")
    return out

def core_tokens(p):
    r = core.review_patient(p); out = set()
    for s in r["surface"]:
        t = s.get("type"); d = (s.get("drug") or "").lower()
        if t in ("gap", "gap_gated"):
            out.add("sglt2" if "sglt2" in d else "rasi" if "ras" in d else
                    "finerenone" if "finerenone" in d else "statin" if "statin" in d else "?")
        elif t == "trajectory": out.add("trajectory")
        elif t == "referral": out.add("referral")
    for s in r["suppress"]:
        if s.get("type") in ("egfr_failure_mode", "pseudo_rise"): out.add("cystatin")
    return out

def naive_tokens(p):
    """A rule engine with no suppression, no contraindication, no gating — it over-fires."""
    labs = sorted(p["labs"], key=lambda l: l["date"]); lab = labs[-1]
    egfr, acr, dm, age = lab["egfr"], lab["acr_mg_g"], p["diabetes"], p["age"]
    on = {m["class"] for m in p["medications"]}; out = set()
    if acr >= 30 and not (on & {"ACEi", "ARB"}): out.add("rasi")
    if (acr >= 30 or egfr < 60) and "SGLT2i" not in on: out.add("sglt2")
    if dm and acr >= 30 and "nsMRA" not in on: out.add("finerenone")
    if (age >= 50 or egfr < 60) and "statin" not in on: out.add("statin")
    if egfr < 60 or acr >= 30: out.add("referral")
    if labs[0]["egfr"] > lab["egfr"]: out.add("trajectory")
    return out

def _prf(pairs):
    TP = sum(len(a & b) for a, b in pairs); FP = sum(len(a - b) for a, b in pairs); FN = sum(len(b - a) for a, b in pairs)
    p = TP / (TP + FP) if TP + FP else 1.0
    r = TP / (TP + FN) if TP + FN else 1.0
    return {"precision": round(p * 100, 1), "recall": round(r * 100, 1),
            "f1": round((2 * p * r / (p + r) if p + r else 0) * 100, 1),
            "false_alarm": round((1 - p) * 100, 1)}

def compute():
    adapted = [adapt(wp) for wp in WIKI]
    golds = [wiki_tokens(wp) for wp in WIKI]
    naive = _prf([(naive_tokens(p), g) for p, g in zip(adapted, golds)])
    core_m = _prf([(core_tokens(p), g) for p, g in zip(adapted, golds)])
    stage_ok = sum(_stage_match(core.review_patient(p), wp["expected"])
                   for p, wp in zip(adapted, WIKI))
    ckd_ok = sum(core.review_patient(p)["ckd"] == wp["expected"].get("is_ckd") for p, wp in zip(adapted, WIKI))
    n = len(WIKI)
    return {
        "n": n,
        "against": "Wiki's clinician-authored golden set (50 synthetic CKD patients)",
        "rows": [
            {"name": "Naive rule engine", "sub": "if-statements, no suppression", **naive, "tone": "bad"},
            {"name": "Sentinel — deterministic core", "sub": "KDIGO logic, computed live now", **core_m, "tone": "good"},
            {"name": "Sentinel — live Claude agent", "sub": "50 real tool-calling runs (pre-measured)",
             **AGENT_MEASURED, "false_alarm": round(100 - AGENT_MEASURED["precision"], 1),
             "tone": "good", "measured": True},
        ],
        "staging_accuracy": round(stage_ok / n * 100, 1),
        "ckd_gate_accuracy": round(ckd_ok / n * 100, 1),
        "false_alarm": {"naive": naive["false_alarm"], "sentinel": core_m["false_alarm"]},
    }

if __name__ == "__main__":
    print(json.dumps(compute(), indent=2))
