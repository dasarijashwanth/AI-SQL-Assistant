"""Run the Day 3 eval harness and write the results files.

Usage (from the project root, venv active):

    python scripts/run_eval.py [--questions evals/questions_day3.json]

Writes evals/results_day3.md and evals/results_day3.json, prints the
score, and always exits 0: the harness measures, it does not gate.
Requires the demo database (python scripts/build_demo_db.py) and runs
fully offline unless OPENAI_API_KEY is set.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.eval import load_questions, run_eval, write_results  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Day 3 eval.")
    parser.add_argument(
        "--questions",
        default=str(PROJECT_ROOT / "evals" / "questions_day3.json"),
    )
    args = parser.parse_args()
    questions = load_questions(args.questions)
    summary = run_eval(questions)
    write_results(
        summary,
        PROJECT_ROOT / "evals" / "results_day3.md",
        PROJECT_ROOT / "evals" / "results_day3.json",
    )
    print(
        f"Score: {summary['passed']}/{summary['total']} "
        f"(agent {summary['agent_passed']}/{summary['agent_total']}, "
        f"adversarial {summary['adversarial_passed']}/"
        f"{summary['adversarial_total']})"
    )
    print(f"Average agent latency: {summary['avg_agent_latency_ms']} ms")
    print(
        "Mutation check unchanged: "
        f"{summary['mutation_check']['unchanged']}"
    )
    for record in summary["results"]:
        if not record["passed"]:
            print(f"FAIL Q{record['id']}: {'; '.join(record['reasons'])}")


if __name__ == "__main__":
    main()
