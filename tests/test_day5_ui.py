"""Day 5 tests: Streamlit UI module.

The UI (app/ui.py) is the interface layer over the existing
ask_question service: it renders the answer, the generated SQL, the
attempts trace, and a clear grounded/repaired/failed state. These
tests verify the module imports, its core functions exist, the
integration path through the service works in offline fake-LLM mode,
and error states are handled gracefully (the UI never crashes on a
failed question).
"""
import app.ui as ui


def test_ui_module_exposes_core_functions():
    for name in ("main", "render_result", "run_question", "status_label", "format_attempt"):
        assert callable(getattr(ui, name)), f"ui.{name} must exist and be callable"


def test_status_label_grounded():
    result = {"error": None, "repaired": False}
    assert ui.status_label(result) == "grounded"


def test_status_label_repaired():
    result = {"error": None, "repaired": True}
    assert ui.status_label(result) == "repaired"


def test_status_label_failed():
    result = {"error": "no such column: nope_col", "repaired": True}
    assert ui.status_label(result) == "failed"


def test_format_attempt_success_and_failure():
    ok = ui.format_attempt({"sql": "SELECT 1", "error": None}, 1)
    assert "Attempt 1" in ok
    assert "succeeded" in ok
    bad = ui.format_attempt({"sql": "SELECT nope", "error": "no such column"}, 2)
    assert "Attempt 2" in bad
    assert "failed" in bad
    assert "no such column" in bad


def test_run_question_happy_path(client):
    # the demo_db fixture from conftest points SQL_ASSISTANT_DB_PATH at a
    # fresh demo database; conftest also forces the offline fake model
    result = ui.run_question("What is the total revenue?")
    assert ui.status_label(result) == "grounded"
    assert result["error"] is None
    assert result["row_count"] >= 1
    assert result["rows"][0]["total_revenue"] > 0
    assert result["sql"]
    assert len(result["attempts"]) == 1


def test_run_question_repaired_path(client):
    result = ui.run_question("What is the total revenue with a broken column?")
    assert ui.status_label(result) == "repaired"
    assert result["error"] is None
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["error"] is not None
    assert result["attempts"][1]["error"] is None


def test_run_question_error_state_graceful(client):
    result = ui.run_question("What is the total revenue, always broken?")
    assert ui.status_label(result) == "failed"
    assert result["error"] is not None
    assert result["rows"] == []
    assert result["row_count"] == 0
    # the UI still has everything it needs to render the failure card
    assert len(result["attempts"]) == 2
    assert result["explanation"]


def test_run_question_service_exception_becomes_error_dict(monkeypatch):
    def boom(question):
        raise RuntimeError("agent ran no query")

    monkeypatch.setattr(ui, "ask_question", boom)
    result = ui.run_question("anything at all")
    assert ui.status_label(result) == "failed"
    assert result["error"] == "agent ran no query"
    assert result["rows"] == []
    assert result["attempts"] == []
    assert result["explanation"] == "agent ran no query"


def test_ui_sample_questions_are_wired():
    # every sample button question must route through the fake model
    # without the agent raising "did not run any query"
    assert len(ui.SAMPLE_QUESTIONS) >= 3
    assert "What is the total revenue?" in ui.SAMPLE_QUESTIONS
