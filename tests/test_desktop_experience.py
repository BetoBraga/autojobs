from __future__ import annotations

import gc
import time
import tkinter as tk
from pathlib import Path

import pytest

import app as desktop
from linkedin_easy_apply.config import AppConfig, app_data_dir
from linkedin_easy_apply.models import RunStats


def pump(window, seconds=0.15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        window.update()
        time.sleep(0.01)


@pytest.fixture(scope="module")
def desktop_window(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("desktop")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(desktop.EasyApplyApp, "_configure_logging", lambda self: None)
    config = AppConfig(onboarding_completed=True).normalized()
    config.save()
    gc.collect()
    app = desktop.EasyApplyApp()
    failures = []
    app.report_callback_exception = lambda *args: failures.append(args)
    pump(app)
    yield app
    app.stop_event.set()
    if app.worker:
        app.worker.join(timeout=2)
    if app.winfo_exists():
        for callback in app.tk.call("after", "info"):
            app.after_cancel(callback)
        app.destroy()
    gc.collect()
    monkeypatch.undo()
    assert not failures, failures


@pytest.fixture
def window(desktop_window):
    app = desktop_window
    app._autosave_loading = True
    app.config_data = AppConfig(onboarding_completed=True).normalized()
    app.config_data.save()
    app._question_drafts.clear()
    app._editing_question_key = None
    app.question_search_var.set("")
    app.question_scope_var.set("All questions")
    app.question_category_var.set("All categories")
    app._load_config_into_ui()
    app._settings_dirty = False
    app._autosave_loading = False
    pump(app)
    return app


def settings_path():
    return app_data_dir() / "config.json"


def test_autosave_persists_without_clicking_save(window):
    window.phone_var.set("+55 11 99999-0000")
    pump(window, 0.85)
    assert AppConfig.load().phone_number == "+55 11 99999-0000"
    assert not window._settings_dirty
    assert "All changes saved" in window.save_status_var.get()


def test_invalid_edit_does_not_overwrite_saved_settings(window):
    before = settings_path().read_bytes()
    window.max_apps_var.set("incompleto")
    pump(window, 0.85)
    assert window._settings_dirty
    assert settings_path().read_bytes() == before
    assert "Not saved yet" in window.save_status_var.get()
    window.max_apps_var.set(5)
    pump(window, 0.85)
    assert AppConfig.load().max_applications == 5


def select_question(window, key):
    window.notebook.select(window.questions_tab)
    window.question_tree.selection_set(key)
    window._load_question_editor()


def test_answer_drafts_survive_switch_and_save_automatically(window):
    select_question(window, "current_location")
    window.question_editor_value_var.set("São Paulo")
    select_question(window, "notice_period")
    window.question_editor_value_var.set("30 days")
    pump(window, 0.85)
    saved = AppConfig.load().profile_answers
    assert saved["current_location"] == "São Paulo"
    assert saved["notice_period"] == "30 days"
    editor = window.question_editor_widget
    window._load_question_editor()
    assert window.question_editor_widget is editor
    window._clear_catalog_answer()
    pump(window, 0.85)
    assert "notice_period" not in AppConfig.load().profile_answers


def test_numeric_catalog_answer_is_validated_before_save(window):
    select_question(window, "hybrid_days")
    window.question_editor_value_var.set("muitos")
    pump(window, 0.85)
    assert "hybrid_days" not in AppConfig.load().profile_answers
    assert window._settings_dirty
    window.question_editor_value_var.set("3,5")
    pump(window, 0.85)
    assert AppConfig.load().profile_answers["hybrid_days"] == "3.5"


def test_filter_preserves_unsaved_answer_and_shows_empty_state(window):
    select_question(window, "current_location")
    window.question_editor_value_var.set("Curitiba")
    window.question_search_var.set("nothing-will-match-this-question")
    pump(window, 0.85)
    assert not window.question_tree.get_children()
    assert "No " in window.question_results_var.get()
    assert AppConfig.load().profile_answers["current_location"] == "Curitiba"


@pytest.mark.parametrize("size", ["640x480", "900x640", "1240x830"])
def test_every_main_page_can_scroll_at_supported_sizes(window, size):
    window.geometry(size)
    for tab in (window.setup_tab, window.questions_tab, window.run_tab, window.applied_tab, window.answers_tab):
        window.notebook.select(tab)
        pump(window)
        window._apply_responsive_layout()
        pump(window)
        page = next(page for page in window._pages if page.canvas.master is tab)
        assert page.canvas.winfo_width() <= window.winfo_width()
        assert page.content.winfo_width() == page.canvas.winfo_width()
        assert page.canvas.winfo_height() > 50
        if page.content.winfo_height() > page.canvas.winfo_height():
            page.canvas.yview_moveto(0)
            page.content.event_generate("<MouseWheel>", delta=-120)
            pump(window, 0.03)
            assert page.canvas.yview()[0] > 0


def test_settings_locked_until_worker_exits_then_learned_answers_saved(window, monkeypatch):
    class FakeBot:
        def __init__(self, config, **options):
            assert options["persist_answers"] is False
            self.config = config
            self.options = options

        def run(self):
            self.config.remember_answer("Can you start next week?", "Yes")
            self.options["on_status"]("Scanning form controls: selector=private")
            while not self.options["should_stop"]():
                time.sleep(0.01)
            return RunStats()

    monkeypatch.setattr(desktop, "EasyApplyBot", FakeBot)
    window._start_run()
    before = settings_path().read_bytes()
    assert window._run_active
    assert str(window.resume_entry.cget("state")) == "disabled"
    assert str(window.theme_combo.cget("state")) == "disabled"
    window.phone_var.set("pending-programmatic-edit")
    pump(window, 0.85)
    assert settings_path().read_bytes() == before
    assert "selector" not in window.status_var.get()
    assert "can you start next week" not in AppConfig.load().answers
    window._stop_run()
    pump(window, 0.45)
    assert not window._settings_locked()
    assert str(window.theme_combo.cget("state")) == "readonly"
    assert AppConfig.load().answers["can you start next week"] == "Yes"
    assert AppConfig.load().phone_number == "pending-programmatic-edit"


def test_run_log_hides_technical_details_and_repetition(window):
    line = "12:15:00 INFO Opening LinkedIn jobs search"
    window._append_log(line)
    first = window.log_text.get("1.0", "end")
    window._append_log(line)
    assert window.log_text.get("1.0", "end") == first
    window._append_log("DEBUG selector=#secret token=123 stacktrace WebDriverException")
    text = window.log_text.get("1.0", "end")
    assert "selector" not in text
    assert "token" not in text
    assert "WebDriverException" not in text


def test_history_filter_pagination_and_details(window):
    window._history_rows = [dict(timestamp="2026-09-10", title=f"Cargo {i}", company="Company", location="Remote", url="https://www.linkedin.com/jobs/view/123/", result="submitted", status="submitted") for i in range(55)]
    window._render_history()
    assert len(window.applied_tree.get_children()) == 50
    window._change_history_page(1)
    assert len(window.applied_tree.get_children()) == 5
    window.applied_tree.selection_set("0")
    window._show_application_details()
    assert "Cargo 50" in window.history_detail_var.get()
    assert str(window.history_open_button.cget("state")) == "normal"
    window.history_search_var.set("não existe")
    pump(window, 0.25)
    assert not window.applied_tree.get_children()
    assert "No " in window.history_status_var.get()
