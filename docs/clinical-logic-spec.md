# Sentinel — Clinical Logic Specification
### v1.0 · Source of truth for the deterministic clinical core

**Guideline basis:** KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD (published March 2024, Kidney International), with the KDIGO 2013 Lipid and KDIGO 2022 Diabetes-in-CKD guidelines where noted for domains the 2024 CKD guideline defers to. As of this writing the KDIGO 2024 CKD guideline remains the current global standard for CKD evaluation and management; no later guideline supersedes it. A focused update to Chapter 3 (delaying progression and managing complications) is in progress — addressing SGLT2 inhibitors, GLP-1 receptor agonists, and nonsteroidal MRA in CKD *without* diabetes — but is unpublished, so this spec builds to the 2024 guideline.
**Scope of this version:** RAS inhibitors (ACEi/ARB) fully specified. SGLT2 inhibitors, statins and nonsteroidal MRA are stubbed with verified indications and marked TODO for post-event expansion.
**Companion document:** the PRD defines product scope and architecture; this document defines the clinical thresholds and edge-case logic the deterministic core must implement.

**Safety framing:** Sentinel is decision support with a human in the loop. It proposes; a clinician approves. It runs on synthetic data. Nothing here is autonomous prescribing.

---

## Provenance legend

Every threshold below is tagged so the source is auditable:

- **[REC n, grade]** — KDIGO graded recommendation (e.g. 1A, 1B, 2A, 2B).
- **[PP n]** — KDIGO practice point (guidance without a formal grade).
- **[TRIAL]** — derived from a cited trial rather than a threshold number in the guideline.
- **[CONV]** — implementation convention for the code; not a specific guideline number. Verify against local policy before clinical use.

Where a value is **[CONV]**, the code owns it and it must be easy to change in one place; it is not presented to judges as a guideline mandate.

---

## 1. RAS inhibitors (ACEi / ARB) — fully specified

### 1.1 Indication logic (when "not on a RASi" is a genuine gap)

Indication depends on **diabetes status × albuminuria category**, not albuminuria alone. This is the correction to any "A2/A3" shorthand. KDIGO 2024 applies these independently of blood pressure — the work group deliberately removed the hypertension precondition carried by the earlier BP guideline, so the indication stands on albuminuria and diabetes status alone.

| Diabetes | Albuminuria | RASi status | Basis |
|---|---|---|---|
| No | A3 (>300 mg/g) | **Indicated** — strong (hard gap) | [REC 3.6.1, 1B] |
| No | A2 (30–300) | **Suggested** — weak (soft prompt) | [REC 3.6.2, 2C] |
| No | A1 (<30) | Only for a specific indication (hypertension, HFrEF) | [PP 3.6.6] |
| Yes (T2D) | A2 or A3 | **Indicated** — strong (hard gap) | [REC 3.6.3, 1B] |
| Yes (T2D) | A1 | Only for a specific indication (hypertension, HFrEF) | [PP 3.6.6] |

**Hard gap fires only when:** the patient meets a strong ("Indicated") row above, AND is not currently on an ACEi or ARB, AND no contraindication in §1.2 applies, AND not blocked by the potassium gate in §1.6.

A patient in the weak ("Suggested", 2C) row is surfaced as a softer prompt, not a hard gap, and must be labelled as a weaker-evidence suggestion in the output. The distinction is deliberate: it mirrors the guideline's own strength of recommendation, so the agent never presents 2C evidence with the same force as 1B.

### 1.2 Contraindications / do-not-start (hard blocks) [CONV — standard pharmacologic contraindications]

Do not propose initiation if any of:

- Known bilateral renal artery stenosis (or stenosis in a single functioning kidney).
- Pregnancy or planning pregnancy (ACEi/ARB are fetotoxic).
- Prior ACEi-induced angioedema (avoid ACEi; ARB only with specialist caution).
- Known hypersensitivity to the class.
- Baseline potassium above the initiation gate that cannot be corrected (see §1.6).

These are not KDIGO-specific numbers; they are standard prescribing contraindications and should be encoded as a pre-filter that runs before the indication logic surfaces anything.

### 1.3 Expected physiology on initiation (must be encoded, or the agent misreads it)

An eGFR dip / small creatinine rise on starting or up-titrating a RASi is **expected and haemodynamic** — it reflects reduced intraglomerular pressure from efferent arteriolar vasodilation, not injury. The core must treat a sub-threshold early change as normal, never as progression. [PP context; KDIGO 2024]

### 1.4 Creatinine response after initiation or dose increase

Recheck creatinine at **2–4 weeks** after initiation or any dose increase [PP 3.6.2]. Then apply:

| Creatinine change from baseline | Interpretation | Action |
|---|---|---|
| Rise < 30% (≈ eGFR fall < 25%) | Expected haemodynamic effect | Continue; routine monitoring; **do not** flag as progression |
| Rise ≥ 30% within 4 weeks | Not attributable to RASi by default | Investigate AKI: volume depletion, NSAIDs/nephrotoxins, renovascular disease; hold RASi pending workup; recheck |

Basis: [PP] continue unless serum creatinine rises >30% within 4 weeks of initiation/dose increase; a rise ≥30% should trigger investigation for AKI. The 30% is a creatinine-*rise* threshold; the equivalent eGFR-*fall* figure is ~25%.

### 1.5 Potassium bands after / around initiation

KDIGO's stance is explicit and must be encoded faithfully: **hyperkalaemia is generally managed rather than treated by stopping the RASi** [PP 3.6.3]. Reduction or discontinuation is reserved for hyperkalaemia that is *uncontrolled despite treatment*, or symptomatic hypotension, or to reduce uraemic symptoms in advanced failure [KDIGO 2024].

| Potassium (mmol/L) | Classification | Action |
|---|---|---|
| ≤ 5.0 | Normal | Proceed / continue [CONV] |
| 5.1 – 5.5 | Mild | Initiate/continue with mitigation (dietary K restriction, review K-raising drugs, loop diuretic, potassium binder) and closer monitoring [PP 3.6.3] |
| > 5.5 (persistent) | Moderate | Optimise potassium first; potassium binders may enable continuation rather than withdrawal [PP 3.6.3]; do not present a clean "start now" — surface as gated |
| ≥ 6.0 or symptomatic / ECG changes | Severe | Urgent management; hold RASi acutely, treat hyperkalaemia, reintroduce once controlled [CONV — safety, not a KDIGO stop-number] |

The 6.0 stop point is a **[CONV]** operational safety threshold. It must not be presented to a judge as "the guideline says stop at 6" — the guideline says treat the potassium.

### 1.6 Initiation potassium gate (links to the demo)

Before proposing initiation, the core checks the latest potassium against the §1.5 bands. If ≤ 5.0, propose initiation normally. If above, output the **safety-gated** form: "RASi indicated — gated on hyperkalaemia; treat potassium first," never a clean start action. This is the live-demo beat: editing the hero patient's potassium above 5.5 flips the recommendation from "initiate" to "indicated, gated."

### 1.7 Monitoring schedule

Check BP, serum creatinine and serum potassium **within 2–4 weeks** of initiation or dose increase, with earlier checks if baseline GFR is low or potassium is borderline/high [PP 3.6.2]. Each initiation action Sentinel proposes must automatically pair with a scheduled 2–4 week recheck order (this is the coordination behaviour shown in the demo cases).

### 1.8 Continuation at low eGFR

Continue the ACEi or ARB even when eGFR falls below 30 [PP 3.6.7]. STOP-ACEi (NEJM 2022) showed no eGFR benefit from stopping in advanced CKD, and observational data (Fu et al, JASN 2021) support continued cardiovascular benefit. The core must not generate a "stop RASi" suggestion triggered by low eGFR alone.

### 1.9 Combination rule

Never combine any two of ACEi, ARB, or direct renin inhibitor [REC 3.6.4, 1B]. If the medication list already contains one class, the core must not propose adding another RAS-acting agent, and should flag any existing dual-blockade as an error to review.

### 1.10 Dose titration

Target the highest approved tolerated dose, because trial benefits were achieved at those doses [PP 3.6.1]. If the patient is on a sub-maximal dose and tolerating it (potassium and creatinine within §1.4–§1.5 bounds), surface an up-titration suggestion, paired with the §1.7 recheck.

### 1.11 Reduce / discontinue criteria

Propose dose reduction or discontinuation only for: symptomatic hypotension; hyperkalaemia uncontrolled despite the §1.5 measures; or to reduce uraemic symptoms while managing kidney failure [KDIGO 2024]. All three are clinician-confirmed actions, never automatic.

### 1.12 Gap-detection pseudocode (RASi)

```
function rasi_status(patient):
    if has_contraindication(patient):            # §1.2
        return NO_ACTION("contraindicated")
    if on_rasi(patient):
        if suboptimal_dose(patient) and labs_within_bounds(patient):
            return SUGGEST("up-titrate", schedule_recheck=2_4_weeks)   # §1.10, §1.7
        return NO_ACTION("already on RASi")       # suppression: no nag
    indication = rasi_indication(patient.diabetes, patient.albuminuria)  # §1.1 table -> STRONG | WEAK | NONE
    if indication == NONE:
        return NO_ACTION("not indicated")
    if latest_potassium(patient) > 5.0:           # §1.6 gate
        return GATED("indicated — treat potassium first")
    strength = "hard_gap" if indication == STRONG else "consider"   # STRONG=1B, WEAK=2C
    return PROPOSE(initiate_rasi, strength, schedule_recheck=2_4_weeks)  # §1.7
```

### 1.13 Interaction with the suppression layer

The RASi logic must defer to suppression rules: an eGFR/creatinine movement that coincides with acute illness, a resolved AKI, or a creatinine pseudo-rise (trimethoprim, cimetidine) is not a valid trigger for holding or stopping a RASi. Route those to the suppression panel, not to a RASi action.

### 1.14 Outcomes rationale (the "why starting too late harms" narrative)

For the pitch and for reviewer credibility: RASi lower intraglomerular pressure and reduce albuminuria, and albuminuria is a *driver* of progression, not merely a marker — so the benefit is disease-modifying and accrues over time. Nephron loss is largely irreversible, so every interval a genuinely-indicated patient spends untreated is avoidable cumulative loss that cannot be recovered later. The expected early creatinine bump is haemodynamic and reversible; misreading it as injury is a common reason clinicians wrongly withhold or stop the drug, which forfeits long-term benefit. STOP-ACEi reinforces the same direction: stopping does not preserve function even in advanced CKD, so the correct posture is *start when indicated and continue* — which is precisely the miss Sentinel is built to catch.

---

## 2. SGLT2 inhibitors — STUB (verified indications; logic TODO)

Indications, confirmed against KDIGO 2024:

- T2D + CKD + eGFR ≥ 20 [REC 3.7.1, 1A].
- CKD with eGFR ≥ 20 and urine ACR ≥ 200 mg/g (≥ 20 mg/mmol), **or** heart failure irrespective of albuminuria [REC, 1A].
- eGFR 20–45 with ACR < 200 mg/g [REC 3.7.3, 2B].
- Once started, it is reasonable to continue even if eGFR later falls below 20, unless not tolerated or dialysis is started [PP 3.7.1].
- Reasonable to withhold during prolonged fasting, surgery, or critical illness (sick-day guidance) [PP 3.7.2].
- The reversible eGFR dip on initiation is generally **not** a reason to discontinue, and does not change monitoring frequency [PP 3.7.3].

TODO for expansion: continuation-below-threshold logic, volume/euglycaemic-DKA cautions, sick-day handling, initiation potassium/creatinine interplay, and the non-diabetic hero-catch logic (already the demo centrepiece).

## 3. Statins — STUB (indications verified)

Lipid management is deferred by the KDIGO 2024 CKD guideline to the KDIGO 2013 Lipid Management in CKD guideline; cut-points below are from that guideline. The approach is age-based rather than LDL-target-based — no specific LDL goal is set.

- Adults ≥ 50 with eGFR < 60 (G3a–G5), not on dialysis or transplant: statin **or** statin/ezetimibe [KDIGO 2013 Lipids 2.1.1, 1A].
- Adults ≥ 50 with CKD and eGFR ≥ 60 (G1–G2): statin [2.1.2].
- Adults 18–49 with CKD, not on dialysis or transplant: statin suggested if one or more of — known coronary disease (MI or coronary revascularisation), diabetes, prior ischaemic stroke, or estimated 10-year incidence of coronary death/non-fatal MI > 10% [2.2, 2A].
- Dialysis-dependent CKD: do **not** initiate statins (2A); continue if already established at dialysis start.

TODO for expansion: statin dose-adjustment cautions at low eGFR, transplant-recipient handling, and gap-detection wiring.

## 4. Nonsteroidal MRA (finerenone) — STUB (verified indication; logic TODO)

Indication, confirmed against KDIGO 2024: adults with **T2D**, eGFR > 25, **normal serum potassium**, and albuminuria (> 30 mg/g / > 3 mg/mmol) despite maximum tolerated RASi [REC 3.8.1, 2A]. May be added on top of a RASi and an SGLT2i [PP 3.8.2]. Select patients with consistently normal potassium and monitor potassium regularly after initiation [PP 3.8.3].

TODO for expansion: potassium initiation gate (trial initiation used serum K ≤ 4.8 mmol/L in FIDELIO-DKD — [TRIAL], verify), monitoring cadence, and interaction with the shared potassium constraint in §5. Do not gate the non-diabetic hero patient on finerenone. For the pitch, the honest recency note is: the diabetes-specific guidance remains KDIGO 2022, and KDIGO's in-progress focused update to Chapter 3 of the 2024 CKD guideline is examining nsMRA (alongside SGLT2i and GLP-1 receptor agonists) in CKD without diabetes; combination therapy is supported by trial evidence such as CONFIDENCE (finerenone + empagliflozin). Build to 2024; name the direction of travel without asserting an unpublished recommendation.

---

## 5. Cross-cutting logic

**Shared potassium constraint.** RASi and nonsteroidal MRA both raise potassium. The core should treat potassium as a shared budget: evaluate cumulative hyperkalaemia risk before proposing to add a second potassium-raising agent, and prefer mitigation (binders, diuretics, dietary review) over abandoning a disease-modifying drug, consistent with §1.5.

**Sequencing.** When several pillars are indicated at once (as in the red demo patient), present them as a prioritised, clinician-approved set rather than firing simultaneously — RASi and SGLT2i are foundational; nonsteroidal MRA is added on top once RASi is maximised and potassium is confirmed normal.

**Every number in one place.** All thresholds in this document must live in a single `THRESHOLDS` constant in the core so they are auditable and adjustable, and so the live-demo edit recomputes deterministically.

---

## References

- KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD — Executive Summary (kdigo.org).
- KDOQI US Commentary on the KDIGO 2024 CKD Guideline, American Journal of Kidney Diseases (2024).
- KDIGO 2024 CKD Guidelines, Part 2 — NephJC summary (RASi practice points; STOP-ACEi, Fu et al).
- KDIGO 2024 CKD Guideline: a primer for pharmacists, American Journal of Health-System Pharmacy (2025).
- KDIGO 2013 Clinical Practice Guideline for Lipid Management in CKD (statin cut-points).
- KDIGO 2021 Clinical Practice Guideline for the Management of Blood Pressure in CKD; KDIGO 2022 Diabetes Management in CKD (context for RASi indications).
- STOP-ACEi trial, NEJM 2022; Fu et al, JASN 2021 (continuation at low eGFR).

*Verify all [CONV] and [TRIAL] values against the current guideline text before any real-world use. Graded recommendations and practice points above were cross-checked against the KDIGO 2024 executive summary and KDOQI commentary.*
