import csv
from unittest.mock import Mock

import pytest

from linkedin_easy_apply.bot import EasyApplyBot
from linkedin_easy_apply.config import AppConfig, normalize_question
from linkedin_easy_apply.models import JobInfo
from linkedin_easy_apply.presentation import (
    friendly_result_reason,
    friendly_run_message,
    load_application_history,
    safe_application_url,
)


FIELDS = ["timestamp", "job_id", "title", "company", "url", "result", "reason"]
SECRET = "private@example.test token=secret123 C:\\Users\\Private\\resume.pdf"


def write_history(path, rows, fields=FIELDS, encoding="utf-8"):
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_missing_empty_and_header_only_history(tmp_path):
    path = tmp_path / "applications.csv"
    assert load_application_history(path) == []
    assert load_application_history("") == []
    path.write_text("", encoding="utf-8")
    assert load_application_history(path) == []
    write_history(path, [])
    assert load_application_history(path) == []


@pytest.mark.parametrize("raw, expected", [
    ("https://www.linkedin.com/jobs/view/123/", "https://www.linkedin.com/jobs/view/123/"),
    ("https://br.linkedin.com/jobs/view/engenheiro-456?trackingId=secret#details", "https://www.linkedin.com/jobs/view/456/"),
    ("https://linkedin.com:443/jobs/view/789", "https://www.linkedin.com/jobs/view/789/"),
    ("HTTPS://WWW.LINKEDIN.COM/jobs/view/123", "https://www.linkedin.com/jobs/view/123/"),
    ("javascript:alert(1)", ""), ("file:///C:/private.txt", ""),
    ("http://www.linkedin.com/jobs/view/123", ""),
    ("https://linkedin.com.evil.test/jobs/view/123/", ""),
    ("https://evil.test/linkedin.com/jobs/view/123", ""),
    ("https://www.linkedin.com@evil.test/jobs/view/123/", ""),
    ("https://private:secret@www.linkedin.com/jobs/view/123/", ""),
    ("https://www.linkedin.com:444/jobs/view/123/", ""),
    ("https://www.linkedin.com:notaport/jobs/view/123/", ""),
    ("https://www.linkedin.com/jobs/view/123/redirect", ""),
    ("https://www.linkedin.com/redir/redirect?url=https://evil.test", ""),
    ("https://www.linkedin.com/jobs/view/%31%32%33/", ""),
    ("https://www.linkedin.com/jobs/view/123\n", "https://www.linkedin.com/jobs/view/123/"),
    ("https://www.linked\nin.com/jobs/view/123", ""),
    ("https://www.linkedin.com\\@evil.test/jobs/view/123", ""),
    ("https://[bad/jobs/view/123", ""), ("", ""), (None, ""),
])
def test_safe_application_urls(raw, expected):
    assert safe_application_url(raw) == expected


@pytest.mark.parametrize("result, reason, expected", [
    ("applied", "submission confirmed", "submitted"),
    ("applied", "submission confirmed structurally", "submitted"),
    ("applied", "submission confirmed by Applied state", "submitted"),
    ("submitted", "", "submitted"),
    ("submitted", "submission confirmed", "submitted"),
    ("applied", "", "unknown"),
    ("applied", "submit clicked", "unknown"),
    ("applied", "submission confirmed but failed", "unknown"),
    ("submitted", "user declined submission", "unknown"),
    ("filtered", "already applied", "skipped"),
    ("filtered", "submission confirmed", "skipped"),
    ("skipped", "submission confirmed", "skipped"),
    ("failed", "submission confirmed", "failed"),
    ("success", "submission confirmed", "unknown"),
    ("pending", "submission confirmed", "unknown"),
    ("failed", "exception: " + SECRET, "failed"),
])
def test_only_confirmed_submissions_are_sent(tmp_path, result, reason, expected):
    path = tmp_path / "applications.csv"
    write_history(path, [{"job_id": "123", "result": result, "reason": reason}])
    row, = load_application_history(path)
    assert row["status"] == expected
    assert (row["result"] == "submitted") == (expected == "submitted")
    assert set(row) == {"timestamp", "job_id", "title", "company", "location", "url", "result", "status"}
    assert all(isinstance(value, str) for value in row.values())
    assert SECRET not in str(row)


def test_conflicting_status_columns_cannot_claim_submission(tmp_path):
    path = tmp_path / "applications.csv"
    write_history(path, [{"job_id": "123", "status": "submitted", "result": "failed", "reason": "submission confirmed"}], [*FIELDS, "status"])
    row, = load_application_history(path)
    assert row["status"] == "unknown"
    assert row["result"] == "unknown"


def test_legacy_bom_history_and_chronological_order(tmp_path):
    path = tmp_path / "applications.csv"
    write_history(path, [
        {"timestamp": "2026-09-10 10:00:00", "job_id": "100", "result": "applied", "reason": "submission confirmed"},
        {"timestamp": "2026-09-10T09:00:00-03:00", "job_id": "200", "result": "failed"},
        {"timestamp": "invalid", "job_id": "300", "result": "skipped"},
        {"timestamp": "2026-09-10T12:00:00Z", "job_id": "400", "result": "skipped"},
    ], encoding="utf-8-sig")
    original = path.read_bytes()
    rows = load_application_history(path)
    assert [row["job_id"] for row in rows] == ["400", "200", "100", "300"]
    assert rows[-1]["timestamp"] == ""
    assert all(row["location"] == "" for row in rows)
    assert rows[2]["url"] == "https://www.linkedin.com/jobs/view/100/"
    assert path.read_bytes() == original


def test_history_aliases_and_display_sanitization(tmp_path):
    path = tmp_path / "applications.csv"
    fields = [" Date ", "job_id", "job_title", "company_name", "job_location", "job_url", "status", "reason"]
    write_history(path, [{
        " Date ": "2026-09-10", "job_id": "123", "job_title": '<b>Engenheiro</b>\r\nPython\x00\u202e',
        "company_name": '=HYPERLINK("https://evil.test")', "job_location": "São Paulo &amp; região",
        "job_url": "javascript:alert(1)", "status": "failed", "reason": "exception: " + SECRET,
    }], fields)
    row, = load_application_history(path)
    assert row["title"] == "Engenheiro Python"
    assert row["company"].startswith("'=HYPERLINK")
    assert row["location"] == "São Paulo & região"
    assert row["url"] == ""
    assert row["result"] == "failed"
    assert SECRET not in str(row)


def test_truncated_and_malformed_csv_rows_are_not_presented_as_sent(tmp_path):
    path = tmp_path / "applications.csv"
    path.write_text(
        "job_id,result,reason\n"
        "1,applied,submission confirmed\n"
        "2,submitted\n"
        "3,applied,submission confirmed,extra\n"
        "4,skipped,user stopped\n"
        '5,applied,"submission confirmed', encoding="utf-8",
    )
    assert {row["job_id"] for row in load_application_history(path)} == {"1", "4"}


@pytest.mark.parametrize("contents", ["title,company\nDeveloper,Company\n", "result,result\nsubmitted,failed\n"])
def test_unrecognized_or_duplicate_columns_are_ignored(tmp_path, contents):
    path = tmp_path / "applications.csv"
    path.write_text(contents, encoding="utf-8")
    assert load_application_history(path) == []


def test_history_read_failure_reaches_ui(tmp_path):
    with pytest.raises(OSError):
        load_application_history(tmp_path)


@pytest.mark.parametrize("message, fragment", [
    ("Opening Chrome in background…", "Opening"),
    ("LinkedIn login required. " + SECRET, "Sign in to LinkedIn"),
    ("LinkedIn session detected.", "connected"),
    ("Headless Chrome is not signed in. " + SECRET, "sign in"),
    ("Searching: " + SECRET, "Looking for jobs"),
    ("Easy Apply: " + SECRET, "Getting your application ready"),
    ("Easy Apply step 2: inspecting the current form…", "questions"),
    ("Submit clicked; waiting for LinkedIn confirmation…", "not confirmed yet"),
    ("submission confirmed structurally", "confirmed that your application was sent"),
    ("Could not resolve required question safely: " + SECRET, "answer needs"),
    ("Could not commit a valid autocomplete option for: " + SECRET, "answer needs"),
    ("Selected autocomplete answer for: " + SECRET, "option"),
    ("Autonomous fallback used for an unmapped choice: " + SECRET, "option"),
    ("Browser recovery was not possible: " + SECRET, "reopen"),
    ("Filtered by blacklist: " + SECRET, "preferences"),
    ("Filtered previously submitted job: " + SECRET, "without sending again"),
    ("Question prompt failed safely: " + SECRET, "question could not open"),
    ("Could not persist learned answer " + SECRET, "saved"),
    ("FAILSAFE: " + SECRET, "longer than expected"),
    ("Run failed " + SECRET, "stopped"),
    ("Run completed", "complete"),
])
def test_run_messages_are_friendly_and_never_echo_details(message, fragment):
    translated = friendly_run_message(message)
    assert fragment in translated
    assert SECRET not in translated
    assert not any(word in translated.lower() for word in ("webdriver", "dom", "fallback", "traceback", "token=", "private@", "c:\\", "blacklist", "autocomplete"))


@pytest.mark.parametrize("prefix", ["", "INFO ", "17:00:00  INFO  ", "2026-09-10 17:00:00  INFO  linkedin_easy_apply.bot  "])
def test_formatted_log_compatibility(prefix):
    assert friendly_run_message(prefix + "Searching: " + SECRET) == "Looking for jobs that match your preferences…"


def test_unknown_logs_are_not_echoed():
    assert friendly_run_message(SECRET) is None
    assert friendly_run_message("Traceback (most recent call last):\n" + SECRET) is None
    assert friendly_run_message("DEBUG Opening Chrome…") is None
    assert friendly_run_message("", "ERROR") is None
    assert "Something did not go" in friendly_run_message(SECRET, level="ERROR")
    assert "attention" in friendly_run_message(SECRET, level="WARNING")
    assert "Something did not go" in friendly_run_message("17:00:00 ERROR " + SECRET)


@pytest.mark.parametrize("reason", [
    "exception: " + SECRET, "skipped: required question was not answered after live-DOM retries: " + SECRET,
    "skipped: unresolved validation error: " + SECRET, "verified location conflict: " + SECRET,
    "unknown private diagnostic " + SECRET,
])
def test_result_explanations_never_echo_diagnostics(reason):
    text = friendly_result_reason(reason)
    assert SECRET not in text
    assert "DOM" not in text and "exception" not in text and "diagnostic" not in text
    assert friendly_result_reason("applied") == "There is no confirmation that this application was sent."


def make_bot(path, **kwargs):
    return EasyApplyBot(AppConfig(output_csv=str(path)), **kwargs)


def test_new_result_files_include_location_without_changing_submission_result(tmp_path):
    path = tmp_path / "results" / "applications.csv"
    bot = make_bot(path, persist_answers=False)
    bot._record(JobInfo("123", "Engenheiro", "Empresa", location="Recife"), "applied", "submission confirmed")
    with path.open(encoding="utf-8", newline="") as handle:
        raw, = csv.DictReader(handle)
    assert raw["result"] == "applied"
    assert raw["reason"] == "submission confirmed"
    assert raw["location"] == "Recife"
    row, = load_application_history(path)
    assert row["location"] == "Recife" and row["status"] == "submitted"
    assert make_bot(path).previously_applied_ids == {"123"}


def test_old_history_is_upgraded_without_losing_rows_or_extra_columns(tmp_path):
    path = tmp_path / "applications.csv"
    write_history(path, [{"job_id": "100", "result": "applied", "reason": "submission confirmed", "note": "preserve"}], [*FIELDS, "note"], encoding="utf-8-sig")
    bot = make_bot(path)
    bot._record(JobInfo("200", location="Curitiba"), "failed", "application stalled on the same step")
    bot._record(JobInfo("300", location="São Paulo"), "skipped", "user stopped")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["job_id"] for row in rows] == ["100", "200", "300"]
    assert [row["location"] for row in rows] == ["", "Curitiba", "São Paulo"]
    assert rows[0]["note"] == "preserve"
    assert all(None not in row for row in rows)
    assert not list(tmp_path.glob("*.writing"))
    assert make_bot(path).previously_applied_ids == {"100"}


def test_failed_migration_preserves_history_and_cleans_staging_file(tmp_path, monkeypatch):
    path = tmp_path / "applications.csv"
    write_history(path, [{"job_id": "100", "result": "applied", "reason": "submission confirmed"}])
    original = path.read_bytes()
    monkeypatch.setattr("linkedin_easy_apply.bot.os.replace", Mock(side_effect=PermissionError("locked")))
    with pytest.raises(PermissionError):
        make_bot(path)._record(JobInfo("200", location="Recife"), "skipped", "user stopped")
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("persist_answers", [True, False])
def test_learned_answers_remain_available_and_persistence_can_be_deferred(tmp_path, monkeypatch, persist_answers):
    bot = make_bot(tmp_path / "applications.csv", persist_answers=persist_answers,
                   ask_question=lambda *_: "  Minha resposta  ")
    save = Mock()
    monkeypatch.setattr(bot.config, "save", save)
    assert bot._ask_and_store("Qual a resposta?", [], "") == "Minha resposta"
    assert bot.config.answers[normalize_question("Qual a resposta?")] == "Minha resposta"
    assert bot._known_answer(normalize_question("Qual a resposta?")) == "Minha resposta"
    assert save.call_count == int(persist_answers)


def test_cli_keeps_immediate_saving_by_default(tmp_path, monkeypatch):
    bot = make_bot(tmp_path / "applications.csv", ask_question=lambda *_: "Sim")
    save = Mock()
    monkeypatch.setattr(bot.config, "save", save)
    bot._ask_and_store("Uma pergunta?", [], "")
    save.assert_called_once_with()


def test_deferred_answers_are_not_saved_on_run_completion(tmp_path, monkeypatch):
    bot = make_bot(tmp_path / "applications.csv", persist_answers=False, ask_question=lambda *_: "Sim")
    save = Mock()
    monkeypatch.setattr(bot.config, "save", save)
    monkeypatch.setattr(bot, "open", lambda: None)
    monkeypatch.setattr(bot, "close", lambda: None)
    monkeypatch.setattr(bot, "ensure_logged_in", lambda **_: True)
    monkeypatch.setattr(bot, "_run_search", lambda *_: bot._ask_and_store("Pergunta?", [], ""))
    bot.config.positions = ["Engenheiro"]
    bot.config.locations = ["Recife"]
    bot.run()
    assert bot.config.answers[normalize_question("Pergunta?")] == "Sim"
    save.assert_not_called()
