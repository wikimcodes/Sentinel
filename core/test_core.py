"""
Sentinel core tests. Run: python3 core/test_core.py   (no pytest needed)

Two layers:
  1. Unit tests on primitives against hand-verified values.
  2. Cross-check: core.review_patient agrees with the frozen gold set (data/patients.json)
     on the surface/suppress item keys for all 50 patients. Since the gold set was authored
     by a SEPARATE oracle, agreement validates both implementations against one contract.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clinical_core as c

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "patients.json")
_fails = []

def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        _fails.append(name)

def approx(a, b, tol):
    return a is not None and abs(a - b) <= tol


print("UNIT — staging")
check("egfr 51 -> G3a", c.gfr_category(51) == "G3a")
check("egfr 45 -> G3a (boundary)", c.gfr_category(45) == "G3a")
check("egfr 44 -> G3b (boundary)", c.gfr_category(44) == "G3b")
check("acr 320 -> A3", c.acr_category(320) == "A3")
check("acr 300 -> A2 (boundary)", c.acr_category(300) == "A2")
check("hero stage G3a A3 / red", c.stage_patient(51, 320) == {"gfr_category": "G3a", "acr_category": "A3", "stage": "G3a A3", "risk_tier": "red"})
check("G3a A1 -> yellow", c.stage_patient(51, 10)["risk_tier"] == "yellow")
check("G2 A1 -> green", c.stage_patient(72, 9)["risk_tier"] == "green")

print("UNIT — CKD gate")
check("G2 A1 no marker -> NOT CKD", c.meets_ckd_definition(71, 9) is False)
check("G3a A1 -> CKD (by eGFR)", c.meets_ckd_definition(51, 9) is True)
check("G2 A2 -> CKD (by marker)", c.meets_ckd_definition(72, 40) is True)

print("UNIT — trajectory")
hero_labs = [{"date": "2022-03-11", "egfr": 78}, {"date": "2023-04-02", "egfr": 71},
             {"date": "2024-03-19", "egfr": 63}, {"date": "2025-03-08", "egfr": 57},
             {"date": "2026-02-15", "egfr": 51}]
t = c.egfr_trajectory(hero_labs)
check("hero decline ~6.8/yr", approx(t["decline_per_year"], 6.8, 0.3))
check("hero rapid == True", t["rapid"] is True)
aki = [{"date": "2024-06-10", "egfr": 58}, {"date": "2024-12-04", "egfr": 56},
       {"date": "2025-08-21", "egfr": 32, "flags": ["acute_illness"]}, {"date": "2026-01-12", "egfr": 57}]
check("AKI dip excluded -> not rapid", c.egfr_trajectory(aki)["rapid"] is False)
check("AKI steady points = 3", c.egfr_trajectory(aki)["n_steady"] == 3)

print("UNIT — KFRE")
check("hero KFRE ~0.8%", approx(c.kfre_5yr_risk(62, "F", 51, 320) * 100, 0.8, 0.3))
check("advanced KFRE higher", c.kfre_5yr_risk(70, "M", 22, 800) > c.kfre_5yr_risk(62, "F", 51, 320))

print("UNIT — meds & referral")
hero = {"age": 62, "sex": "F", "diabetes": False, "problems": [],
        "labs": [{"date": "2026-02-15", "egfr": 51, "acr_mg_g": 320, "potassium_mmol_l": 4.4}],
        "medications": [{"name": "ramipril", "class": "ACEi"}, {"name": "atorvastatin", "class": "statin"}]}
meds = {m["drug"]: m["status"] for m in c.evaluate_medications(hero)}
check("hero SGLT2i = gap", meds["SGLT2 inhibitor"] == "gap")
check("hero RASi = optimised", meds["RAS inhibitor"] == "optimised")
check("hero statin = optimised", meds["statin"] == "optimised")
check("hero finerenone = not_indicated (non-diabetic)", meds["finerenone"] == "not_indicated")
gated = {"age": 64, "sex": "M", "diabetes": True, "problems": [],
         "labs": [{"date": "2026-01-27", "egfr": 36, "acr_mg_g": 410, "potassium_mmol_l": 5.7}],
         "medications": [{"name": "ramipril", "class": "ACEi"}, {"name": "dapagliflozin", "class": "SGLT2i"}]}
gmeds = {m["drug"]: m["status"] for m in c.evaluate_medications(gated)}
check("gated finerenone = gated (K+ 5.7)", gmeds["finerenone"] == "gated")
check("hero referral fires (rapid)", c.referral_recommendation({**hero, "labs": [dict(l) for l in [
    {"date": "2022-03-11", "egfr": 78, "acr_mg_g": 260}, {"date": "2026-02-15", "egfr": 51, "acr_mg_g": 320}]]})["refer"] is True)

print("CROSS-CHECK — core vs frozen gold set (50 patients)")
patients = json.load(open(DATA))["patients"]
def keys(items, kind):
    return {(i["type"], i.get("drug") or i.get("item")) for i in items} if kind == "surf" \
        else {(i["type"], i.get("item")) for i in items}
mismatch = 0
for p in patients:
    r = c.review_patient(p)
    e = p["expected"]
    if keys(r["surface"], "surf") != keys(e["surface"], "surf") or \
       keys(r["suppress"], "sup") != keys(e["suppress"], "sup") or \
       r["ckd"] != e["ckd"] or r["risk_tier"] != e["risk_tier"]:
        mismatch += 1
        if mismatch <= 5:
            print(f"    MISMATCH {p['id']}: surf {keys(r['surface'],'surf') ^ keys(e['surface'],'surf')} | "
                  f"supp {keys(r['suppress'],'sup') ^ keys(e['suppress'],'sup')}")
check(f"core agrees with gold set on all 50 (mismatches={mismatch})", mismatch == 0)

print()
if _fails:
    print(f"FAILED {len(_fails)}: " + ", ".join(_fails)); sys.exit(1)
print("ALL TESTS PASSED")
