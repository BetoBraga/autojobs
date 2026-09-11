"""Safe, plain-English presentation of run events and application history."""
from __future__ import annotations

import csv
import html
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


_CONFIRMED_REASONS = frozenset({
    "submission confirmed", "submission confirmed structurally",
    "submission confirmed by applied state",
})
_REASON_MESSAGES = {
    "submitted": "LinkedIn confirmed that your application was sent.",
    "already_applied": "LinkedIn shows an earlier application. Nothing was sent again.",
    "excluded": "This job was skipped based on your preferences.",
    "location": "This job is outside the location you chose.",
    "external": "This job does not offer LinkedIn Easy Apply.",
    "required_answer": "A required answer was missing. Review your answers before trying again.",
    "validation": "LinkedIn asked for a correction. Review your answers before trying again.",
    "declined": "You chose not to send this application.",
    "stopped": "The search stopped before the application was confirmed as sent.",
    "browser": "The browser could not continue. Check your connection and try again.",
    "open_failed": "This application form could not open. You can try again later.",
    "stalled": "The form did not move forward. Sending was not confirmed.",
    "unsupported": "This form could not be completed. Sending was not confirmed.",
    "skipped": "This application was not sent during this search.",
    "failed": "This application could not be completed. Sending was not confirmed.",
    "unknown": "There is no confirmation that this application was sent.",
}


def _reason_code(reason: str) -> str:
    value = str(reason or "").strip().casefold()
    if value in _REASON_MESSAGES:
        return value
    if value in _CONFIRMED_REASONS:
        return "submitted"
    if value == "already applied":
        return "already_applied"
    if value == "blacklisted":
        return "excluded"
    if value.startswith("verified location conflict:"):
        return "location"
    if value == "no easy apply control":
        return "external"
    if value.startswith("skipped: required question"):
        return "required_answer"
    if value.startswith("skipped: unresolved validation error"):
        return "validation"
    if value == "user declined submission":
        return "declined"
    if value == "user stopped":
        return "stopped"
    if value == "browser recovery failed":
        return "browser"
    if value == "could not open easy apply":
        return "open_failed"
    if value == "application stalled on the same step":
        return "stalled"
    if value in {"no supported next/review/submit action found", "application exceeded safe step limit"}:
        return "unsupported"
    if value.startswith(("exception:", "job exception:")):
        return "failed"
    return "unknown"


def friendly_result_reason(result: str) -> str:
    """Explain a known reason/code without ever displaying its diagnostic details."""
    return _REASON_MESSAGES[_reason_code(result)]


# Only fixed text is emitted: questions, answers, paths and exception details stay private.
_RUN_MESSAGES = (
    (("opening chrome",), "Opening your browser to start the search…"),
    (("linkedin login required", "linkedin login is required", "linkedin session not available"),
     "Sign in to LinkedIn in your browser and complete any sign-in checks."),
    (("headless chrome is not signed in",), "Open LinkedIn and sign in before starting a search without a browser window."),
    (("linkedin session detected",), "All set! Your LinkedIn account is connected."),
    (("run stopped before login completed",), "The search ended before connecting to LinkedIn. Sign in and try again."),
    (("searching:",), "Looking for jobs that match your preferences…"),
    (("no additional jobs found",), "No new jobs on this page. We will check the next one."),
    (("search exhausted",), "This search is complete. There are no more new jobs here."),
    (("filtered previously submitted job:", "filtered because linkedin reports it was already applied:"),
     "You have already applied to this job. Moving on without sending again."),
    (("filtered by blacklist:",), "This job was skipped based on your preferences."),
    (("filtering verified location conflict:",), "This job is in a different location. Moving to the next one."),
    (("filtered because no easy apply control",), "This job does not offer Easy Apply. Moving to the next one."),
    (("easy apply:", "resumed a saved easy apply draft"), "Getting your application ready…"),
    (("easy apply step ",), "Checking the questions and filling in your answers…"),
    (("the application stayed on the same step", "linkedin reports validation errors"),
     "LinkedIn asked for a correction. Checking your answers before continuing."),
    (("submit clicked; waiting for linkedin confirmation",), "Waiting for LinkedIn to confirm your application. It is not confirmed yet."),
    (("review/forward action clicked", "advanced using the easy apply primary action"), "Moving to the next step of your application…"),
    (("could not resolve required question safely:", "could not resolve required choice safely:",
      "could not select a valid option for:", "could not select a valid choice for:",
      "could not commit a valid autocomplete option for:"),
     "An answer needs attention. Review your answers before trying again."),
    (("autonomous fallback used for an unmapped choice:", "autonomous fallback selected a valid option for:",
      "selected autocomplete answer for:"), "An option was chosen using your preferences. Continuing to check the questions."),
    (("browser session became unavailable",), "The browser stopped responding. Reopening it carefully."),
    (("browser recovery was not possible:", "browser recovery failed"), "The browser could not reopen. Check your connection and try again."),
    (("skipping this search page", "skipping one result page"), "This page could not load. Continuing with the next jobs."),
    (("warning: configured action delay", "aggressive action delay configured:"),
     "The pause between actions is very short. A longer pause may help avoid interruptions."),
    (("question prompt failed safely:", "question dialog failed"), "The question could not open. This application needs attention."),
    (("could not persist learned answer", "could not save settings"), "Your answers could not be saved. Check your preferences before closing the app."),
    (("could not read application history",), "Your history could not open. Try refreshing the list."),
    (("failsafe:",), "The search is taking longer than expected. Check your browser before continuing."),
    (("run failed", "could not start run worker"), "The search stopped because something went wrong. Check your connection and try again."),
    (("application failed",), "This application could not be completed. Sending was not confirmed."),
    (("run completed", "run finished"), "Search complete. See your applications in Applied."),
    (("run stopped", "user stopped"), "Search stopped. Your confirmed applications are still in your history."),
    (("autojobs desktop started;",), "Ready to help you set up your search."),
)
_LOG_PREFIX = re.compile(
    r"^(?:(?:\d{4}-\d{2}-\d{2}[ T])?\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+)?"
    r"\[?(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\]?\s*[:\-]?\s+", re.I,
)


def friendly_run_message(message: str, level: str = "INFO") -> str | None:
    """Translate recognized events; hide unknown informational/technical output."""
    text = str(message or "").strip().splitlines()
    if not text:
        return None
    text = text[0]
    match = _LOG_PREFIX.match(text)
    if match:
        level = match.group(1)
        text = text[match.end():]
    text = re.sub(r"^(?:linkedin_easy_apply(?:\.[\w]+)*|__main__|app)\s+", "", text)
    normalized = text.strip().casefold()
    if str(level).upper() == "DEBUG":
        return None
    if normalized in _CONFIRMED_REASONS:
        return _REASON_MESSAGES["submitted"]
    for prefixes, translated in _RUN_MESSAGES:
        if normalized.startswith(prefixes):
            return translated
    if str(level).upper() in {"ERROR", "CRITICAL"}:
        return "Something did not go as expected. Check the search progress before trying again."
    if str(level).upper() in {"WARNING", "WARN"}:
        return "One step needs attention. Checking whether the search can continue."
    return None


def safe_application_url(url: str) -> str:
    """Return a canonical HTTPS LinkedIn job URL, dropping all tracking data."""
    value = str(url or "").strip()
    if not value or any(unicodedata.category(char).startswith("C") for char in value):
        return ""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443)
                or not re.fullmatch(r"(?:www\.|[a-z]{2}\.)?linkedin\.com", host)):
            return ""
        match = re.fullmatch(r"/jobs/view/(?:[\w-]+-)?([0-9]+)/?", parsed.path, flags=re.ASCII)
        if not match:
            return ""
        return f"https://www.linkedin.com/jobs/view/{match.group(1)}/"
    except ValueError:
        return ""


def _display_text(value: str, limit: int = 400) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"<[^>]*>", "", text)
    text = " ".join(text.split())
    text = "".join(char for char in text if not unicodedata.category(char).startswith("C"))
    if text.startswith(("=", "+", "-", "@")):
        text = "'" + text
    return text[:limit]


def _history_status(result: str, reason: str) -> tuple[str, str]:
    result = result.strip().casefold()
    code = _reason_code(reason)
    if result in {"applied", "submitted"}:
        if reason.strip().casefold() in _CONFIRMED_REASONS or (result == "submitted" and not reason.strip()):
            return "submitted", "submitted"
        return "unknown", "unknown"
    if result in {"skipped", "filtered"}:
        return "skipped", code if code not in {"submitted", "unknown"} else "skipped"
    if result in {"failed", "error"}:
        return "failed", code if code not in {"submitted", "unknown"} else "failed"
    return "unknown", "unknown"


def load_application_history(path: str | Path) -> list[dict[str, str]]:
    """Read current/legacy CSVs newest first, without modifying files.

    Every row has timestamp, job_id, title, company, location, url, result and
    status. ``result`` is a safe reason code for ``friendly_result_reason``;
    ``status`` is submitted/skipped/failed/unknown. Old applied rows require an
    explicit confirmation reason. A canonical submitted status is affirmative
    unless contradicted by its reason. Malformed/truncated rows are ignored.
    Missing files return an empty list; other I/O errors reach the caller.
    """
    if not path:
        return []
    file_path = Path(path).expanduser()
    try:
        handle = file_path.open("r", encoding="utf-8-sig", errors="replace", newline="")
    except FileNotFoundError:
        return []
    rows: list[tuple[float, int, dict[str, str]]] = []
    with handle:
        reader = csv.DictReader(handle, strict=True)
        if not reader.fieldnames:
            return []
        reader.fieldnames = [name.strip().casefold() for name in reader.fieldnames]
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            return []
        if not {"result", "status"}.intersection(reader.fieldnames):
            return []
        while True:
            try:
                raw = next(reader)
            except StopIteration:
                break
            except csv.Error:
                continue
            if None in raw or any(value is None for value in raw.values()):
                continue
            if not any(value.strip() for value in raw.values()):
                continue
            declared_status = raw.get("status", "").strip().casefold()
            stored_result = raw.get("result", "").strip().casefold()
            status, reason = _history_status(declared_status or stored_result, raw.get("reason", ""))
            if (status == "submitted" and declared_status and stored_result
                    and stored_result not in {"applied", "submitted", *_CONFIRMED_REASONS}):
                status, reason = "unknown", "unknown"
            timestamp = _display_text(raw.get("timestamp") or raw.get("date") or raw.get("applied_at", ""), 40)
            try:
                date = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                order = date.replace(tzinfo=date.tzinfo or timezone.utc).timestamp()
            except (ValueError, OverflowError, OSError):
                timestamp, order = "", float("-inf")
            job_id = _display_text(raw.get("job_id", ""), 40)
            url = raw.get("url") or raw.get("job_url") or raw.get("link", "")
            if not url and re.fullmatch(r"[0-9]+", job_id):
                url = f"https://www.linkedin.com/jobs/view/{job_id}/"
            row = {
                "timestamp": timestamp, "job_id": job_id,
                "title": _display_text(raw.get("title") or raw.get("job_title", "")),
                "company": _display_text(raw.get("company") or raw.get("company_name", "")),
                "location": _display_text(raw.get("location") or raw.get("job_location", "")),
                "url": safe_application_url(url), "result": reason, "status": status,
            }
            rows.append((order, len(rows), row))
    return [row for _, _, row in sorted(rows, key=lambda item: (item[0], item[1]), reverse=True)]
