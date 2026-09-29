"""Release gate for IncidentOps AI: reads eval_results.json (from eval.py)
and enforces thresholds. Exits non-zero if not met — same pattern as
azure-agent-demo-setup/day3/check_release_gate.py, adapted for this
system's deterministic structural checks instead of LLM-judge scores.
"""
import json
import sys
from pathlib import Path

RESULTS_PATH = Path(__file__).parent / "eval_results.json"

STATE_CORRECTNESS_THRESHOLD = 0.90
GROUNDING_CORRECTNESS_THRESHOLD = 1.00  # zero tolerance for hallucinated citations


def main():
    if not RESULTS_PATH.exists():
        print(f"FAIL: {RESULTS_PATH} not found. Run eval.py first.")
        sys.exit(1)

    results = json.loads(RESULTS_PATH.read_text())
    total = len(results)
    state_correct = sum(1 for r in results if r["state_correct"])
    state_rate = state_correct / total if total else 0.0

    grounding_applicable = [r for r in results if r["grounding_correct"] is not None]
    grounding_correct = sum(1 for r in grounding_applicable if r["grounding_correct"])
    grounding_rate = grounding_correct / len(grounding_applicable) if grounding_applicable else 1.0

    print(f"State correctness: {state_rate:.0%} (threshold: >={STATE_CORRECTNESS_THRESHOLD:.0%})")
    print(f"Grounding correctness: {grounding_rate:.0%} (threshold: >={GROUNDING_CORRECTNESS_THRESHOLD:.0%})")

    failures = []
    if state_rate < STATE_CORRECTNESS_THRESHOLD:
        failures.append(f"state_correctness {state_rate:.0%} < {STATE_CORRECTNESS_THRESHOLD:.0%}")
    if grounding_rate < GROUNDING_CORRECTNESS_THRESHOLD:
        failures.append(f"grounding_correctness {grounding_rate:.0%} < {GROUNDING_CORRECTNESS_THRESHOLD:.0%}")

    if failures:
        print("\nRELEASE GATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    print("\nRELEASE GATE PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
