"""
Sentinel — gold patient generator + clinical oracle.

Builds data/patients.json: 50 synthetic CKD patients, each tagged with
persona / job-to-be-done / eval-category / difficulty, plus a ground-truth
`expected` block (what MUST surface, what MUST be suppressed).

The `expected` blocks are produced by the CLINICAL ORACLE below — a transparent,
human-reviewable reference implementation of KDIGO 2024 logic. It is deliberately
SEPARATE from core/ (the deterministic tools the agent calls at runtime), so the
eval scores the agent against independent ground truth rather than itself.

No real PHI. All patients synthetic. Reproducible (seeded).
"""
import json, math, os, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ANCHORS_FILE = os.path.join(HERE, "gold_patients.json")
OUT_FILE = os.path.join(HERE, "patients.json")

# ---------------------------------------------------------------------------
# THRESHOLDS (single source of truth — nothing lives in the model)
# ---------------------------------------------------------------------------
RAPID_SLOPE = 5.0          # mL/min/1.73m^2 per year decline -> rapid progression
K_GATE = 5.5               # serum K+ >= this gates RASi up-titration / nsMRA start
SGLT2_ACR = 200            # mg/g: SGLT2i albuminuria threshold (DAPA-CKD)
ALBUMINURIA = 30           # mg/g: A2 threshold / damage marker
A3 = 300                   # mg/g: A3 threshold
REFERRAL_ACR = 620         # mg/g ~= 70 mg/mmol (NICE NG203 heavy-albuminuria referral)
STATIN_AGE = 50
FINERENONE_EGFR = 25
KFRE_REFERRAL = 0.05       # 5-yr kidney-failure risk

MG_G_PER_MG_MMOL = 8.84    # ACR unit conversion


# ---------------------------------------------------------------------------
# CLINICAL ORACLE  (reference ground truth)
# ---------------------------------------------------------------------------
def gfr_cat(egfr):
    if egfr >= 90: return "G1"
    if egfr >= 60: return "G2"
    if egfr >= 45: return "G3a"
    if egfr >= 30: return "G3b"
    if egfr >= 15: return "G4"
    return "G5"

def acr_cat(acr):
    if acr < ALBUMINURIA: return "A1"
    if acr <= A3: return "A2"
    return "A3"

def risk_tier(g, a):
    if g in ("G1", "G2") and a == "A1": return "green"
    if (g in ("G1", "G2") and a == "A2") or (g == "G3a" and a == "A1"): return "yellow"
    if (g in ("G1", "G2") and a == "A3") or (g == "G3a" and a == "A2") or (g == "G3b" and a == "A1"): return "orange"
    return "red"  # G3a+A3, G3b+A2/A3, all G4/G5

def latest(labs):
    return sorted(labs, key=lambda l: l["date"])[-1]

def steady_state(labs):
    """Points usable for trajectory: exclude acute illness / drug-confounded / low-muscle."""
    bad = {"acute_illness", "trimethoprim_course", "low_muscle_mass"}
    return [l for l in labs if not (bad & set(l.get("flags", [])))]

def fit_slope(labs):
    """Linear regression of eGFR over years on steady-state points. Returns decline (+ve = falling)."""
    pts = steady_state(labs)
    if len(pts) < 2:
        return None
    pts = sorted(pts, key=lambda l: l["date"])
    t0 = date.fromisoformat(pts[0]["date"])
    xs = [(date.fromisoformat(l["date"]) - t0).days / 365.25 for l in pts]
    ys = [l["egfr"] for l in pts]
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom
    return -slope  # positive => declining

def kfre_5yr(age, sex, egfr, acr_mg_g):
    """4-variable Kidney Failure Risk Equation (Tangri), North American 5-yr calibration."""
    acr_mmol = max(acr_mg_g / MG_G_PER_MG_MMOL, 0.1)
    male = 1 if sex == "M" else 0
    L = (-0.2201 * (age / 10 - 7.036)
         + 0.2467 * (male - 0.5642)
         - 0.5567 * (egfr / 5 - 7.222)
         + 0.4510 * (math.log(acr_mmol) - 5.137))
    return 1 - 0.9240 ** math.exp(L)

def on_class(meds, classes):
    return any(m["class"] in classes for m in meds)

def has_drug(meds, name):
    return any(m["name"] == name for m in meds)


def evaluate(p):
    """Return the ground-truth expected block for a patient input dict."""
    labs = p["labs"]; meds = p["medications"]
    lab = latest(labs)
    egfr, acr, k = lab["egfr"], lab["acr_mg_g"], lab["potassium_mmol_l"]
    dm = p["diabetes"]; age = p["age"]; sex = p["sex"]
    on_rasi = on_class(meds, {"ACEi", "ARB"})
    g, a = gfr_cat(egfr), acr_cat(acr)

    surface, suppress = [], []

    # --- CKD definition gate ---
    marker = acr >= ALBUMINURIA or p.get("haematuria") or p.get("structural_marker")
    ckd = egfr < 60 or bool(marker)
    if not ckd:
        suppress.append({"type": "not_ckd", "item": "patient",
                         "reason": f"{g} {a} with no damage marker — does not meet the CKD definition gate; normal kidney, do not surface."})
        return {"ckd": False, "stage": None, "risk_tier": None, "surface": [], "suppress": suppress}

    stage = f"{g} {a}"
    tier = risk_tier(g, a)

    # --- confounder suppressions (drive the trust story) ---
    flagset = set().union(*[set(l.get("flags", [])) for l in labs]) if labs else set()
    if "acute_illness" in flagset:
        acute = [l for l in labs if "acute_illness" in l.get("flags", [])]
        recovered = latest(labs) not in acute and steady_state(labs)
        suppress.append({"type": "non_steady_state", "item": f"eGFR dip on {acute[0]['date']}",
                         "reason": "Coincided with acute illness / volume depletion — non-steady-state, not progression."})
        if recovered:
            suppress.append({"type": "resolved_aki", "item": "trajectory",
                             "reason": "In-hospital nadir recovered to baseline — true trajectory is stable; do not flag progression."})
    if "trimethoprim_course" in flagset:
        suppress.append({"type": "pseudo_rise", "item": "creatinine rise on trimethoprim",
                         "reason": "Trimethoprim blocks tubular creatinine secretion — pseudo-rise, not true GFR decline. Confirm with cystatin C if it persists."})
    if "low_muscle_mass" in flagset:
        suppress.append({"type": "egfr_failure_mode", "item": f"eGFR {egfr}",
                         "reason": "Low muscle mass / cachexia — creatinine-based eGFR overestimates true GFR. Confirm with cystatin C; do not act on the number."})

    # --- trajectory ---
    decline = fit_slope(labs)
    rapid = decline is not None and decline >= RAPID_SLOPE
    steady_pts = steady_state(labs)
    if rapid:
        first, last = sorted(steady_pts, key=lambda l: l["date"])[0], sorted(steady_pts, key=lambda l: l["date"])[-1]
        yrs = (date.fromisoformat(last["date"]) - date.fromisoformat(first["date"])).days / 365.25
        surface.append({"type": "trajectory", "priority": 1,
                        "summary": f"eGFR {first['egfr']} -> {last['egfr']} over {yrs:.0f}y (~{decline:.1f} mL/min/1.73m2/yr) across steady-state values — sustained rapid progression, now {stage}. Invisible value-by-value without trend-fitting."})
    elif decline is not None and tier in ("orange", "red") and len(steady_pts) >= 3:
        suppress.append({"type": "no_progression", "item": "trajectory",
                         "reason": f"Slope ~{decline:.1f} mL/min/yr — below the rapid-progression threshold ({RAPID_SLOPE}). Stable; nothing to action on trajectory."})

    # --- drug gaps (indicated AND not on AND not blocked) ---
    def emit(drug, indicated, already, gated, gate_reason, gap_summary, opt_reason, not_ind_reason=None, prio=2):
        if indicated and already:
            suppress.append({"type": "already_optimised", "item": drug, "reason": opt_reason})
        elif indicated and gated:
            surface.append({"type": "gap_gated", "drug": drug, "priority": 1, "summary": gate_reason})
            suppress.append({"type": "gated_hold", "item": drug, "reason": f"Indicated but gated on K+ {k} (>= {K_GATE}) — treat hyperkalaemia first."})
        elif indicated:
            surface.append({"type": "gap", "drug": drug, "priority": prio, "summary": gap_summary})
        elif not_ind_reason:
            suppress.append({"type": "not_indicated", "item": drug, "reason": not_ind_reason})

    # RAS inhibitor
    emit("RAS inhibitor",
         indicated=acr >= ALBUMINURIA,
         already=on_rasi,
         gated=(acr >= ALBUMINURIA and not on_rasi and k >= K_GATE),
         gate_reason=f"RAS inhibitor indicated (albuminuria ACR {acr}) but gated on K+ {k} (>= {K_GATE}) — treat hyperkalaemia first.",
         gap_summary=f"Albuminuric CKD (ACR {acr}) — RAS inhibitor indicated for cardiorenal protection, not prescribed.",
         opt_reason="Already on a RAS inhibitor.",
         not_ind_reason=None, prio=2)

    # SGLT2 inhibitor
    sglt2_ind = egfr >= 20 and (acr >= SGLT2_ACR or (dm and ckd) or p.get("heart_failure"))
    emit("SGLT2 inhibitor",
         indicated=sglt2_ind,
         already=on_class(meds, {"SGLT2i"}),
         gated=False, gate_reason="",
         gap_summary=(f"Albuminuric CKD (ACR {acr} >= {SGLT2_ACR}), eGFR {egfr} >= 20"
                      + ("" if dm else ", non-diabetic") + " — SGLT2 inhibitor indicated, not prescribed."),
         opt_reason="Already on an SGLT2 inhibitor.",
         not_ind_reason=(f"ACR {acr} (< {SGLT2_ACR}), {'no HF, ' if not p.get('heart_failure') else ''}"
                         f"{'non-diabetic' if not dm else ''} — SGLT2 inhibitor not indicated." if ALBUMINURIA <= acr < SGLT2_ACR and not dm else None),
         prio=2)

    # Finerenone (nsMRA) — diabetes-gated
    fin_ind = dm and ckd and acr >= ALBUMINURIA and on_rasi and egfr >= FINERENONE_EGFR
    emit("finerenone",
         indicated=fin_ind,
         already=on_class(meds, {"nsMRA"}),
         gated=(fin_ind and not on_class(meds, {"nsMRA"}) and k >= K_GATE),
         gate_reason=f"Finerenone (nsMRA) indicated (T2D + albuminuric CKD, on RASi, eGFR {egfr} >= {FINERENONE_EGFR}) but gated on K+ {k} (>= {K_GATE}) — treat hyperkalaemia first.",
         gap_summary=f"T2D + albuminuric CKD (ACR {acr}), on RASi, K+ {k} normal, eGFR {egfr} >= {FINERENONE_EGFR} — finerenone (nsMRA) indicated, not prescribed.",
         opt_reason="Already on finerenone.",
         not_ind_reason=("Non-diabetic — nsMRA is a T2D-gated indication; do NOT surface." if (not dm and acr >= ALBUMINURIA) else None),
         prio=2)

    # Statin
    emit("statin",
         indicated=age >= STATIN_AGE and ckd,
         already=on_class(meds, {"statin"}),
         gated=False, gate_reason="",
         gap_summary=f"Adult >= {STATIN_AGE} (age {age}) with CKD — statin indicated for CV-risk reduction, not prescribed.",
         opt_reason="Already on a statin.",
         not_ind_reason=None, prio=3)

    # --- hyperkalaemia as a first-class safety item ---
    if k >= K_GATE:
        surface.append({"type": "safety", "item": "hyperkalaemia", "priority": 1,
                        "summary": f"K+ {k} (>= {K_GATE}) — address (dietary review, K-binder, review RASi dose) before adding a nsMRA or up-titrating RASi."})

    # --- referral ---
    kfre = kfre_5yr(age, sex, egfr, acr)
    ref_reasons = []
    if egfr < 30: ref_reasons.append(f"eGFR {egfr} < 30")
    if acr >= REFERRAL_ACR: ref_reasons.append(f"ACR {acr} >= {REFERRAL_ACR} mg/g")
    if kfre >= KFRE_REFERRAL: ref_reasons.append(f"KFRE 5-yr {kfre*100:.1f}% >= 5%")
    if rapid: ref_reasons.append("sustained rapid progression")
    if ref_reasons:
        surface.append({"type": "referral", "priority": 3,
                        "summary": "Draft nephrology referral — trigger: " + "; ".join(ref_reasons) + f". (KFRE 5-yr {kfre*100:.1f}%.)"})
    elif tier in ("orange", "red"):
        suppress.append({"type": "no_referral", "item": "referral",
                         "reason": f"No referral criterion met (eGFR {egfr} >= 30, ACR < {REFERRAL_ACR}, KFRE {kfre*100:.1f}% < 5%, not rapid) — do not escalate."})

    # rank surfaced items by priority (stable)
    surface.sort(key=lambda s: s.get("priority", 9))
    return {"ckd": True, "stage": stage, "risk_tier": tier, "surface": surface, "suppress": suppress,
            "kfre_5yr_pct": round(kfre * 100, 1)}


# ---------------------------------------------------------------------------
# PERSONAS  &  JOBS-TO-BE-DONE
# ---------------------------------------------------------------------------
PERSONAS = {
    "amara": {"role": "Panel GP", "job": "See which patients changed between visits so I spend my minutes on the ones who matter."},
    "bola":  {"role": "Care-coordinating nurse", "job": "Get a prioritised worklist of who needs a lab, a titration, or a referral so nothing slips."},
    "chen":  {"role": "Nephrology-adjacent reviewer", "job": "See the reasoning and the ruled-out confounders so I can trust or overrule in seconds."},
}
JTBD = {
    "stratify":  ("amara", "Place each patient on the KDIGO risk grid."),
    "catch":     ("amara", "Surface the slow decline that's invisible visit-by-visit."),
    "close_gap": ("bola",  "Name the now-indicated drug they're not on."),
    "escalate":  ("bola",  "Draft the referral when criteria are met."),
    "withhold":  ("chen",  "Show what was deliberately NOT surfaced, and why."),
    "gate":      ("chen",  "Never recommend starting a drug that's unsafe right now."),
}
# category -> (label, primary jtbd)
CATEGORIES = {
    "C1_staging":        ("Staging & definition gate", "stratify"),
    "C2_true_decline":   ("True rapid progression", "catch"),
    "C3_false_decline":  ("Suppress false decline (AKI / pseudo-rise / muscle)", "withhold"),
    "C4_gap_fire":       ("Correct gap fire", "close_gap"),
    "C5_gap_nonfire":    ("Correct gap non-fire (optimised / below threshold)", "withhold"),
    "C6_safety_gate":    ("Safety gating (hyperkalaemia)", "gate"),
    "C7_referral":       ("Referral fire / non-fire", "escalate"),
}

def tag(category, difficulty):
    label, jtbd = CATEGORIES[category]
    persona = JTBD[jtbd][0]
    return {"category": category, "category_label": label, "jtbd": jtbd,
            "jtbd_desc": JTBD[jtbd][1], "persona": persona,
            "persona_role": PERSONAS[persona]["role"], "difficulty": difficulty}

# hand-authored anchors -> tags + premium summary overrides for the demo hero
ANCHOR_TAGS = {
    "hero-01":       tag("C2_true_decline", "hard"),
    "aki-01":        tag("C3_false_decline", "hard"),
    "pseudo-01":     tag("C3_false_decline", "hard"),
    "optimised-01":  tag("C5_gap_nonfire", "medium"),
    "notckd-01":     tag("C1_staging", "easy"),
    "gated-01":      tag("C6_safety_gate", "hard"),
    "rapid-01":      tag("C2_true_decline", "medium"),
    "statin-01":     tag("C4_gap_fire", "easy"),
    "finerenone-01": tag("C4_gap_fire", "medium"),
    "muscle-01":     tag("C3_false_decline", "hard"),
}
HERO_OVERRIDES = {
    ("trajectory", None): "eGFR declined 78 -> 51 over 4 years (~6.8 mL/min/yr) — a slope invisible at any single visit, now G3a A3, very-high risk.",
    ("gap", "SGLT2 inhibitor"): "Albuminuric CKD, eGFR >= 20: SGLT2 inhibitor indicated and NOT prescribed — the cardiorenal drug never started because the patient isn't diabetic.",
    ("referral", None): "Draft nephrology referral — rapid progression + heavy albuminuria (ACR 320). KFRE-based rationale auto-composed.",
}


# ---------------------------------------------------------------------------
# SYNTHETIC PATIENT GENERATION (40 cases across the categories)
# ---------------------------------------------------------------------------
FIRST_M = ["James","David","Robert","Thomas","Samuel","Daniel","Henry","George","Frank","Oscar","Leon","Omar","Raj","Wei","Kofi"]
FIRST_F = ["Margaret","Aisha","Grace","Priya","Emily","Eleanor","Ruth","Nadia","Ines","Clara","Amina","Mei","Sofia","Lena","Fatima"]
LAST = ["A.","B.","C.","D.","E.","F.","G.","H.","J.","K.","L.","M.","N.","O.","P.","R.","S.","T.","W.","Z."]

def cr_from_egfr(egfr, sex):
    return round(0.8 * (75.0 / max(egfr, 5)) * (1.12 if sex == "M" else 1.0), 2)

def mk_labs(rng, base_egfr, decline, acr_start, acr_end, k, sex, n=4, span_yrs=4,
            confound=None, confound_idx=2, confound_egfr=None):
    """Build n time-ordered labs. confound applies a flag+egfr override at confound_idx."""
    end = date(2026, 2, 1)
    labs = []
    for i in range(n):
        yrs_ago = span_yrs * (n - 1 - i) / (n - 1)
        d = end - timedelta(days=int(yrs_ago * 365.25))
        egfr = round(base_egfr - decline * (span_yrs - yrs_ago))
        acr = round(acr_start + (acr_end - acr_start) * i / (n - 1))
        lab = {"date": d.isoformat(), "egfr": egfr, "acr_mg_g": acr,
               "potassium_mmol_l": round(k + rng.uniform(-0.1, 0.1), 1),
               "creatinine_mg_dl": cr_from_egfr(egfr, sex)}
        if confound and i == confound_idx:
            lab["egfr"] = confound_egfr if confound_egfr is not None else max(egfr - 20, 15)
            lab["creatinine_mg_dl"] = cr_from_egfr(lab["egfr"], sex)
            lab["flags"] = [confound]
        labs.append(lab)
    return labs

def name(rng, sex):
    return f"{rng.choice(FIRST_M if sex=='M' else FIRST_F)} {rng.choice(LAST)}"

MEDS = {
    "ACEi": {"name": "ramipril", "dose": "10 mg", "class": "ACEi", "at_max": True},
    "ACEi_sub": {"name": "ramipril", "dose": "5 mg", "class": "ACEi", "at_max": False},
    "ARB": {"name": "losartan", "dose": "100 mg", "class": "ARB", "at_max": True},
    "SGLT2i": {"name": "dapagliflozin", "dose": "10 mg", "class": "SGLT2i"},
    "nsMRA": {"name": "finerenone", "dose": "20 mg", "class": "nsMRA"},
    "statin": {"name": "atorvastatin", "dose": "20 mg", "class": "statin"},
    "CCB": {"name": "amlodipine", "dose": "5 mg", "class": "CCB"},
    "metformin": {"name": "metformin", "dose": "1 g", "class": "biguanide"},
}
def meds(*keys):
    return [dict(MEDS[k]) for k in keys]

def generate(rng):
    """Return list of (patient_input, tag) for 40 generated patients."""
    out = []
    def add(category, difficulty, **kw):
        sex = kw["sex"]
        p = {"id": None, "name": name(rng, sex), "age": kw["age"], "sex": sex,
             "diabetes": kw.get("dm", False), "problems": kw.get("problems", []),
             "labs": kw["labs"], "medications": kw.get("medications", [])}
        for extra in ("haematuria", "structural_marker", "heart_failure"):
            if kw.get(extra): p[extra] = True
        out.append((p, tag(category, difficulty), category))

    # C1 staging & definition gate (5)
    for _ in range(2):  # not-CKD (G1/G2 A1, no marker)
        add("C1_staging", "easy", sex=rng.choice("MF"), age=rng.randint(35, 55),
            labs=mk_labs(rng, rng.randint(72, 95), 0.5, rng.randint(4, 20), rng.randint(4, 22), 4.2, "M", n=3, span_yrs=2))
    for tier_egfr, acr in [(52, 15), (40, 20), (25, 25)]:  # G3a/G3b/G4 A1 CKD-by-GFR
        s = rng.choice("MF")
        add("C1_staging", "easy", sex=s, age=rng.randint(55, 75),
            labs=mk_labs(rng, tier_egfr, 0.8, acr, acr + 3, 4.3, s, n=3, span_yrs=2),
            medications=meds("statin", "CCB"))

    # C2 true rapid progression (5) — some with gap, some already optimised
    for i in range(5):
        s = rng.choice("MF"); optimised = i % 2 == 1
        m = meds("ACEi", "SGLT2i", "statin") if optimised else meds("ACEi", "statin")
        add("C2_true_decline", "medium" if optimised else "hard", sex=s, age=rng.randint(50, 72), dm=False,
            problems=["hypertension", "albuminuria"],
            labs=mk_labs(rng, rng.randint(56, 66), rng.uniform(6, 8), 210, rng.randint(300, 360), 4.4, s, n=4, span_yrs=3),
            medications=m)

    # C3 suppress false decline (8): AKI, pseudo-rise, muscle
    for _ in range(3):  # AKI dip recovered
        s = rng.choice("MF")
        add("C3_false_decline", "hard", sex=s, age=rng.randint(50, 70),
            problems=["hypertension", "CKD"],
            labs=mk_labs(rng, rng.randint(54, 60), 0.5, 22, 26, 4.5, s, n=5, span_yrs=2.5,
                         confound="acute_illness", confound_idx=2, confound_egfr=rng.randint(28, 34)),
            medications=meds("statin", "CCB"))
    for _ in range(3):  # trimethoprim pseudo-rise
        s = rng.choice("MF")
        add("C3_false_decline", "hard", sex=s, age=rng.randint(58, 74),
            problems=["hypertension", "CKD", "recurrent UTI"],
            labs=mk_labs(rng, rng.randint(48, 54), 0.5, 40, 45, 4.6, s, n=4, span_yrs=2,
                         confound="trimethoprim_course", confound_idx=2, confound_egfr=rng.randint(38, 42)),
            medications=meds("ACEi_sub", "statin"))
    for _ in range(2):  # low muscle mass
        s = rng.choice("MF")
        add("C3_false_decline", "hard", sex=s, age=rng.randint(76, 88),
            problems=["frailty / low muscle mass", "albuminuria"],
            labs=[dict(l, flags=["low_muscle_mass"]) for l in
                  mk_labs(rng, rng.randint(62, 68), 0.4, 90, 120, 4.5, s, n=3, span_yrs=2)],
            medications=meds("CCB", "statin"))

    # C4 correct gap fire (8): SGLT2i non-DM, finerenone DM, statin, RASi
    for _ in range(2):  # SGLT2i non-diabetic albuminuric, not on
        s = rng.choice("MF")
        add("C4_gap_fire", "hard", sex=s, age=rng.randint(48, 68), dm=False,
            problems=["hypertension", "albuminuria"],
            labs=mk_labs(rng, rng.randint(46, 58), 1.5, 240, rng.randint(260, 340), 4.4, s, n=3, span_yrs=2),
            medications=meds("ACEi", "statin"))
    for _ in range(2):  # finerenone: T2D albuminuric on RASi, K normal
        s = rng.choice("MF")
        add("C4_gap_fire", "medium", sex=s, age=rng.randint(55, 70), dm=True,
            problems=["type 2 diabetes", "hypertension", "albuminuria"],
            labs=mk_labs(rng, rng.randint(40, 52), 1.0, 300, 330, 4.6, s, n=3, span_yrs=2),
            medications=meds("ACEi", "SGLT2i", "statin", "metformin"))
    for _ in range(2):  # statin gap
        s = rng.choice("MF")
        add("C4_gap_fire", "easy", sex=s, age=rng.randint(52, 68),
            problems=["CKD"],
            labs=mk_labs(rng, rng.randint(48, 56), 0.6, 14, 18, 4.3, s, n=3, span_yrs=2),
            medications=meds("CCB"))
    for _ in range(2):  # RASi gap (albuminuric, not on RASi, K normal)
        s = rng.choice("MF")
        add("C4_gap_fire", "medium", sex=s, age=rng.randint(45, 60), dm=False,
            problems=["albuminuria"],
            labs=mk_labs(rng, rng.randint(58, 70), 0.6, 60, 90, 4.3, s, n=3, span_yrs=2),
            medications=meds("CCB"))

    # C5 correct non-fire / optimised (5)
    for _ in range(3):  # fully optimised, stable
        s = rng.choice("MF"); dm = rng.random() < 0.5
        m = meds("ARB", "SGLT2i", "statin") + ([dict(MEDS["nsMRA"]), dict(MEDS["metformin"])] if dm else [])
        add("C5_gap_nonfire", "medium", sex=s, age=rng.randint(58, 74), dm=dm,
            problems=(["type 2 diabetes"] if dm else []) + ["hypertension", "CKD", "albuminuria"],
            labs=mk_labs(rng, rng.randint(38, 46), 1.2, 320, 340, 4.6, s, n=3, span_yrs=2),
            medications=m)
    for _ in range(2):  # below-threshold: albuminuric A2 non-DM already on RASi -> SGLT2i correctly withheld
        s = rng.choice("MF")
        add("C5_gap_nonfire", "medium", sex=s, age=rng.randint(50, 66), dm=False,
            problems=["hypertension", "albuminuria"],
            labs=mk_labs(rng, rng.randint(50, 58), 0.6, 60, 90, 4.4, s, n=3, span_yrs=2),
            medications=meds("ACEi", "statin"))

    # C6 safety gating: indicated drug blocked by hyperkalaemia (5)
    for i in range(5):
        s = rng.choice("MF"); dm = i % 2 == 0
        prob = (["type 2 diabetes"] if dm else []) + ["hypertension", "CKD", "albuminuria", "hyperkalaemia"]
        m = meds("ACEi_sub", "SGLT2i", "statin") + ([dict(MEDS["metformin"])] if dm else [])
        add("C6_safety_gate", "hard", sex=s, age=rng.randint(58, 72), dm=dm, problems=prob,
            labs=mk_labs(rng, rng.randint(36, 46), 1.0, 360, 410, rng.choice([5.6, 5.7, 5.8]), s, n=3, span_yrs=2),
            medications=m)

    # C7 referral fire / non-fire (5)
    for _ in range(2):  # eGFR < 30 -> referral
        s = rng.choice("MF")
        add("C7_referral", "easy", sex=s, age=rng.randint(60, 78),
            problems=["CKD", "hypertension"],
            labs=mk_labs(rng, rng.randint(26, 29), 1.0, 40, 50, 4.6, s, n=3, span_yrs=2),
            medications=meds("ACEi", "SGLT2i", "statin"))
    for _ in range(1):  # heavy albuminuria ACR >= 620
        s = rng.choice("MF")
        add("C7_referral", "medium", sex=s, age=rng.randint(50, 68), dm=False,
            problems=["albuminuria"],
            labs=mk_labs(rng, rng.randint(40, 50), 1.0, 650, 720, 4.4, s, n=3, span_yrs=2),
            medications=meds("ACEi", "SGLT2i", "statin"))
    for _ in range(1):  # orange/red but NO referral criterion -> withheld escalation
        s = rng.choice("MF")
        add("C7_referral", "medium", sex=s, age=rng.randint(45, 58),
            problems=["hypertension", "albuminuria"],
            labs=mk_labs(rng, rng.randint(50, 58), 0.8, 320, 340, 4.4, s, n=3, span_yrs=2),
            medications=meds("ACEi", "SGLT2i", "statin"))

    return out


# ---------------------------------------------------------------------------
# ASSEMBLE
# ---------------------------------------------------------------------------
COMORBID_POOL = ["hyperlipidaemia", "ischaemic heart disease", "osteoarthritis", "gout",
                 "obesity", "hypothyroidism", "GORD", "benign prostatic hyperplasia",
                 "atrial fibrillation", "peripheral vascular disease", "former smoker"]

def enrich(p, rng):
    """Add a realistic problem list + encounter history for the EHR view (ignored by the eval)."""
    labs = sorted(p["labs"], key=lambda l: l["date"])
    como = []
    if p["diabetes"]:
        como.append("Type 2 diabetes mellitus")
    como += ["Hypertension", "Chronic kidney disease"]
    pool = [c for c in COMORBID_POOL if not (p["sex"] == "F" and "prostatic" in c)]
    rng.shuffle(pool)
    for c in pool[:rng.randint(1, 3)]:
        como.append(c[0].upper() + c[1:])
    seen, comorbidities = set(), []
    for c in como:
        if c.lower() not in seen:
            seen.add(c.lower()); comorbidities.append(c)

    enc = []
    for l in labs:
        fl = l.get("flags", [])
        if "acute_illness" in fl:
            enc.append({"date": l["date"], "type": "Hospital admission",
                        "summary": l.get("context", "Community-acquired pneumonia; volume depleted. AKI on background CKD.")})
        if "trimethoprim_course" in fl:
            enc.append({"date": l["date"], "type": "GP consultation",
                        "summary": "Urinary tract infection — trimethoprim 200 mg BD for 7 days."})
    enc.append({"date": labs[-1]["date"], "type": "CKD annual review",
                "summary": "Bloods and urine ACR checked; blood pressure recorded; medications reviewed."})
    if len(labs) >= 2:
        enc.append({"date": labs[-2]["date"], "type": "Medication review",
                    "summary": "Repeat prescriptions reviewed."})
    enc.sort(key=lambda e: e["date"], reverse=True)
    return comorbidities, enc


def apply_overrides(pid, expected):
    if pid != "hero-01":
        return expected
    for item in expected["surface"]:
        key = (item["type"], item.get("drug"))
        if key in HERO_OVERRIDES:
            item["summary"] = HERO_OVERRIDES[key]
    return expected

def main():
    rng = random.Random(42)
    anchors = json.load(open(ANCHORS_FILE))["patients"]
    patients = []

    # 10 hand-authored anchors: keep inputs, recompute expected via the oracle, add tags
    for a in anchors:
        pin = {k: a[k] for k in ("id", "name", "age", "sex", "diabetes", "problems", "labs", "medications")}
        for extra in ("haematuria", "structural_marker", "heart_failure"):
            if a.get(extra): pin[extra] = a[extra]
        exp = apply_overrides(a["id"], evaluate(pin))
        patients.append({**pin, "source": "anchor", "tags": ANCHOR_TAGS[a["id"]], "expected": exp})

    # 40 generated
    counters = {}
    for pin, tg, cat in generate(rng):
        counters[cat] = counters.get(cat, 0) + 1
        pin["id"] = f"{cat.split('_')[0].lower()}-g{counters[cat]:02d}"
        exp = evaluate(pin)
        patients.append({**pin, "source": "generated", "tags": tg, "expected": exp})

    for p in patients:
        p["comorbidities"], p["encounters"] = enrich(p, random.Random(p["id"]))

    doc = {
        "meta": {
            "name": "Sentinel — CKD between-visit gold set (personas · JTBD · evals)",
            "version": "2.0", "n": len(patients),
            "guideline_basis": "KDIGO 2024 CKD",
            "personas": PERSONAS, "jobs_to_be_done": {k: {"persona": v[0], "desc": v[1]} for k, v in JTBD.items()},
            "categories": {k: v[0] for k, v in CATEGORIES.items()},
            "thresholds": {"rapid_slope_ml_min_yr": RAPID_SLOPE, "k_gate": K_GATE,
                           "sglt2_acr_mg_g": SGLT2_ACR, "referral_acr_mg_g": REFERRAL_ACR,
                           "kfre_referral": KFRE_REFERRAL},
            "note": "expected blocks are ground truth from the clinical oracle in this file (KDIGO 2024). No real PHI.",
        },
        "patients": patients,
    }
    json.dump(doc, open(OUT_FILE, "w"), indent=2)
    print(f"wrote {len(patients)} patients -> {OUT_FILE}")

if __name__ == "__main__":
    main()
