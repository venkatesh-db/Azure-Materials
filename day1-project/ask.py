"""CLI: ask the Runbook Knowledge Agent a question.

    python3 ask.py "How do I recover from a database connection timeout?"
    python3 ask.py            # runs a short scripted demo
"""
import sys

from agent import RunbookKnowledgeAgent

DEMO_QUESTIONS = [
    "How do I recover from a database connection timeout?",
    "Something is broken",
    "How do I fix a broken office printer?",
]


def main() -> None:
    questions = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else DEMO_QUESTIONS

    with RunbookKnowledgeAgent() as agent:
        print(f"agent: {agent.agent_id}\n")
        for question in questions:
            print("=" * 72)
            print(f"Q: {question}\n")
            print(agent.ask(question).summary())
            print()


if __name__ == "__main__":
    main()
