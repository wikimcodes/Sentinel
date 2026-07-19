"""
Sentinel — deterministic clinical core (KDIGO 2024).

These are the tools the agent calls at runtime. Every number Sentinel outputs
originates here; the model orchestrates them but never invents a threshold.

Each public function is individually typed and testable, and is exposed to Claude
as a tool (see agent/tools.py). `review_patient` is the deterministic composition
of all of them — used as the eval's reference and as an offline fallback.

core/test_core.py cross-checks review_patient against the frozen gold patients (data/patients.json).
"""
from __future__ import annotations
import math
from datetime import date

# ---------------------------------------------------------------------------
# THRESHOLDS — the contract. Nothing here may live in the model.
# ---------------------------------------------------------------------------
RAPID_SLOPE = 5.0        # mL/min/1.73m^2 per year decline -> rapid progression
K_GATE = 5.5             # serum K+ > this gates RASi initiation / up-titration (§1.6)
FINERENONE_K_GATE = 5.0  # serum K+ > this: do NOT initiate finerenone (stricter, §4)
SGLT2_ACR = 200          # mg/g — SGLT2i albuminuria threshold (DAPA-CKD, 1A)
SGLT2_EGFR_2B = 45       # eGFR 20-45 with ACR<200 -> SGLT2i (2B)
ALBUMINURIA = 30         # mg/g — A2 / damage-marker threshold
A3 = 300                 # mg/g — A3 threshold
REFERRAL_ACR = 300       # mg/g — refer on A3 (severe albuminuria) per Wiki spec §referral
STATIN_AGE = 50
FINERENONE_EGFR = 25
KFRE_REFERRAL = 0.03     # 5-yr kidney-failure risk (Wiki spec: refer at 3-5%)
MG_G_PER_MG_MMOL = 8.84


# ---------------------------------------------------------------------------
# TOOL 1 — staging
# ---------------------------------------------------------------------------
def gfr_category(egfr: float) -> str:
    for lo, name in [(90, "G1"), (60, "G2"), (45, "G3a"), (30, "G3b"), (15, "G4")]:
        if egfr >= lo:
            return name
    return "G5"

def acr_category(acr: float) -> str:
    if acr < ALBUMINURIA:
        return "A1"
    return "A2" if acr <= A3 else "A3"

def risk_tier(gfr_cat: str, acr_cat: str) -> str:
    if gfr_cat in ("G1", "G2") and acr_cat == "A1":
        return "green"
    if (gfr_cat in ("G1", "G2") and acr_cat == "A2") or (gfr_cat == "G3a" and acr_cat == "A1"):
        return "yellow"
    if (gfr_cat in ("G1", "G2") and acr_cat == "A3") or (gfr_cat == "G3a" and acr_cat == "A2") \
            or (gfr_cat == "G3b" and acr_cat == "A1"):
        return "orange"
    return "red"

def stage_patient(egfr: float, acr: float) -> dict:
    """CGA staging + KDIGO risk tier from the latest eGFR and ACR."""
    g, a = gfr_category(egfr), acr_category(acr)
    return {"gfr_category": g, "acr_category": a, "stage": f"{g} {a}", "risk_tier": risk_tier(g, a)}


# ---------------------------------------------------------------------------
# TOOL 2 — CKD definition gate
# ---------------------------------------------------------------------------
def meets_ckd_definition(egfr: float, acr: float, haematuria: bool = False,
                         structural_marker: bool = False) -> bool:
    """CKD = eGFR<60 OR a damage marker persisting >=3 months. A single value is not CKD."""
    return egfr < 60 or acr >= ALBUMINURIA or bool(haematuria) or bool(structural_marker)


# ---------------------------------------------------------------------------
# TOOL 3 — trajectory
# ---------------------------------------------------------------------------
_CONFOUND_FLAGS = {"acute_illness", "trimethoprim_course", "low_muscle_mass"}

def steady_state(labs: list) -> list:
    return [l for l in labs if not (_CONFOUND_FLAGS & set(l.get("flags", [])))]

def egfr_trajectory(labs: list) -> dict:
    """Linear regression of eGFR over years on steady-state points. decline>0 => falling."""
    pts = sorted(steady_state(labs), key=lambda l: l["date"])
    if len(pts) < 2:
        return {"decline_per_year": None, "rapid": False, "n_steady": len(pts), "first": None, "last": None}
    t0 = date.fromisoformat(pts[0]["date"])
    xs = [(date.fromisoformat(l["date"]) - t0).days / 365.25 for l in pts]
    ys = [l["egfr"] for l in pts]
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return {"decline_per_year": None, "rapid": False, "n_steady": n, "first": pts[0], "last": pts[-1]}
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom
    decline = -slope
    return {"decline_per_year": decline, "rapid": decline >= RAPID_SLOPE,
            "n_steady": n, "first": pts[0], "last": pts[-1]}


# ---------------------------------------------------------------------------
# TOOL 4 — KFRE (4-variable, Tangri; N. American 5-yr calibration)
# ---------------------------------------------------------------------------
def kfre_5yr_risk(age: float, sex: str, egfr: float, acr_mg_g: float) -> float:
    acr_mmol = max(acr_mg_g / MG_G_PER_MG_MMOL, 0.1)
    male = 1 if sex == "M" else 0
    L = (-0.2201 * (age / 10 - 7.036)
         + 0.2467 * (male - 0.5642)
         - 0.5567 * (egfr / 5 - 7.222)
         + 0.4510 * (math.log(acr_mmol) - 5.137))
    return 1 - 0.9240 ** math.exp(L)


# ---------------------------------------------------------------------------
# TOOL 5 — medication gap / safety evaluation
# ---------------------------------------------------------------------------
def _on_class(meds, classes):
    return any(m["class"] in classes for m in meds)

def _cvd_risk(patient) -> bool:
    txt = " ".join(list(patient.get("problems", [])) + list(patient.get("comorbidities", []))).lower()
    return any(w in txt for w in ["myocardial", "ischaemic heart", "coronary", "stroke", "revascular"])

def evaluate_medications(patient: dict) -> list:
    """For each guideline drug return {drug, status, reason, [strength]}. status in
    {gap, gated, optimised, not_indicated, contraindicated, pending_cystatin}."""
    labs = sorted(patient["labs"], key=lambda l: l["date"])
    lab = labs[-1]
    egfr, acr, k = lab["egfr"], lab["acr_mg_g"], lab["potassium_mmol_l"]
    dm = patient["diabetes"]; age = patient["age"]; meds = patient["medications"]
    on_rasi = _on_class(meds, {"ACEi", "ARB"})
    ckd = meets_ckd_definition(egfr, acr, patient.get("haematuria"), patient.get("structural_marker"))
    a3 = acr >= A3
    pregnant = bool(patient.get("pregnant")); dialysis = bool(patient.get("dialysis"))
    egfr_unreliable = "low_muscle_mass" in set(lab.get("flags", []))
    out = []
    def add(drug, status, reason, **kw):
        out.append({"drug": drug, "status": status, "reason": reason, **kw})

    # RAS inhibitor — §1.1 strong/weak by diabetes x albuminuria
    rasi_strength = ("strong" if (a3 and not dm) or (acr >= ALBUMINURIA and dm)
                     else "weak" if (ALBUMINURIA <= acr < A3 and not dm) else None)
    if pregnant:
        add("RAS inhibitor", "contraindicated", "Fetotoxic — contraindicated in pregnancy (§1.2).")
    elif dialysis or rasi_strength is None:
        add("RAS inhibitor", "not_indicated",
            "Under dialysis care — not a between-visit gap." if dialysis
            else "A1 albuminuria — no RASi indication without a specific reason.")
    elif on_rasi:
        add("RAS inhibitor", "optimised", "Already on a RAS inhibitor.")
    elif egfr_unreliable:
        add("RAS inhibitor", "pending_cystatin", "Indicated, but eGFR unreliable (muscle mass) — confirm with cystatin C before acting.")
    elif k > K_GATE:
        add("RAS inhibitor", "gated", f"Indicated but gated on K+ {k} (> {K_GATE}).")
    else:
        add("RAS inhibitor", "gap",
            f"Albuminuric CKD ({'A3' if a3 else 'A2'}, {'diabetic' if dm else 'non-diabetic'}) — RAS inhibitor indicated, not prescribed.",
            strength=rasi_strength)

    # SGLT2 inhibitor — 1A (ACR>=200 / HF / T2D+CKD); 2B (eGFR 20-45)
    sglt2_ind = egfr >= 20 and (acr >= SGLT2_ACR or (dm and ckd) or patient.get("heart_failure") or egfr <= SGLT2_EGFR_2B)
    sglt2_weak = sglt2_ind and not (acr >= SGLT2_ACR or (dm and ckd) or patient.get("heart_failure"))
    if pregnant:
        add("SGLT2 inhibitor", "contraindicated", "Avoided in pregnancy (§1.2).")
    elif dialysis:
        add("SGLT2 inhibitor", "not_indicated", "Dialysis-dependent — not applicable.")
    elif not sglt2_ind:
        if ALBUMINURIA <= acr < SGLT2_ACR and not dm:
            add("SGLT2 inhibitor", "not_indicated", f"ACR {acr} (< {SGLT2_ACR}), non-diabetic, eGFR {egfr} > 45, no HF — not indicated.")
    elif _on_class(meds, {"SGLT2i"}):
        add("SGLT2 inhibitor", "optimised", "Already on an SGLT2 inhibitor.")
    elif egfr_unreliable:
        add("SGLT2 inhibitor", "pending_cystatin", "Indicated, but confirm true eGFR with cystatin C first.")
    else:
        add("SGLT2 inhibitor", "gap",
            (f"Albuminuric CKD (ACR {acr} >= {SGLT2_ACR}), eGFR {egfr} (>= 20)" if acr >= SGLT2_ACR
             else f"CKD, eGFR {egfr} (20-45, 2B)") + " — SGLT2 inhibitor indicated, not prescribed.",
            strength="weak" if sglt2_weak else "strong")

    # Finerenone (nsMRA) — T2D-gated, stricter K gate (§4)
    fin_ind = dm and ckd and acr >= ALBUMINURIA and on_rasi and egfr >= FINERENONE_EGFR
    if pregnant:
        add("finerenone", "contraindicated", "Avoided in pregnancy (§1.2).")
    elif not dm and acr >= ALBUMINURIA:
        add("finerenone", "not_indicated", "Non-diabetic — nsMRA is a T2D-gated indication; do NOT surface.")
    elif fin_ind and not dialysis:
        if _on_class(meds, {"nsMRA"}):
            add("finerenone", "optimised", "Already on finerenone.")
        elif k > FINERENONE_K_GATE:
            add("finerenone", "gated", f"Indicated but K+ {k} (> {FINERENONE_K_GATE}) — stricter nsMRA gate; treat potassium first.")
        else:
            add("finerenone", "gap", f"T2D + albuminuric CKD on RASi, K+ {k} normal, eGFR {egfr} (>= {FINERENONE_EGFR}) — finerenone indicated, not prescribed.")

    # Statin — age>=50 with CKD; 18-49 with CKD + a risk factor; not on dialysis
    statin_ind = ckd and (age >= STATIN_AGE or (18 <= age < STATIN_AGE and (dm or _cvd_risk(patient))))
    if pregnant:
        add("statin", "contraindicated", "Avoided in pregnancy (§1.2).")
    elif dialysis:
        add("statin", "not_indicated", "Dialysis-dependent — do not initiate a statin (KDIGO 2A).")
    elif statin_ind:
        if _on_class(meds, {"statin"}):
            add("statin", "optimised", "Already on a statin.")
        else:
            add("statin", "gap", f"CKD, age {age}{' + CV risk' if age < STATIN_AGE else ''} — statin indicated for CV-risk reduction, not prescribed.")
    return out


# ---------------------------------------------------------------------------
# TOOL 6 — referral
# ---------------------------------------------------------------------------
def referral_recommendation(patient: dict) -> dict:
    labs = sorted(patient["labs"], key=lambda l: l["date"])
    lab = labs[-1]
    egfr, acr = lab["egfr"], lab["acr_mg_g"]
    kfre = kfre_5yr_risk(patient["age"], patient["sex"], egfr, acr)
    rapid = egfr_trajectory(patient["labs"])["rapid"]
    if patient.get("dialysis"):    # already under specialist renal care
        return {"refer": False, "reasons": [], "kfre_5yr_pct": round(kfre * 100, 1)}
    reasons = []
    if egfr < 30: reasons.append(f"eGFR {egfr} < 30")
    if acr >= REFERRAL_ACR: reasons.append(f"severe albuminuria (ACR {acr} >= {REFERRAL_ACR} mg/g, A3)")
    if kfre >= KFRE_REFERRAL: reasons.append(f"KFRE 5-yr {kfre*100:.1f}% (>= 3%)")
    if rapid: reasons.append("sustained rapid progression")
    return {"refer": bool(reasons), "reasons": reasons, "kfre_5yr_pct": round(kfre * 100, 1)}


# ---------------------------------------------------------------------------
# COMPOSITION — the deterministic reference review (what the agent orchestrates)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Diagnosis coding — computed CKD stage -> standard clinical codes (SNOMED CT + ICD-10).
# SNOMED concept IDs should be validated against a terminology server (NHS TS /
# Ontoserver) before clinical use; open-ended codes resolve via FHIR $translate.
# ---------------------------------------------------------------------------
_GFR_CODES = {
    "G1":  ("431855005", "N18.1"),  "G2":  ("431856006", "N18.2"),
    "G3a": ("700378005", "N18.31"), "G3b": ("700379002", "N18.32"),
    "G4":  ("431857002", "N18.4"),  "G5":  ("433146000", "N18.5"),
}
def diagnosis_codes(egfr, acr, diabetes=False, hypertension=False):
    """Standard codes for the computed CKD diagnosis (SNOMED CT + ICD-10)."""
    g, a = gfr_category(egfr), acr_category(acr)
    out = []
    sn, icd = _GFR_CODES.get(g, (None, None))
    if sn:
        out.append({"label": f"Chronic kidney disease, stage {g[1:].upper()}", "snomed": sn, "icd10": icd})
    if a == "A2":
        out.append({"label": "Microalbuminuria", "snomed": "197655007", "icd10": "R80.9"})
    elif a == "A3":
        out.append({"label": "Severe albuminuria (macroalbuminuria)", "snomed": None, "icd10": "R80.9"})
    if diabetes:
        out.append({"label": "Type 2 diabetes with diabetic CKD", "snomed": None, "icd10": "E11.22"})
    if hypertension:
        out.append({"label": "Hypertension", "snomed": "38341003", "icd10": "I10"})
    return out


_PROVISIONAL_MARKERS = ("no prior baseline", "first abnormal", "provisional", "no baseline", "unconfirmed")

def chronicity_unconfirmed(patient: dict, labs: list) -> bool:
    """KDIGO defines CKD as an abnormality that persists >=3 months. A first abnormal
    result with no prior baseline is provisional — you repeat to confirm chronicity
    before diagnosing or starting treatment. True only when the record is explicitly a
    first/baseline-less result AND has no longitudinal confirmation (no two reliable
    abnormal points >=3 months apart), so established multi-visit patients are unaffected."""
    ctx = " ".join(str(x).lower() for x in
                   list(patient.get("problems", [])) + list(patient.get("comorbidities", [])))
    if not any(m in ctx for m in _PROVISIONAL_MARKERS):
        return False
    reliable = [l for l in labs if not (_CONFOUND_FLAGS & set(l.get("flags", [])))]
    if len(reliable) < 2:
        return True
    ds = sorted(date.fromisoformat(l["date"]) for l in reliable)
    return (ds[-1] - ds[0]).days < 90


def review_patient(patient: dict) -> dict:
    """Full between-visit review: {ckd, stage, risk_tier, surface, suppress, kfre_5yr_pct, codes}.
    Surface/suppress items are (type, drug|item) — the eval compares on those keys."""
    labs = sorted(patient["labs"], key=lambda l: l["date"])
    lab = labs[-1]
    egfr, acr, k = lab["egfr"], lab["acr_mg_g"], lab["potassium_mmol_l"]
    hyp = any("hypertension" in str(x).lower() for x in patient.get("problems", []) + patient.get("comorbidities", []))
    codes = diagnosis_codes(egfr, acr, patient["diabetes"], hyp)

    if not meets_ckd_definition(egfr, acr, patient.get("haematuria"), patient.get("structural_marker")):
        g, a = gfr_category(egfr), acr_category(acr)
        return {"ckd": False, "stage": None, "risk_tier": None, "surface": [], "codes": [],
                "suppress": [{"type": "not_ckd", "item": "patient",
                              "reason": f"{g} {a} with no damage marker — does not meet the CKD definition gate."}],
                "kfre_5yr_pct": round(kfre_5yr_risk(patient["age"], patient["sex"], egfr, acr) * 100, 1)}

    st = stage_patient(egfr, acr)
    kfre_pct = round(kfre_5yr_risk(patient["age"], patient["sex"], egfr, acr) * 100, 1)

    # Pregnancy: all CKD pharmacotherapy contraindicated; joint obstetric-nephrology referral.
    if patient.get("pregnant"):
        surface = [{"type": "referral", "priority": 1,
                    "summary": "Refer for joint obstetric-nephrology care — all CKD pharmacotherapy (RASi, SGLT2i, statin, finerenone) is contraindicated in pregnancy."}]
        suppress = [{"type": "not_indicated", "item": m["drug"], "reason": m["reason"]}
                    for m in evaluate_medications(patient) if m["status"] == "contraindicated"]
        return {"ckd": True, "stage": st["stage"], "risk_tier": st["risk_tier"], "codes": codes,
                "surface": surface, "suppress": suppress, "kfre_5yr_pct": kfre_pct}

    # Chronicity gate: a first abnormal result with no prior baseline is provisional.
    # KDIGO needs >=3-month persistence — repeat to confirm before diagnosing or treating,
    # so no medication is started on a single unconfirmed result.
    if chronicity_unconfirmed(patient, labs):
        surface = [{"type": "monitor", "priority": 1,
                    "summary": (f"Abnormal kidney indices ({st['stage']}) on a first result with no prior baseline. "
                                "KDIGO requires >=3-month persistence — repeat eGFR and ACR to confirm chronicity "
                                "before any diagnosis or treatment. Monitoring, not a treatment action.")}]
        suppress = [{"type": "provisional_defer", "item": m["drug"],
                     "reason": "CKD unconfirmed on a single result — do not start on a provisional diagnosis; "
                               "confirm >=3-month persistence first."}
                    for m in evaluate_medications(patient) if m["status"] in ("gap", "gated")]
        return {"ckd": "unconfirmed", "stage": st["stage"] + " (provisional)", "risk_tier": st["risk_tier"],
                "codes": codes, "surface": surface, "suppress": suppress, "kfre_5yr_pct": kfre_pct}

    surface, suppress = [], []

    # confounder suppressions
    flags = set().union(*[set(l.get("flags", [])) for l in labs]) if labs else set()
    if "acute_illness" in flags:
        acute = [l for l in labs if "acute_illness" in l.get("flags", [])]
        suppress.append({"type": "non_steady_state", "item": f"eGFR dip on {acute[0]['date']}",
                         "reason": "Coincided with acute illness — non-steady-state, not progression."})
        if lab not in acute:
            suppress.append({"type": "resolved_aki", "item": "trajectory",
                             "reason": "Nadir recovered to baseline — trajectory stable."})
    if "trimethoprim_course" in flags:
        suppress.append({"type": "pseudo_rise", "item": "creatinine rise on trimethoprim",
                         "reason": "Trimethoprim blocks tubular creatinine secretion — pseudo-rise. Confirm with cystatin C if persists."})
    if "low_muscle_mass" in flags:
        suppress.append({"type": "egfr_failure_mode", "item": f"eGFR {egfr}",
                         "reason": "Low muscle mass — creatinine-based eGFR overestimates true GFR. Confirm with cystatin C."})

    # trajectory
    traj = egfr_trajectory(labs)
    if traj["rapid"]:
        f, l = traj["first"], traj["last"]
        yrs = (date.fromisoformat(l["date"]) - date.fromisoformat(f["date"])).days / 365.25
        surface.append({"type": "trajectory", "priority": 1,
                        "summary": f"eGFR {f['egfr']} -> {l['egfr']} over {yrs:.0f}y (~{traj['decline_per_year']:.1f} mL/min/yr) — sustained rapid progression, now {st['stage']}."})
    elif traj["decline_per_year"] is not None and st["risk_tier"] in ("orange", "red") and traj["n_steady"] >= 3:
        suppress.append({"type": "no_progression", "item": "trajectory",
                         "reason": f"Slope ~{traj['decline_per_year']:.1f} mL/min/yr — below rapid threshold ({RAPID_SLOPE}). Stable."})

    # medications
    for m in evaluate_medications(patient):
        s = m["status"]
        if s == "gap":
            item = {"type": "gap", "drug": m["drug"], "priority": 2 if m["drug"] != "statin" else 3,
                    "summary": m["reason"]}
            if "strength" in m: item["strength"] = m["strength"]
            surface.append(item)
        elif s == "gated":
            surface.append({"type": "gap_gated", "drug": m["drug"], "priority": 1, "summary": m["reason"]})
            suppress.append({"type": "gated_hold", "item": m["drug"], "reason": m["reason"]})
        elif s == "optimised":
            suppress.append({"type": "already_optimised", "item": m["drug"], "reason": m["reason"]})
        elif s == "pending_cystatin":
            suppress.append({"type": "gated_hold", "item": m["drug"], "reason": m["reason"]})
        elif s in ("not_indicated", "contraindicated"):
            suppress.append({"type": "not_indicated", "item": m["drug"], "reason": m["reason"]})

    # hyperkalaemia as a first-class safety item
    if k >= K_GATE:
        surface.append({"type": "safety", "item": "hyperkalaemia", "priority": 1,
                        "summary": f"K+ {k} (>= {K_GATE}) — address before adding a nsMRA or up-titrating RASi."})

    # referral
    ref = referral_recommendation(patient)
    if ref["refer"]:
        surface.append({"type": "referral", "priority": 3,
                        "summary": "Draft nephrology referral — trigger: " + "; ".join(ref["reasons"]) + f". (KFRE 5-yr {ref['kfre_5yr_pct']}%.)"})
    elif st["risk_tier"] in ("orange", "red"):
        suppress.append({"type": "no_referral", "item": "referral",
                         "reason": f"No referral criterion met (KFRE {ref['kfre_5yr_pct']}%) — do not escalate."})

    surface.sort(key=lambda s: s.get("priority", 9))
    return {"ckd": True, "stage": st["stage"], "risk_tier": st["risk_tier"], "codes": codes,
            "surface": surface, "suppress": suppress, "kfre_5yr_pct": ref["kfre_5yr_pct"]}
