"""
Sentinel backend — the live agent behind the EHR surface.

Runs the tested deterministic core (core/clinical_core.py) on the patient's record —
including any lab values the clinician edits in the UI — so every re-run is instant
and reliable. Attaches KDIGO/NICE guideline citations, an agent tool-trace (what the
agent checked, in order), and a clinical brief (missed / needs-attention / working /
ruled-out). The referral letter is generated on demand, by Claude when a key is present.

Run:  python3 server/app.py        # serves http://localhost:8787
Zero dependencies for the core path; `anthropic` is imported lazily only for referral prose.
"""
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))

def _load_env():
    p = os.path.join(HERE, "..", ".env")
    if os.path.exists(p):
        for line in open(p):
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
_load_env()

sys.path.insert(0, os.path.join(HERE, "..", "core"))
sys.path.insert(0, os.path.join(HERE, "..", "agent"))
import clinical_core as core

DATA = os.path.join(HERE, "..", "data", "patients.json")
PATIENTS = {p["id"]: p for p in json.load(open(DATA))["patients"]}
PORT = 8787
MODEL = "claude-opus-4-8"

# ---------------------------------------------------------------------------
# Guideline citations — every finding maps to the rule that justifies it
# ---------------------------------------------------------------------------
CITE = {
    ("trajectory", None): "KDIGO 2024 CKD — sustained eGFR decline ≥5 mL/min/1.73m²/yr defines rapid progression.",
    ("gap", "SGLT2 inhibitor"): "KDIGO 2024 · DAPA-CKD — SGLT2 inhibitor for albuminuric CKD (ACR ≥200 mg/g), eGFR ≥20.",
    ("gap", "RAS inhibitor"): "KDIGO 2024 — ACEi/ARB for albuminuric CKD (A2–A3); titrate to max tolerated.",
    ("gap", "finerenone"): "KDIGO · FIDELIO/FIGARO-DKD — nsMRA for T2D + albuminuric CKD on max RASi, K⁺ normal, eGFR ≥25.",
    ("gap", "statin"): "KDIGO Lipid — statin for all adults ≥50 with CKD (CV risk reduction).",
    ("gap_gated", "finerenone"): "KDIGO safety — nsMRA indicated but withhold initiation while K⁺ ≥5.5 mmol/L.",
    ("gap_gated", "RAS inhibitor"): "KDIGO safety — do not up-titrate RASi while hyperkalaemic (K⁺ ≥5.5).",
    ("safety", "hyperkalaemia"): "KDIGO — treat K⁺ ≥5.5 mmol/L (diet, review RASi, K-binder) before adding a nsMRA.",
    ("referral", None): "NICE NG203 · KDIGO — refer if eGFR<30, ACR ≥70 mg/mmol (~620 mg/g), KFRE 5-yr ≥5%, or rapid progression.",
    ("already_optimised", None): "Already on guideline-directed therapy — no action needed.",
    ("not_indicated", "SGLT2 inhibitor"): "Below DAPA-CKD threshold (ACR <200 mg/g), non-diabetic — SGLT2i not indicated.",
    ("not_indicated", "finerenone"): "nsMRA is a T2D-gated indication (KDIGO) — not indicated in non-diabetics.",
    ("gated_hold", None): "KDIGO safety gate — indicated but held until the blocking parameter is corrected.",
    ("non_steady_state", None): "KDIGO — exclude non-steady-state eGFR (acute illness / AKI / volume depletion) from progression assessment.",
    ("resolved_aki", None): "KDIGO — a recovered AKI nadir is not a progression signal.",
    ("pseudo_rise", None): "Trimethoprim inhibits tubular creatinine secretion — pseudo-rise, not true GFR decline. Confirm with cystatin C.",
    ("egfr_failure_mode", None): "KDIGO — creatinine-based eGFR unreliable at extremes of muscle mass; confirm with cystatin C.",
    ("no_progression", None): "eGFR slope <5 mL/min/1.73m²/yr — not rapid progression (KDIGO).",
    ("no_referral", None): "No KDIGO/NICE nephrology-referral criterion met.",
    ("not_ckd", None): "KDIGO CKD definition not met (no eGFR<60 and no persistent damage marker).",
}
def cite(item):
    key = item.get("drug") or item.get("item")
    return CITE.get((item["type"], key)) or CITE.get((item["type"], None)) or "KDIGO 2024 CKD guideline."


# ---------------------------------------------------------------------------
# Build the agent's review of a (possibly edited) record
# ---------------------------------------------------------------------------
def build_review(patient):
    labs = sorted(patient["labs"], key=lambda l: l["date"])
    lab = labs[-1]
    egfr, acr, k = lab["egfr"], lab["acr_mg_g"], lab["potassium_mmol_l"]

    ckd = core.meets_ckd_definition(egfr, acr, patient.get("haematuria"), patient.get("structural_marker"))
    stage = core.stage_patient(egfr, acr)
    traj = core.egfr_trajectory(labs)
    meds = core.evaluate_medications(patient)
    ref = core.referral_recommendation(patient)
    review = core.review_patient(patient)

    excluded = len(labs) - traj["n_steady"]
    med_bits = ", ".join(f"{m['drug']}: {m['status']}" for m in meds)
    trace = [
        {"tool": "stage_patient", "summary": f"CGA {stage['stage']} — {stage['risk_tier'].upper()} risk tier"},
        {"tool": "check_ckd_definition", "summary": "Meets KDIGO CKD definition" if ckd else "Does NOT meet CKD definition"},
        {"tool": "fit_egfr_trajectory",
         "summary": (f"slope {traj['decline_per_year']:.1f} mL/min/yr over {traj['n_steady']} steady-state points"
                     + (f" ({excluded} excluded as confounded)" if excluded else "")
                     + (" → RAPID PROGRESSION" if traj["rapid"] else " → stable")) if traj["decline_per_year"] is not None
                    else "insufficient steady-state points"},
        {"tool": "evaluate_medications", "summary": med_bits or "no guideline drugs applicable"},
        {"tool": "referral_recommendation",
         "summary": ("refer — " + "; ".join(ref["reasons"])) if ref["refer"] else f"no referral criterion (KFRE {ref['kfre_5yr_pct']}%)"},
        {"tool": "apply_suppression_rules", "summary": f"{len(review['suppress'])} findings considered and deliberately withheld"},
    ]
    return decorate(review["surface"], review["suppress"], trace, review["ckd"], review["stage"],
                    review["risk_tier"], review.get("kfre_5yr_pct"), traj.get("rapid"),
                    engine="deterministic core")


def build_review_live(patient):
    """Same output shape, but the surface/suppress and the tool trace come from the
    live Claude agent actually calling the core tools. Numbers still come from core."""
    import review_agent
    ag = review_agent.run_review(patient["id"], patient=patient)
    labs = sorted(patient["labs"], key=lambda l: l["date"]); lab = labs[-1]
    ckd = core.meets_ckd_definition(lab["egfr"], lab["acr_mg_g"], patient.get("haematuria"), patient.get("structural_marker"))
    stage = core.stage_patient(lab["egfr"], lab["acr_mg_g"])
    traj = core.egfr_trajectory(labs)
    ref = core.referral_recommendation(patient)
    return decorate(ag["surface"], ag["suppress"], ag.get("trace", []), ckd,
                    stage["stage"] if ckd else None, stage["risk_tier"] if ckd else None,
                    ref["kfre_5yr_pct"], traj.get("rapid"), engine="Claude agent (live tool-calling)")


def decorate(surface_raw, suppress_raw, trace, ckd, stage, tier, kfre, rapid, engine):
    surface = [{**s, "citation": cite(s)} for s in surface_raw]
    suppress = [{**s, "citation": cite(s)} for s in suppress_raw]
    missed = [s for s in surface if s["type"] in ("trajectory", "gap", "referral")]
    attention = [s for s in surface if s["type"] in ("safety", "gap_gated")]
    working = [s for s in suppress if s["type"] == "already_optimised"]
    ruled_out = [s for s in suppress if s["type"] != "already_optimised"]
    brief = {"missed": missed, "attention": attention, "working": working, "ruled_out": ruled_out,
             "headline": headline(ckd, rapid, missed, attention)}
    return {"ckd": ckd, "stage": stage, "risk_tier": tier, "kfre_5yr_pct": kfre, "engine": engine,
            "trace": trace, "surface": surface, "suppress": suppress, "brief": brief}


def headline(ckd, rapid, missed, attention):
    if not ckd:
        return "No CKD — this patient does not meet the KDIGO definition. Nothing to action."
    parts = []
    if rapid:
        parts.append("a rapid eGFR decline invisible visit-to-visit")
    gaps = [s["drug"] for s in missed if s["type"] == "gap"]
    if gaps:
        parts.append("a now-indicated " + " and ".join(gaps) + " that was never started")
    if any(s["type"] == "referral" for s in missed):
        parts.append("nephrology-referral criteria met")
    if attention:
        parts.append("a drug held pending hyperkalaemia")
    if not parts:
        return "Reviewed against KDIGO 2024 — this patient is on optimal therapy and stable. No action needed."
    return f"Sentinel caught {', '.join(parts)} — {len(missed)} item{'s' if len(missed) != 1 else ''} a busy 10-minute visit would likely miss."


# ---------------------------------------------------------------------------
# Referral letter — Claude when available, deterministic template otherwise
# ---------------------------------------------------------------------------
def referral_letter(patient):
    review = core.review_patient(patient)
    ref_item = next((s for s in review["surface"] if s["type"] == "referral"), None)
    if not ref_item:
        return None, "template"
    lab = sorted(patient["labs"], key=lambda l: l["date"])[-1]
    trigger = ref_item["summary"].split("trigger:")[-1].split("(KFRE")[0].strip().rstrip(".")
    facts = {
        "name": patient["name"], "age": patient["age"], "sex": patient["sex"],
        "ckd_stage": review["stage"],
        "eGFR": f"{lab['egfr']} mL/min/1.73m2",
        "urine_ACR": f"{lab['acr_mg_g']} mg/g",           # unit is explicit — do not convert
        "serum_potassium": f"{lab['potassium_mmol_l']} mmol/L",
        "KFRE_5yr": f"{review.get('kfre_5yr_pct')}%",
        "referral_trigger": trigger,
        "comorbidities": patient.get("comorbidities", []),
    }
    letter = claude_referral(facts)
    if letter:
        return letter, "claude"
    return (
f"""Dear Nephrology team,

Re: {facts['name']} — {facts['age']}{facts['sex']}, CKD {facts['ckd_stage']}.
Background: {', '.join(facts['comorbidities'][:4])}.

I am referring this patient for nephrology assessment.

Trigger: {facts['referral_trigger']}.
Latest bloods: eGFR {facts['eGFR']}, urine ACR {facts['urine_ACR']}, K+ {facts['serum_potassium']}.
5-year kidney-failure risk (KFRE): {facts['KFRE_5yr']}.

Grateful for your review.""", "template")


def claude_referral(facts):
    try:
        import anthropic
    except Exception:
        return None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.path.exists(os.path.expanduser("~/.config/anthropic"))):
        return None
    try:
        client = anthropic.Anthropic()
        prompt = ("Write a concise, professional UK GP-to-nephrology referral letter (max 140 words) "
                  "using ONLY the facts below. Do NOT invent values, and do NOT convert or relabel units — "
                  "quote each value with the exact unit given (ACR is in mg/g, not mg/mmol):\n"
                  + json.dumps(facts, indent=2))
        resp = client.messages.create(model=MODEL, max_tokens=600,
                                       messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_OPTIONS(self):
        self._send({})

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        if self.path == "/api/patients":
            return self._send({"patients": list(PATIENTS.values())})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        try:
            b = self._body()
            base = PATIENTS.get(b.get("patient_id"))
            if not base:
                return self._send({"error": "unknown patient"}, 404)
            patient = {**base, "labs": b.get("labs", base["labs"])}
            if self.path == "/api/review":
                if b.get("live"):
                    try:
                        return self._send(build_review_live(patient))
                    except Exception as e:
                        r = build_review(patient)
                        r["engine"] = f"deterministic core (live agent unavailable: {e})"
                        return self._send(r)
                return self._send(build_review(patient))
            if self.path == "/api/referral":
                letter, source = referral_letter(patient)
                return self._send({"letter": letter, "source": source})
            if self.path == "/api/prescribe":
                drug = b.get("drug", "medication")
                return self._send({"ok": True, "drug": drug,
                                   "message": f"{drug} initiated and added to the medication list. "
                                              "Follow-up bloods (U&E) in 2–4 weeks."})
        except Exception as e:
            return self._send({"error": str(e)}, 500)
        self._send({"error": "not found"}, 404)


if __name__ == "__main__":
    print(f"Sentinel backend on http://localhost:{PORT}  ({len(PATIENTS)} patients)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
