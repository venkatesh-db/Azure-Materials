"""Lab 5: evaluate retrieval + grounding and produce the Day 1 evaluation report.

    python lab05_retrieval_evaluation/evaluate.py [--mock|--live] [--include-extended]

Writes reports/day1_evaluation_report.{md,json}. Exit code 1 if any Day 1 target is missed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agentcore.config import REPORTS_DIR, lab_args
from agentcore.day1 import build_knowledge_agent, close_agent
from agentcore.evaluation import DAY1_TARGETS, day1_metrics, meets, score_day1_case, write_report
from agentcore.knowledge_agent import UserContext
from agentcore.tracing import correlation, init_tracing, shutdown_tracing

HERE = Path(__file__).parent


def load(include_extended: bool) -> list[dict]:
    cases = json.loads((HERE / "eval_cases.json").read_text())["cases"]
    if include_extended:
        cases += json.loads((HERE / "extended_cases.json").read_text())["cases"]
    return cases


def main() -> int:
    args, settings = lab_args(__doc__, lambda p: p.add_argument("--include-extended", action="store_true"))
    init_tracing(settings, "lab05")
    agent = build_knowledge_agent(settings)
    results = []
    try:
        for case in load(args.include_extended):
            with correlation():
                r = agent.answer(case["question"], UserContext(groups=tuple(case.get("user_groups", ["it-operations"]))))
            res = score_day1_case(case, r)
            results.append(res)
            print(f"[{'PASS' if res.passed else 'FAIL'}] {case['id']} {case['type']:<28} status={res.status:<19} "
                  f"cited={res.cited} {'; '.join(res.failures)}")
    finally:
        close_agent(agent)
        shutdown_tracing()

    metrics = day1_metrics(results)
    rows = [{"id": r.case["id"], "type": r.case["type"], "passed": r.passed, "status": r.status,
             "failures": r.failures, "retrieved": r.retrieved, "cited": r.cited, "latency_ms": r.latency_ms,
             "tokens": r.tokens, "answer": r.answer} for r in results]
    by_type: dict[str, list[str]] = {}
    for r in results:
        if not r.passed:
            by_type.setdefault(r.case["type"], []).append(r.case["id"])
    analysis = "\n".join(f"- **{t}**: {', '.join(ids)}" for t, ids in by_type.items()) or "- No failures."
    latency = sorted(r.latency_ms for r in results)
    delivered = sum(r.steps_total for r in results)
    withheld = sum(r.removed_by_postcheck for r in results)
    ops = (f"- Model-level grounding (diagnostic): {withheld} of {withheld + delivered} raw model steps "
           f"({withheld / max(1, withheld + delivered) * 100:.1f}%) were withheld by the post-check before delivery\n"
           f"- Cases: {len(results)} | passed: {sum(r.passed for r in results)}\n"
           f"- Median latency: {latency[len(latency) // 2]:.0f} ms | max: {latency[-1]:.0f} ms\n"
           f"- Total tokens: {sum(r.tokens for r in results)}")
    json_path, md_path = write_report(REPORTS_DIR / "day1_evaluation_report", "Day 1 Evaluation Report - "
                                      "Enterprise Runbook Knowledge Agent", settings.mode, metrics, DAY1_TARGETS,
                                      rows, [("Failure analysis", analysis), ("Operational figures", ops)])
    print("\nMetric                       result   target")
    for k, rule in DAY1_TARGETS.items():
        v = metrics[k]
        print(f"  {k:<26} {'n/a' if v is None else f'{v * 100:5.1f}%'}   {rule[0]} {rule[1] * 100:.0f}%  "
              f"{'PASS' if meets(v, rule) else 'FAIL'}")
    print(f"\nReport: {md_path.relative_to(md_path.parent.parent)}")
    return 0 if all(meets(metrics[k], r) for k, r in DAY1_TARGETS.items()) else 1


if __name__ == "__main__":
    sys.exit(main())
