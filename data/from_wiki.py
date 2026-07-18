"""
Convert Wiki's golden set (docs/sentinel_demo_patients_50) into the app schema and
write data/patients.json, so the backend + UI run on Wiki's patients.

Records (labs / meds / demographics / context) come from Wiki; the `expected` block
(stage, tier, surface, suppress, KFRE) is computed by our deterministic core — the
same core the live agent orchestrates — so the panel preview matches the detail view.

    .venv/bin/python data/from_wiki.py
"""
import json, os, sys, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "core"))
import clinical_core as core

WIKI = json.load(open(os.path.join(HERE, "..", "docs", "sentinel_demo_patients_50")))["patients"]
OUT = os.path.join(HERE, "patients.json")

MED_CLASS = {
    "ramipril": "ACEi", "lisinopril": "ACEi", "enalapril": "ACEi", "perindopril": "ACEi",
    "losartan": "ARB", "candesartan": "ARB", "valsartan": "ARB", "irbesartan": "ARB",
    "dapagliflozin": "SGLT2i", "empagliflozin": "SGLT2i", "finerenone": "nsMRA",
    "atorvastatin": "statin", "simvastatin": "statin", "rosuvastatin": "statin",
    "amlodipine": "CCB", "furosemide": "loop", "metformin": "biguanide", "insulin": "insulin",
    "trimethoprim": "antibiotic", "cimetidine": "h2",
}
DOSE = {"ramipril": "10 mg", "lisinopril": "10 mg", "losartan": "100 mg", "candesartan": "16 mg",
        "dapagliflozin": "10 mg", "empagliflozin": "10 mg", "finerenone": "20 mg",
        "atorvastatin": "20 mg", "simvastatin": "40 mg", "amlodipine": "5 mg",
        "metformin": "1 g", "furosemide": "40 mg", "insulin": "24 U",
        "trimethoprim": "200 mg BD (course)", "cimetidine": "400 mg"}
FIRST_M = ["James", "David", "Robert", "Thomas", "Samuel", "Henry", "George", "Omar", "Raj", "Kofi", "Leon", "Frank"]
FIRST_F = ["Margaret", "Aisha", "Grace", "Priya", "Eleanor", "Ruth", "Nadia", "Clara", "Amina", "Mei", "Sofia", "Fatima"]
LAST = ["A.", "B.", "C.", "D.", "E.", "F.", "G.", "H.", "K.", "L.", "M.", "N.", "P.", "R.", "S.", "T.", "W."]

CONDITION = [
    ("heart failure", "Heart failure"), ("myocardial infarction", "Ischaemic heart disease"),
    ("prior mi", "Ischaemic heart disease"), ("pregnant", "Pregnancy"),
    ("haematuria", "Persistent haematuria"), ("amputation", "Below-knee amputation"),
    ("bodybuilder", "High muscle mass"), ("muscle mass", "Low muscle mass"),
    ("frail", "Frailty"), ("hyperkalaemia", "Hyperkalaemia"),
    ("haemodialysis", "On haemodialysis"), ("dialysis", "Dialysis-dependent CKD"),
]

def cr_from_egfr(egfr, sex):
    return round(0.8 * (75.0 / max(egfr, 5)) * (1.12 if sex == "M" else 1.0), 2)

def build(wp):
    rng = random.Random(wp["id"])
    dm = wp["demographics"]["diabetes"]; sex = wp["demographics"]["sex"]
    ctx = " ".join(wp.get("context", [])).lower()

    labs = []
    for l in sorted(wp["labs"], key=lambda x: x["date"]):
        d = l["date"] + "-01" if len(l["date"]) == 7 else l["date"]
        lab = {"date": d, "egfr": l["eGFR"], "acr_mg_g": l["ACR"], "potassium_mmol_l": l["K"],
               "creatinine_mg_dl": cr_from_egfr(l["eGFR"], sex)}
        if l.get("acute"):
            lab["flags"] = ["acute_illness"]
        labs.append(lab)
    latest = labs[-1]; lf = set(latest.get("flags", []))
    if any(w in ctx for w in ["trimethoprim", "cimetidine"]): lf.add("trimethoprim_course")
    if any(w in ctx for w in ["muscle mass", "amputation", "frail", "bodybuilder", "cachex"]): lf.add("low_muscle_mass")
    if lf: latest["flags"] = list(lf)

    meds = [{"name": m, "dose": DOSE.get(m, ""), "class": MED_CLASS.get(m, "other")} for m in wp["medications"]]

    p = {"id": wp["id"], "name": f"{rng.choice(FIRST_M if sex == 'M' else FIRST_F)} {rng.choice(LAST)}",
         "age": wp["demographics"]["age"], "sex": sex, "diabetes": dm,
         "problems": wp.get("context", []), "labs": labs, "medications": meds}
    if "haematuria" in ctx: p["haematuria"] = True
    if "heart failure" in ctx or "hfref" in ctx: p["heart_failure"] = True
    if "pregnant" in ctx: p["pregnant"] = True
    if "dialysis" in ctx or "haemodialysis" in ctx: p["dialysis"] = True

    expected = core.review_patient(p)

    como = (["Type 2 diabetes mellitus"] if dm else [])
    if expected["ckd"]:
        como += ["Hypertension", "Chronic kidney disease"]
    for kw, name in CONDITION:
        if kw in ctx and name not in como:
            como.append(name)

    enc = []
    for l in labs:
        if "acute_illness" in l.get("flags", []):
            enc.append({"date": l["date"], "type": "Hospital admission",
                        "summary": "Acute illness — non-steady-state bloods (excluded from trend)."})
        if "trimethoprim_course" in l.get("flags", []):
            drug = "trimethoprim" if "trimethoprim" in ctx else "cimetidine"
            enc.append({"date": l["date"], "type": "GP consultation",
                        "summary": f"Prescribed {drug} — may transiently raise creatinine."})
    enc.append({"date": labs[-1]["date"], "type": "CKD annual review",
                "summary": "Bloods and urine ACR checked; medications reviewed."})
    seen = set(); enc = [e for e in sorted(enc, key=lambda e: e["date"], reverse=True)
                         if not (e["summary"] in seen or seen.add(e["summary"]))]

    p["comorbidities"] = como
    p["encounters"] = enc
    p["source"] = "wiki"
    p["wiki_expected"] = wp["expected"]     # keep Wiki's ground truth for reference
    p["expected"] = expected
    return p

patients = [build(wp) for wp in WIKI]
json.dump({"meta": {"name": "Sentinel — Wiki golden set (docs/sentinel_demo_patients_50), app schema",
                    "n": len(patients), "note": "records from Wiki; expected computed by core"},
           "patients": patients}, open(OUT, "w"), indent=2)
print(f"wrote {len(patients)} patients (from Wiki's golden set) -> {OUT}")
