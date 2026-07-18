# Sentinel — Reasoning & Guideline Linking (Functional Spec)

Scope: behavior and data requirements for the Clinical Reasoning Panel — the explanation
Sentinel shows when it recommends an action or suppresses an alert. This file covers *how it
works*; the visual styling of the panel lives in the design prompt (`sentinel-design-prompt.md`).

## Requirement

Whenever the interface displays its reasoning — suppression logic, or why something was
recommended — every referenced clinical guideline must be a hyperlink to its source, not a
plain-text mention. A clinician should be able to click the guideline and land on the exact
protocol, dosing reference, threshold table, or care pathway that drove the decision.

## Behavior

- **Link target.** Each cited guideline resolves to its source document, deep-linked to the
  relevant section/anchor where possible (not just the document's landing page).
- **New tab.** Guideline links open in a new tab (`target="_blank"`, `rel="noopener"`) so the
  clinician keeps their place in the dashboard.
- **Traceability.** The panel footer names the rule and version that produced the decision and a
  timestamp (e.g., "Alert rule: SpO₂ low-threshold v3 · 14:22").
- **Missing source fallback.** If a cited guideline has no resolvable source, render the name as
  plain text with a small muted "source unavailable" tag — never a dead/broken link.
- **Access.** If a source sits behind the clinic's licensed reference system, the link routes
  through that system's SSO rather than exposing a raw external URL.

## Data requirements

For links to resolve, each guideline reference emitted by the recommendation/suppression logic
must carry more than a display name. Minimum fields per reference:

| Field         | Description                                                        |
| ------------- | ------------------------------------------------------------------ |
| `id`          | Stable identifier for the guideline/protocol                       |
| `title`       | Human-readable name shown in the panel                             |
| `source_url`  | Resolvable link to the source (deep-linked to the section if able) |
| `section`     | Optional anchor/section reference within the source                |
| `version`     | Guideline version, for traceability and audit                     |

If the logic currently emits guideline names as strings only, it needs to also emit `source_url`
(or an `id` that maps to one via a lookup table) so the UI has a target to link to.

## Out of scope (here)

- Visual styling of the panel and links → `sentinel-design-prompt.md`
- The clinical rules themselves (thresholds, recommendation criteria) → clinical rules config
