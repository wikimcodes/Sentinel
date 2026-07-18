"""
Sentinel eval harness — scores a predictor against the gold set's ground truth.

Two metrics carry the pitch:
  * FALSE-ALARM RATE  — of everything surfaced, how much was wrong? (the "cry wolf" number, the moat)
  * MISSED-CATCH RATE — of everything that should have surfaced, how much was missed? (the safety number)

plus surface/suppression precision-recall and per-JTBD / per-persona pass rates.

Predictors:
  perfect  — returns ground truth (harness self-test -> 100%)
  naive    — a dumb rule engine: flags every dip and every label-indicated drug,
             no suppression, wrong thresholds. Quantifies the alert-fatigue problem
             Sentinel's suppression layer is built to solve.

Wire the real agent in by writing a predictor that returns {surface:[...], suppress:[...]}
per patient (see agent_predict stub).
"""
import json, os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "patients.json")


# ---- item identity: compare on type + drug (ignore free-text summary) ----
def surf_key(item):
    return (item["type"], item.get("drug") or item.get("item"))

def supp_key(item):
    return (item["type"], item.get("item"))


# ---- predictors -----------------------------------------------------------
def perfect(p):
    return p["expected"]

def naive(p):
    """Rule engine with no judgment: over-fires, never suppresses."""
    labs = sorted(p["labs"], key=lambda l: l["date"])
    last = labs[-1]
    egfr, acr, k = last["egfr"], last["acr_mg_g"], last["potassium_mmol_l"]
    dm = p["diabetes"]
    on = {m["class"] for m in p["medications"]}
    surface = []
    # flags ANY visit-to-visit drop >=5, including confounded (AKI/pseudo/muscle) -> false alarms
    for a, b in zip(labs, labs[1:]):
        if a["egfr"] - b["egfr"] >= 5:
            surface.append({"type": "trajectory"}); break
    if acr >= 30 and egfr >= 20 and "SGLT2i" not in on:            # wrong threshold (30 not 200)
        surface.append({"type": "gap", "drug": "SGLT2 inhibitor"})
    if acr >= 30 and not (on & {"ACEi", "ARB"}):                   # ignores K+ gate
        surface.append({"type": "gap", "drug": "RAS inhibitor"})
    if dm and acr >= 30 and "nsMRA" not in on:                     # ignores K+ gate + RASi requirement
        surface.append({"type": "gap", "drug": "finerenone"})
    if p["age"] >= 50 and (egfr < 60 or acr >= 30) and "statin" not in on:
        surface.append({"type": "gap", "drug": "statin"})
    if egfr < 45 or acr >= 300:                                   # over-refers
        surface.append({"type": "referral"})
    return {"surface": surface, "suppress": []}

def agent_predict(p):
    """STUB — wire Claude + core tools here; must return {surface:[...], suppress:[...]}."""
    raise NotImplementedError


# ---- scoring --------------------------------------------------------------
def score(predictor, patients):
    S_tp = S_fp = S_fn = 0            # surface confusion
    X_tp = 0; X_total_expected = 0    # suppression recall
    jtbd_pass = defaultdict(lambda: [0, 0])
    persona_pass = defaultdict(lambda: [0, 0])
    ckd_correct = 0

    for p in patients:
        exp = p["expected"]
        pred = predictor(p)
        exp_s = {surf_key(i) for i in exp["surface"]}
        pred_s = {surf_key(i) for i in pred["surface"]}
        S_tp += len(exp_s & pred_s)
        S_fp += len(pred_s - exp_s)
        S_fn += len(exp_s - pred_s)

        exp_x = {supp_key(i) for i in exp["suppress"]}
        pred_x = {supp_key(i) for i in pred.get("suppress", [])}
        X_tp += len(exp_x & pred_x)
        X_total_expected += len(exp_x)

        exact = (exp_s == pred_s)
        jt = p["tags"]["jtbd"]; pe = p["tags"]["persona"]
        jtbd_pass[jt][0] += exact; jtbd_pass[jt][1] += 1
        persona_pass[pe][0] += exact; persona_pass[pe][1] += 1
        if pred.get("ckd", exp["ckd"]) == exp["ckd"]:
            ckd_correct += 1

    total_pred_surface = S_tp + S_fp
    total_exp_surface = S_tp + S_fn
    return {
        "n": len(patients),
        "surface_precision": S_tp / total_pred_surface if total_pred_surface else 1.0,
        "surface_recall": S_tp / total_exp_surface if total_exp_surface else 1.0,
        "false_alarm_rate": S_fp / total_pred_surface if total_pred_surface else 0.0,
        "missed_catch_rate": S_fn / total_exp_surface if total_exp_surface else 0.0,
        "suppression_recall": X_tp / X_total_expected if X_total_expected else 1.0,
        "staging_accuracy": ckd_correct / len(patients),
        "jtbd_pass": {k: v[0] / v[1] for k, v in jtbd_pass.items()},
        "persona_pass": {k: v[0] / v[1] for k, v in persona_pass.items()},
    }


def report(name, m):
    print(f"\n=== {name}  (n={m['n']}) ===")
    print(f"  FALSE-ALARM rate    {m['false_alarm_rate']*100:5.1f}%   (of what it surfaced, how much was wrong)")
    print(f"  MISSED-CATCH rate   {m['missed_catch_rate']*100:5.1f}%   (of what it should surface, how much it missed)")
    print(f"  surface precision   {m['surface_precision']*100:5.1f}%")
    print(f"  surface recall      {m['surface_recall']*100:5.1f}%")
    print(f"  suppression recall  {m['suppression_recall']*100:5.1f}%   (did it withhold what it should)")
    print(f"  staging accuracy    {m['staging_accuracy']*100:5.1f}%")
    print("  per-JTBD exact-match: " + "  ".join(f"{k}={v*100:.0f}%" for k, v in m["jtbd_pass"].items()))
    print("  per-persona         : " + "  ".join(f"{k}={v*100:.0f}%" for k, v in m["persona_pass"].items()))


if __name__ == "__main__":
    patients = json.load(open(DATA))["patients"]
    report("Sentinel target (oracle-perfect)", score(perfect, patients))
    report("Naive rule engine (no suppression)", score(naive, patients))
    print("\nThe gap between these two rows is the product.")
