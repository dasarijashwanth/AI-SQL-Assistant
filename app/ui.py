"""Streamlit UI for the AI SQL Assistant (Day 5).

Runs fully offline by default: unless OPENAI_API_KEY is set, the
deterministic fake-LLM path in app/agent_service.py answers every
question, so no API keys are needed. A real model is used only when
OPENAI_API_KEY is present (model name from SQL_ASSISTANT_MODEL).

Run it with:

    streamlit run app/ui.py
"""
import streamlit as st

from .agent_service import ask_question
from .config import get_model_name, llm_mode

# Streamlit reruns this script top-to-bottom on every interaction, so
# each question is an independent agent run with its own repair budget.
SAMPLE_QUESTIONS = [
    "What is the total revenue?",
    "What are the top 5 products by units sold?",
    "How many orders were placed per month?",
    "What is the total revenue with a broken column?",
    "What is the total revenue, always broken?",
]


def status_label(result: dict) -> str:
    """One-word groundedness state for an ask_question response."""
    if result.get("error"):
        return "failed"
    if result.get("repaired"):
        return "repaired"
    return "grounded"


def format_attempt(attempt: dict, index: int) -> str:
    """One-line human summary of a single executed attempt."""
    error = attempt.get("error")
    if error:
        return f"Attempt {index}: failed — {error}"
    return f"Attempt {index}: succeeded"


def run_question(question: str) -> dict:
    """Run one question through the agent service.

    Returns the ask_question response dict unchanged. If the service
    itself raises (for example, the agent ran no query at all), the
    failure is returned as an error-shaped dict so the UI can render
    it instead of crashing.
    """
    try:
        return ask_question(question)
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim in the UI
        return {
            "question": question,
            "sql": "",
            "rows": [],
            "row_count": 0,
            "explanation": str(exc),
            "attempts": [],
            "repaired": False,
            "error": str(exc),
        }


def render_result(result: dict) -> None:
    """Render an ask_question response: answer, SQL, attempts trace."""
    state = status_label(result)
    if state == "failed":
        st.error("The query failed.")
        st.write(result.get("explanation") or "No explanation available.")
    elif state == "repaired":
        st.warning("Answered after one repair attempt.")
        st.write(result.get("explanation") or "")
    else:
        st.success("Answered from the database.")
        st.write(result.get("explanation") or "")
    st.metric("Rows returned", result.get("row_count", 0))

    if result.get("sql"):
        with st.expander("Generated SQL"):
            st.code(result["sql"], language="sql")

    attempts = result.get("attempts") or []
    if attempts:
        with st.expander(f"Attempts trace ({len(attempts)})"):
            for i, attempt in enumerate(attempts, start=1):
                st.write(format_attempt(attempt, i))
                if attempt.get("sql"):
                    st.code(attempt["sql"], language="sql")

    rows = result.get("rows") or []
    if rows:
        with st.expander("Result rows"):
            st.dataframe(rows)


def main() -> None:
    st.set_page_config(page_title="AI SQL Assistant", layout="wide")
    st.title("AI SQL Assistant")
    mode = llm_mode()
    if mode == "fake":
        st.caption("Offline demo mode: deterministic fake LLM, no API key needed.")
    else:
        st.caption(f"Live mode: OpenAI model {get_model_name()}.")

    if "result" not in st.session_state:
        st.session_state["result"] = None

    question = st.text_input(
        "Ask a question about the e-commerce orders database:",
        placeholder="What is the total revenue?",
    )
    if st.button("Run question", type="primary") and question.strip():
        with st.spinner("Asking the agent..."):
            st.session_state["result"] = run_question(question.strip())

    st.write("Or try one of these:")
    cols = st.columns(len(SAMPLE_QUESTIONS))
    for col, sample in zip(cols, SAMPLE_QUESTIONS):
        if col.button(sample, key=f"sample-{sample[:12]}"):
            with st.spinner("Asking the agent..."):
                st.session_state["result"] = run_question(sample)

    if st.session_state["result"] is not None:
        render_result(st.session_state["result"])


if __name__ == "__main__":
    main()
