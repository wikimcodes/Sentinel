"""
Sentinel — deterministic clinical core (KDIGO 2024).

These are the tools the agent calls at runtime. Every number Sentinel outputs
originates here; the model orchestrates them but never invents a threshold.

Each public function is individually typed and testable, and is exposed to Claude
as a tool (see agent/tools.py). `review_patient` is the deterministic composition
of all of them — used as the eval's reference and as an offline fallback.

This is a SEPARATE implementation from the eval oracle in data/generate_patients.py;
core/test_core.py cross-checks the two agree on all 50 gold patients.
"""
from __future__ import annotations
import math
from datetime import date

# ---------------------------------------------------------------------------
# THRESHOLDS — the contract. Nothing here may live in the model.
# ---------------------------------------------------------------------------
RAPID_SLOPE = 5.0        # mL/min/1.73m^2 per year decline -> rapid progression
K_GATE = 5.5             # serum K+ >= this gates RASi up-titration / nsMRA start
SGLT2_ACR = 200          # mg/g — SGLT2i albuminuria threshold (DAPA-CKD)
ALBUMINURIA = 30         # mg/g — A2 / damage-marker threshold
A3 = 300                 # mg/g — A3 threshold
REFERRAL_ACR = 620       # mg/g ~= 70 mg/mmol (NICE NG203 heavy-albuminuria referral)
STATIN_AGE = 50
FINERENONE_EGFR = 25
KFRE_REFERRAL = 0.05     # 5-yr kidney-failure risk
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

def evaluate_medications(patient: dict) -> list:
    """For each guideline drug return {drug, status, reason}. status in
    {gap, gated, optimised, not_indicated}."""
    labs = sorted(patient["labs"], key=lambda l: l["date"])
    lab = labs[-1]
    egfr, acr, k = lab["egfr"], lab["acr_mg_g"], lab["potassium_mmol_l"]
    dm = patient["diabetes"]; age = patient["age"]; meds = patient["medications"]
    on_rasi = _on_class(meds, {"ACEi", "ARB"})
    ckd = meets_ckd_definition(egfr, acr, patient.get("haematuria"), patient.get("structural_marker"))
    out = []

    def classify(drug, indicated, already, gate_blocked, not_ind_reason=None):
        if indicated and already:
            out.append({"drug": drug, "status": "optimised", "reason": f"Already on {drug}."})
        elif indicated and gate_blocked:
            out.append({"drug": drug, "status": "gated", "reason": f"Indicated but gated on K+ {k} (>= {K_GATE})."})
        elif indicated:
            out.append({"drug": drug, "status": "gap", "reason": f"{drug} indicated and not prescribed."})
        elif not_ind_reason:
            out.append({"drug": drug, "status": "not_indicated", "reason": not_ind_reason})

    # RAS inhibitor
    classify("RAS inhibitor", acr >= ALBUMINURIA, on_rasi,
             acr >= ALBUMINURIA and not on_rasi and k >= K_GATE)
    # SGLT2 inhibitor
    sglt2_ind = egfr >= 20 and (acr >= SGLT2_ACR or (dm and ckd) or patient.get("heart_failure"))
    classify("SGLT2 inhibitor", sglt2_ind, _on_class(meds, {"SGLT2i"}), False,
             not_ind_reason=(f"ACR {acr} (< {SGLT2_ACR}), non-diabetic, no HF — not indicated."
                             if ALBUMINURIA <= acr < SGLT2_ACR and not dm else None))
    # Finerenone (nsMRA) — diabetes-gated
    fin_ind = dm and ckd and acr >= ALBUMINURIA and on_rasi and egfr >= FINERENONE_EGFR
    classify("finerenone", fin_ind, _on_class(meds, {"nsMRA"}),
             fin_ind and not _on_class(meds, {"nsMRA"}) and k >= K_GATE,
             not_ind_reason=("Non-diabetic — nsMRA is a T2D-gated indication; do NOT surface."
                             if (not dm and acr >= ALBUMINURIA) else None))
    # Statin
    classify("statin", age >= STATIN_AGE and ckd, _on_class(meds, {"statin"}), False)
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
    reasons = []
    if egfr < 30: reasons.append(f"eGFR {egfr} < 30")
    if acr >= REFERRAL_ACR: reasons.append(f"ACR {acr} >= {REFERRAL_ACR} mg/g")
    if kfre >= KFRE_REFERRAL: reasons.append(f"KFRE 5-yr {kfre*100:.1f}% >= 5%")
    if rapid: reasons.append("sustained rapid progression")
    return {"refer": bool(reasons), "reasons": reasons, "kfre_5yr_pct": round(kfre * 100, 1)}


# ---------------------------------------------------------------------------
# COMPOSITION — the deterministic reference review (what the agent orchestrates)
# ---------------------------------------------------------------------------
def review_patient(patient: dict) -> dict:
    """Full between-visit review: {ckd, stage, risk_tier, surface, suppress, kfre_5yr_pct}.
    Surface/suppress items are (type, drug|item) — the eval compares on those keys."""
    labs = sorted(patient["labs"], key=lambda l: l["date"])
    lab = labs[-1]
    egfr, acr, k = lab["egfr"], lab["acr_mg_g"], lab["potassium_mmol_l"]

    if not meets_ckd_definition(egfr, acr, patient.get("haematuria"), patient.get("structural_marker")):
        g, a = gfr_category(egfr), acr_category(acr)
        return {"ckd": False, "stage": None, "risk_tier": None, "surface": [],
                "suppress": [{"type": "not_ckd", "item": "patient",
                              "reason": f"{g} {a} with no damage marker — does not meet the CKD definition gate."}]}

    st = stage_patient(egfr, acr)
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
        if m["status"] == "gap":
            surface.append({"type": "gap", "drug": m["drug"], "priority": 2 if m["drug"] != "statin" else 3,
                            "summary": m["reason"]})
        elif m["status"] == "gated":
            surface.append({"type": "gap_gated", "drug": m["drug"], "priority": 1, "summary": m["reason"]})
            suppress.append({"type": "gated_hold", "item": m["drug"], "reason": m["reason"]})
        elif m["status"] == "optimised":
            suppress.append({"type": "already_optimised", "item": m["drug"], "reason": m["reason"]})
        elif m["status"] == "not_indicated":
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
    return {"ckd": True, "stage": st["stage"], "risk_tier": st["risk_tier"],
            "surface": surface, "suppress": suppress, "kfre_5yr_pct": ref["kfre_5yr_pct"]}
