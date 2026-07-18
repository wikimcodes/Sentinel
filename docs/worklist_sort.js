// Sentinel — worklist sort/filter reference implementation.
// Operates on the `patients` array from sentinel_demo_cases.json.
// Each patient carries: name, risk_tier, trigger.date, summary.{latest_egfr, action_count, needs_attention}.
// Default sort is "most_recent" — newest trigger event first, which places the three
// most recently-changed patients at the top of the list (no pinning, no special-casing).

const TIER_RANK = { very_high: 0, high: 1, moderate: 2, low: 3 };

const byDateDesc = (a, b) =>
  (b.trigger?.date || "").localeCompare(a.trigger?.date || "");

/**
 * Sort a copy of the patient list by the chosen mode.
 * @param {Array} patients
 * @param {"most_recent"|"urgency"|"needs_attention"|"az"|"egfr"} mode
 */
export function sortWorklist(patients, mode = "most_recent") {
  const p = [...patients];
  switch (mode) {
    case "urgency":
      // sickest first: risk tier, then most open actions, then most recent
      return p.sort(
        (a, b) =>
          TIER_RANK[a.risk_tier] - TIER_RANK[b.risk_tier] ||
          b.summary.action_count - a.summary.action_count ||
          byDateDesc(a, b)
      );

    case "needs_attention":
      // anything with an unresolved item rises above anything settled, then by risk, then recency
      return p.sort(
        (a, b) =>
          Number(b.summary.needs_attention) - Number(a.summary.needs_attention) ||
          TIER_RANK[a.risk_tier] - TIER_RANK[b.risk_tier] ||
          byDateDesc(a, b)
      );

    case "az":
      return p.sort((a, b) => a.name.localeCompare(b.name));

    case "egfr":
      // most impaired kidney function first (missing eGFR sorts last)
      return p.sort(
        (a, b) =>
          (a.summary.latest_egfr ?? Infinity) - (b.summary.latest_egfr ?? Infinity)
      );

    case "most_recent":
    default:
      return p.sort(byDateDesc);
  }
}

// Optional filters, composable with any sort above.
export const filters = {
  needsAttention: (patients) => patients.filter((p) => p.summary.needs_attention),
  tier: (patients, tier) => patients.filter((p) => p.risk_tier === tier),
  diabetic: (patients, isDiabetic) =>
    patients.filter((p) => p.demographics.diabetes === isDiabetic),
};

// Example usage in the worklist component:
//   const view = sortWorklist(patients, sortMode);            // sortMode from the dropdown
//   const shown = onlyOpen ? filters.needsAttention(view) : view;
