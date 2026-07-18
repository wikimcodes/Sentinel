# Sentinel — Eval Framework
### Personas · Jobs-to-be-done · Evals

Sentinel is the between-visit clinical review no clinician has time to run, for chronic kidney disease. This document defines **who** relies on it, the **job** each of them needs done, and the **evals** that prove it does that job — and, critically, that it *withholds* what it shouldn't say.

The whole framework is built to defend one claim: **detection is easy; trustworthy detection is the scarce resource.** The metrics below are designed so that a system which merely detects scores well on the easy persona and fails the hard one.

---

## 1. Personas — who consumes the output

| Persona | Role | The job they hire Sentinel for |
|---|---|---|
| **Amara** | Panel GP (2,000+ patients, sees each CKD patient every 6–12 months) | "Show me which patients *changed* between visits so I spend my minutes on the ones who matter." |
| **Bola** | Care-coordinating nurse (runs the CKD register / recall) | "Give me a prioritised worklist — who needs a lab, a titration, or a referral — so nothing slips." |
| **Chen** | Nephrology-adjacent reviewer (validates escalations) | "Show me the reasoning *and the ruled-out confounders* so I can trust or overrule in seconds." |

**Non-user:** the patient (secondary beneficiary). Sentinel is decision support with a human in the loop — it does not prescribe or send.

Chen is the persona that decides adoption. A GP can be impressed by a risk grid; a reviewer only trusts a tool that demonstrably knows what *not* to say. That is why Chen owns the suppression and safety jobs, and why half the gold set is his.

---

## 2. Jobs-to-be-done → the agent's four functions

| JTBD | Persona | What "done" means | Agent function |
|---|---|---|---|
| **stratify** | Amara | Every patient placed on the KDIGO CGA risk grid | Risk-stratify |
| **catch** | Amara | The slow decline that's invisible visit-by-visit is surfaced | Detect trajectory |
| **close_gap** | Bola | The now-indicated drug the patient isn't on is named | Detect gaps |
| **escalate** | Bola | A referral is drafted (not sent) when criteria are met | Referral |
| **withhold** | Chen | What was considered and deliberately *not* surfaced is shown, with a reason | **Suppress** |
| **gate** | Chen | A drug that's unsafe *right now* is never recommended as a clean start | Suppress (safety) |

`withhold` and `gate` are the moat. Every generic LLM wrapper can do `stratify`/`catch`/`close_gap`. Almost none do `withhold`/`gate`, because it requires encoding *when a true-looking signal is not actionable*.

---

## 3. Eval categories — the 50-patient gold set

Each patient is tagged `persona · jtbd · category · difficulty` and carries a ground-truth `expected` block (what MUST surface, what MUST be suppressed, and why). Ground truth is the **clinician-authored gold set** (`docs/sentinel_demo_patients_50`) encoding KDIGO 2024 — deliberately separate from `core/` (the tools the agent calls), so the eval scores the agent against independent truth, not itself.

| Category | Primary JTBD | n | What it proves |
|---|---|---|---|
| **C1 · Staging & definition gate** | stratify | 6 | Correct CGA staging; G2/A1-no-marker is *not* CKD and must not surface |
| **C2 · True rapid progression** | catch | 7 | Catches ≥5 mL/min/yr decline across steady-state values |
| **C3 · Suppress false decline** | withhold | 11 | AKI dips, trimethoprim pseudo-rise, low-muscle-mass eGFR — all suppressed |
| **C4 · Correct gap fire** | close_gap | 10 | SGLT2i (incl. **non-diabetic**), finerenone (diabetic only), statin, RASi |
| **C5 · Correct gap non-fire** | withhold | 6 | Already-optimised & below-threshold patients surface nothing |
| **C6 · Safety gating** | gate | 6 | Drug indicated but K⁺ ≥ 5.5 → "indicated, gated", never a clean start |
| **C7 · Referral fire / non-fire** | escalate | 4 | eGFR<30 / heavy albuminuria / KFRE≥5% / rapid → refer; else withhold |

Difficulty is tagged `easy | medium | hard`; the hard cases cluster in C3/C6 (the suppression and gating jobs).

---

## 4. Metrics — how we score

Run: `python3 evals/score.py`. Item identity is compared on **type + drug**, ignoring free-text summary.

| Metric | Definition | Why it's here |
|---|---|---|
| **False-alarm rate** | of everything surfaced, fraction that was wrong | The **"cry wolf" number** — the moat. Alert fatigue is what gets tools switched off. |
| **Missed-catch rate** | of everything that should surface, fraction missed | The **safety number** — a missed decline or gap is a harmed patient. |
| Surface precision / recall | standard | Decomposes the two rates above. |
| **Suppression recall** | of what should be withheld, fraction correctly withheld | Directly measures the `withhold` job. |
| Staging accuracy | CKD-gate + CGA correct | Floor competence for `stratify`. |
| Per-JTBD / per-persona exact-match | patient passes if surfaced set exactly matches ground truth | Shows *where* a system fails — the tell is a high Amara score with a low Chen score. |

### Baseline result — the gap *is* the product

A **naive rule engine** (flags every dip and every label-indicated drug, wrong thresholds, no suppression) vs the **Sentinel target**:

| | Naive rule engine | Sentinel target |
|---|---|---|
| False-alarm rate | **48.6%** | **0.0%** |
| Missed-catch rate | 20.8% | 0.0% |
| Suppression recall | 0.0% | 100.0% |
| `gate` JTBD (hyperkalaemia) | **0%** | 100% |
| `withhold` JTBD | 6% | 100% |
| Persona: Amara (easy) | 92% | 100% |
| **Persona: Chen (hard)** | **4%** | 100% |

The naive engine looks fine to the GP (92%) and is useless to the reviewer (4%) — it recommends starting drugs into hyperkalaemia (`gate` = 0%). That 4%→100% jump for Chen is the entire thesis in one number.

> The Sentinel-target row is the oracle (ground-truth ceiling). The live agent (Claude planning over the deterministic `core/` tools) is scored against the same gold set; its job is to close the distance to that ceiling. The naive row is the floor any "if-statements-plus-a-chatbot" competitor sits at.

---

## 5. How to extend

- **New patient:** add a case to the gold set (`docs/sentinel_demo_patients_50`) with its `expected` block, then run `data/from_wiki.py` to project it into the app.
- **New drug / rule:** add it to the oracle *and* to `core/`, then re-run `score.py` — the gold set catches regressions.
- **Wire the live agent:** implement `agent_predict(p)` in `score.py` to return `{surface, suppress}` from Claude + `core/` tools, and report it as a third row next to naive and target.
