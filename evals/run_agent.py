"""
Run the live Sentinel agent (Claude + core tools) over the gold set and print a
clean 3-row comparison: the naive floor, the live agent, and the oracle ceiling.

    python3 evals/run_agent.py            # all 50 patients
    python3 evals/run_agent.py 8          # first 8 (fast/cheap smoke test)

Requires: pip install anthropic  +  ANTHROPIC_API_KEY (or `ant auth login`).
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "agent"))
import score
from review_agent import run_review

patients = json.load(open(os.path.join(HERE, "..", "data", "patients.json")))["patients"]
limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(patients)
subset = patients[:limit]

cache = {}
def agent(p):
    if p["id"] not in cache:
        sys.stderr.write(f"  reviewing {p['id']} ...\n"); sys.stderr.flush()
        cache[p["id"]] = run_review(p["id"])
    return cache[p["id"]]

def row(name, m):
    return (f"  {name:<38}"
            f"{m['false_alarm_rate']*100:>10.1f}%"
            f"{m['missed_catch_rate']*100:>13.1f}%"
            f"{m['suppression_recall']*100:>13.0f}%"
            f"{m['persona_pass'].get('chen', 0)*100:>11.0f}%")

print(f"\nScoring {len(subset)} patients — running the live agent (this makes one Claude call per patient)...\n",
      file=sys.stderr)
naive = score.score(score.naive, subset)
live = score.score(agent, subset)          # <- the Claude calls happen here
oracle = score.score(score.perfect, subset)

hdr = f"  {'':<38}{'false-alarm':>11}{'missed-catch':>13}{'suppression':>13}{'Chen(hard)':>12}"
print(f"\n╔═══ Sentinel eval — n={len(subset)} ═══")
print(hdr)
print("  " + "─" * 86)
print(row("Naive rule engine (no suppression)", naive))
print(row("Sentinel LIVE agent (Claude + core)", live))
print(row("Oracle ceiling (deterministic core)", oracle))
print("  " + "─" * 86)
print("  false-alarm = the moat (lower is better) · Chen = the reviewer persona who decides adoption")
print("\n  The live agent's job is to close the distance from the naive floor to the oracle ceiling.\n")
