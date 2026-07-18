# Sentinel

**The between-visit clinical review no clinician has time to run — for chronic kidney disease.**

Chronic disease isn't managed in the visit; it's managed in the 364 days *between* visits, where today almost nothing happens until the patient deteriorates and shows up in the ED. Sentinel is an agent that runs that review continuously: it reasons over a patient's longitudinal record, catches a slow decline that's invisible value-by-value, flags a now-indicated treatment the patient isn't on, drafts a referral — and, critically, **knows what *not* to surface**, so a clinician actually trusts it.

CKD is the first wedge: clear labs, clear KDIGO 2024 guidelines, clear deterioration signals, and a real, catchable under-treatment pattern (the non-diabetic albuminuric patient who qualifies for an SGLT2 inhibitor and was never started).

## Architecture

A hard split between deterministic clinical logic and probabilistic language reasoning, human in the loop:

- **Deterministic core** (`core/`) — staging, eGFR slope-fitting, guideline thresholds, suppression rules as tested functions. **Every number in the output originates here.** If a figure appears the core didn't compute, that's a bug.
- **Agent layer** — Claude plans, calls the core functions as tools, sequences the longitudinal reasoning, and composes the ranked action list + referral prose. The model never invents a threshold.
- **Eval harness** (`evals/`) — scores the agent against a 50-patient gold set. Quantified correctness is the evidence of rigour.

Not RAG: guideline logic is *encoded as testable thresholds the model cannot override*, which is stronger than retrieving guideline text and hoping.

## The number that matters

A naive rule engine fires wrong **48.6%** of the time and recommends starting drugs into hyperkalaemia (**0%** on safety-gating). Sentinel's suppression layer drives false alarms to **0%**. The product is the gap between those two rows.

```
python3 data/from_wiki.py           # project the gold set into the app schema -> patients.json
python3 core/test_core.py           # 22 unit tests + core-vs-goldset cross-check
python3 evals/score.py              # Sentinel target vs naive baseline
python3 evals/run_agent.py          # live Claude agent as a third row (needs anthropic + API key)

cd ui && npm install && npm run dev # the clinician surface: panel view -> hero -> 3 panels
```

## Repo

```
core/
  clinical_core.py        deterministic KDIGO tools: staging, slope, KFRE, gaps, suppression
  test_core.py            22 unit tests + cross-check that core agrees with the gold set on all 50
data/
  from_wiki.py            projects the gold set into the app schema -> patients.json
  patients.json           50 patients in the app schema, generated from the gold set
docs/
  sentinel_demo_patients_50   the clinician-authored gold set: 50 CKD patients + ground-truth expected
agent/
  review_agent.py         Claude plans + calls the core tools (by patient_id, on real data) -> submit_review
evals/
  framework.md            personas -> jobs-to-be-done -> eval categories -> metrics
  score.py                the harness: false-alarm & missed-catch rates, per-JTBD/persona
  run_agent.py            scores the live agent next to the naive floor and oracle ceiling
ui/
  src/App.jsx             panel view -> hero detail: eGFR trajectory, ranked actions,
                          draft referral, and the suppression panel (Vite + React)
```

See [`evals/framework.md`](evals/framework.md) for the personas, jobs-to-be-done, and how the evals map to them.

*Synthetic data only. No real PHI. Decision support, not autonomous prescribing. KDIGO 2024 basis.*
