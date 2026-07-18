"""
Sentinel — the between-visit review agent.

Claude plans and orchestrates; the deterministic core in core/clinical_core.py does
every calculation. The core functions are exposed as tools that take a patient_id and
run on the REAL record — so the model cannot invent a number, only decide which tools
to call, how to sequence the reasoning, and what to surface vs. suppress.

A final `submit_review` tool captures the structured output the eval scores.

Run one patient:   python3 agent/review_agent.py hero-01
Requires: pip install anthropic   +   ANTHROPIC_API_KEY (or `ant auth login`).
"""
from __future__ import annotations
import json, os, sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

def _load_env():
    p = os.path.join(_ROOT, ".env")
    if os.path.exists(p):
        for line in open(p):
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
_load_env()

sys.path.insert(0, os.path.join(_ROOT, "core"))
import clinical_core as core

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "patients.json")
MODEL = "claude-opus-4-8"

_PATIENTS = {p["id"]: p for p in json.load(open(DATA))["patients"]}


# ---------------------------------------------------------------------------
# Tools — each wraps a core function and runs on the real patient record
# ---------------------------------------------------------------------------
def _latest(p):
    return sorted(p["labs"], key=lambda l: l["date"])[-1]

def _tool_stage(pid):
    lab = _latest(_PATIENTS[pid])
    return core.stage_patient(lab["egfr"], lab["acr_mg_g"])

def _tool_ckd(pid):
    p = _PATIENTS[pid]; lab = _latest(p)
    return {"is_ckd": core.meets_ckd_definition(lab["egfr"], lab["acr_mg_g"],
                                                p.get("haematuria"), p.get("structural_marker"))}

def _tool_trajectory(pid):
    t = core.egfr_trajectory(_PATIENTS[pid]["labs"])
    return {"decline_per_year": t["decline_per_year"], "rapid": t["rapid"],
            "steady_state_points_used": t["n_steady"]}

def _tool_meds(pid):
    return {"medications": core.evaluate_medications(_PATIENTS[pid])}

def _tool_referral(pid):
    return core.referral_recommendation(_PATIENTS[pid])

CORE_TOOLS = {
    "stage_patient": _tool_stage,
    "check_ckd_definition": _tool_ckd,
    "egfr_trajectory": _tool_trajectory,
    "evaluate_medications": _tool_meds,
    "referral_recommendation": _tool_referral,
}

_pid_arg = {"patient_id": {"type": "string", "description": "The patient id, e.g. 'hero-01'"}}

TOOL_SCHEMAS = [
    {"name": "stage_patient", "description": "CGA stage (GFR + albuminuria category) and KDIGO risk tier from the latest labs.",
     "input_schema": {"type": "object", "properties": _pid_arg, "required": ["patient_id"]}},
    {"name": "check_ckd_definition", "description": "Whether the patient meets the KDIGO CKD definition gate (eGFR<60 OR a damage marker).",
     "input_schema": {"type": "object", "properties": _pid_arg, "required": ["patient_id"]}},
    {"name": "egfr_trajectory", "description": "eGFR slope over steady-state values (excludes acute-illness / trimethoprim / low-muscle-mass points). Reports decline/yr and whether it is rapid (>=5).",
     "input_schema": {"type": "object", "properties": _pid_arg, "required": ["patient_id"]}},
    {"name": "evaluate_medications", "description": "For each guideline drug (RAS inhibitor, SGLT2 inhibitor, finerenone, statin): status = gap | gated | optimised | not_indicated, with a reason.",
     "input_schema": {"type": "object", "properties": _pid_arg, "required": ["patient_id"]}},
    {"name": "referral_recommendation", "description": "Whether nephrology referral criteria are met (eGFR<30, heavy albuminuria, KFRE 5-yr >=5%, or rapid progression), with the KFRE value.",
     "input_schema": {"type": "object", "properties": _pid_arg, "required": ["patient_id"]}},
    {"name": "submit_review", "description": "Submit the final between-visit review. Call this LAST, exactly once.",
     "input_schema": {"type": "object", "properties": {
         "patient_id": {"type": "string"},
         "surface": {"type": "array", "description": "Items to escalate to the clinician, most important first.",
                     "items": {"type": "object", "properties": {
                         "type": {"type": "string", "enum": ["trajectory", "gap", "gap_gated", "safety", "referral"]},
                         "drug": {"type": "string", "description": "For gap / gap_gated: the drug name exactly as returned by evaluate_medications."},
                         "item": {"type": "string", "description": "For safety: e.g. 'hyperkalaemia'."},
                         "summary": {"type": "string"},
                         "priority": {"type": "integer"}}, "required": ["type", "summary"]}},
         "suppress": {"type": "array", "description": "Considered and deliberately withheld, each with a one-line reason.",
                      "items": {"type": "object", "properties": {
                          "type": {"type": "string", "enum": ["already_optimised", "not_indicated", "gated_hold",
                                                              "non_steady_state", "resolved_aki", "pseudo_rise",
                                                              "egfr_failure_mode", "no_progression", "no_referral", "not_ckd"]},
                          "item": {"type": "string"}, "reason": {"type": "string"}}, "required": ["type", "item", "reason"]}}},
      "required": ["patient_id", "surface", "suppress"]}},
]

SYSTEM = """You are Sentinel, a between-visit clinical-review agent for chronic kidney disease (KDIGO 2024).
You run the longitudinal review a clinician has no time to do between appointments.

HARD RULES:
- Every number you report must come from a tool call. Never invent or estimate a threshold, stage, slope, or risk.
- Call the tools to gather the deterministic facts, then decide what a clinician needs to see.
- SURFACE only what needs a human: a rapid decline (trajectory), a now-indicated drug not prescribed (gap),
  a drug indicated but blocked by a safety parameter (gap_gated + a safety item for the blocker), or a referral.
- A drug with status 'gated' is NEVER a clean 'gap' — surface it as gap_gated and also surface the safety issue.
- SUPPRESS, with a one-line reason, everything you considered and deliberately withheld: drugs already optimised,
  drugs not indicated, confounded eGFR readings (acute illness, trimethoprim pseudo-rise, low muscle mass),
  a stable slope, a not-met referral. The value of this tool is what it withholds — a clinician switches off
  anything that cries wolf.
- If the patient does not meet the CKD definition, surface nothing and suppress with type 'not_ckd'.
- Rank surfaced items by clinical priority (1 = most urgent). Call submit_review exactly once at the end."""


def run_review(patient_id: str, verbose: bool = False) -> dict:
    """Drive the tool-use loop for one patient; return {surface, suppress}."""
    import anthropic
    client = anthropic.Anthropic()
    p = _PATIENTS[patient_id]
    user = (f"Review patient '{patient_id}'.\n"
            f"Age {p['age']}, sex {p['sex']}, diabetes: {p['diabetes']}, problems: {p.get('problems')}.\n"
            f"Medications: {[m['name'] for m in p['medications']]}.\n"
            f"Use the tools to gather the facts, then submit_review.")
    messages = [{"role": "user", "content": user}]

    for _ in range(12):  # generous cap on tool-use turns
        resp = client.messages.create(
            model=MODEL, max_tokens=8000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=SYSTEM, tools=TOOL_SCHEMAS, messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            break
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if block.name == "submit_review":
                if verbose:
                    print(json.dumps(block.input, indent=2))
                return {"surface": block.input.get("surface", []),
                        "suppress": block.input.get("suppress", [])}
            fn = CORE_TOOLS.get(block.name)
            out = fn(block.input["patient_id"]) if fn else {"error": "unknown tool"}
            if verbose:
                print(f"  [{block.name}] -> {json.dumps(out)}")
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out)})
        messages.append({"role": "user", "content": results})
    return {"surface": [], "suppress": []}


def agent_predict(patient: dict) -> dict:
    """Predictor entry point for evals/score.py."""
    return run_review(patient["id"])


if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "hero-01"
    print(f"=== Sentinel review: {pid} ===")
    run_review(pid, verbose=True)
