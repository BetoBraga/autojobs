from __future__ import annotations

import csv
import logging
import os
import random
import re
import time
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlencode
from uuid import uuid4

from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select

from .browser import (
    build_chrome_driver,
    collect_job_ids,
    deep_query_all,
    deep_text,
    inspect_form_controls,
    safe_click,
    fill_autocomplete,
    visible_autocomplete_options,
    extract_job_location,
    extract_job_location_info,
    extract_job_metadata,
)
from .answer_engine import adapt_answer_to_choices, resolve_answer
from .autocomplete import classify_location_match, looks_like_autocomplete, location_matches_requested, sanitize_location_evidence, should_block_location
from .config import AppConfig, normalize_question, delay_is_aggressive, delay_warning_text, resolve_search_location
from .models import JobInfo, RunStats
from .question_catalog import match_question

log = logging.getLogger(__name__)

StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[RunStats, JobInfo | None], None]
QuestionCallback = Callable[[str, list[str], str], str | None]
ConfirmCallback = Callable[[JobInfo], bool]
StopCallback = Callable[[], bool]

SUCCESS_PHRASES = (
    "application was sent",
    "application submitted",
    "your application was sent",
    "application sent",
    "candidatura enviada",
    "candidatura submetida",
    "sua candidatura foi enviada",
    "solicitud enviada",
    "candidature envoyée",
)


def build_search_url(config: AppConfig, position: str, location: str, start: int = 0) -> str:
    search_location = resolve_search_location(location)
    params: dict[str, str] = {
        "f_AL": "true",
        "keywords": position,
        "location": search_location,
        "start": str(start),
        "sortBy": "DD",
    }
    if config.experience_levels:
        params["f_E"] = ",".join(str(x) for x in config.experience_levels)
    if config.work_types:
        params["f_WT"] = ",".join(str(x) for x in config.work_types)
    if config.date_posted:
        params["f_TPR"] = config.date_posted
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


class EasyApplyBot:
    def __init__(
        self,
        config: AppConfig,
        *,
        on_status: StatusCallback | None = None,
        on_progress: ProgressCallback | None = None,
        ask_question: QuestionCallback | None = None,
        confirm_submit: ConfirmCallback | None = None,
        should_stop: StopCallback | None = None,
        persist_answers: bool = True,
    ) -> None:
        self.config = config.normalized()
        # The desktop owns deferred saving; CLI callers retain immediate saving.
        self.persist_answers = persist_answers
        self.on_status = on_status or (lambda message: None)
        self.on_progress = on_progress or (lambda stats, job: None)
        self.ask_question = ask_question or (lambda question, choices, default: default or None)
        self.confirm_submit = confirm_submit or (lambda job: True)
        self.should_stop = should_stop or (lambda: False)
        self.driver = None
        self.stats = RunStats()
        self.seen_job_ids: set[str] = set()
        self.previously_applied_ids = self._load_recent_job_ids()
        self._external_recovery_requested = threading.Event()
        self._last_form_issue = ""

    def _status(self, message: str) -> None:
        log.info(message)
        self.on_status(message)

    def _progress(self, job: JobInfo | None = None) -> None:
        self.on_progress(self.stats, job)

    def open(self) -> None:
        self._status("Opening Chrome in background…" if self.config.headless_browser else "Opening Chrome…")
        self.driver = build_chrome_driver(
            self.config.chrome_profile_dir,
            headless=self.config.headless_browser,
        )

    def close(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def interrupt_browser(self) -> None:
        """Break a potentially stuck WebDriver call without erasing the handle.

        The run loop can then observe a WebDriverException and use its normal
        recovery path. This is used by the desktop failsafe watchdog.
        """
        driver = self.driver
        if driver is None:
            return
        try:
            driver.quit()
        except Exception:
            pass

    def request_browser_recovery(self) -> None:
        """Ask the run thread to recover Chrome at its next safe checkpoint."""
        self._external_recovery_requested.set()
        self.interrupt_browser()

    def _consume_external_recovery(self) -> bool:
        if not self._external_recovery_requested.is_set():
            return True
        self._external_recovery_requested.clear()
        return self._recover_browser()

    def _recover_browser(self) -> bool:
        """Best-effort recovery from a crashed/invalid WebDriver session."""
        if self.should_stop():
            return False
        self._status("Browser session became unavailable; reopening Chrome safely…")
        try:
            self.close()
        except Exception:
            pass
        try:
            self.open()
            return self.ensure_logged_in(wait_for_manual_login=not self.config.headless_browser)
        except Exception as exc:
            log.exception("Browser recovery failed")
            self._status(f"Browser recovery was not possible: {exc}")
            return False

    def ensure_logged_in(self, wait_for_manual_login: bool = True) -> bool:
        assert self.driver is not None
        self.driver.get("https://www.linkedin.com/feed/")
        time.sleep(2)
        if self._looks_logged_in():
            return True
        if not wait_for_manual_login:
            self._status(
                "Headless Chrome is not signed in. Use 'Open LinkedIn login' once with a visible browser, "
                "complete any 2FA/challenge, close it, then start the headless run again."
            )
            return False
        self._status("LinkedIn login required. Complete sign-in in the Chrome window; 2FA/challenges must be completed manually.")
        while not self.should_stop():
            if self._looks_logged_in():
                self._status("LinkedIn session detected.")
                return True
            time.sleep(1)
        return False

    def _looks_logged_in(self) -> bool:
        assert self.driver is not None
        try:
            url = (self.driver.current_url or "").lower()
            if "/login" in url or "/checkpoint/" in url:
                return False
            login_fields = deep_query_all(self.driver, "input#username, input#password")
            if login_fields:
                return False
            return "linkedin.com" in url and any(path in url for path in ("/feed", "/jobs", "/mynetwork", "/in/"))
        except WebDriverException:
            return False

    def run(self) -> RunStats:
        if delay_is_aggressive(self.config.min_delay_seconds, self.config.max_delay_seconds):
            log.warning(delay_warning_text(self.config.min_delay_seconds, self.config.max_delay_seconds))
            self._status(
                "Warning: configured action delay is very low; LinkedIn may throttle or challenge long unattended runs."
            )
        self.open()
        try:
            if not self.ensure_logged_in(wait_for_manual_login=not self.config.headless_browser):
                self._status("Run stopped before login completed.")
                return self.stats
            for position in self.config.positions:
                for location in self.config.locations:
                    if self._limit_reached() or self.should_stop():
                        return self.stats
                    self._run_search(position, location)
            return self.stats
        finally:
            self.close()

    def _run_search(self, position: str, location: str) -> None:
        assert self.driver is not None
        self._status(f"Searching: {position} — {location}")
        max_pages = int(self.config.max_pages_per_search)
        page_limit = max_pages if max_pages > 0 else 100
        consecutive_empty_pages = 0
        for page in range(page_limit):
            if self._limit_reached() or self.should_stop():
                return
            if not self._consume_external_recovery():
                return
            start = page * 25
            search_url = build_search_url(self.config, position, location, start)
            try:
                self.driver.get(search_url)
                time.sleep(self._delay())
                self._load_search_results()
                job_ids = collect_job_ids(self.driver)
            except WebDriverException as exc:
                log.warning("Search page browser error: %s", exc)
                if not self._recover_browser():
                    self._status("Skipping this search page because Chrome could not be recovered.")
                    continue
                assert self.driver is not None
                try:
                    self.driver.get(search_url)
                    time.sleep(self._delay())
                    self._load_search_results()
                    job_ids = collect_job_ids(self.driver)
                except Exception as retry_exc:
                    log.warning("Search page retry failed: %s", retry_exc)
                    self._status("Skipping one result page after a safe retry failure.")
                    continue
            new_ids = [jid for jid in job_ids if jid not in self.seen_job_ids]
            self.stats.discovered += len(new_ids)
            self._progress()
            if not new_ids:
                consecutive_empty_pages += 1
                self._status("No additional jobs found on this result page.")
                if max_pages == 0 and consecutive_empty_pages >= 3:
                    self._status("Search exhausted after three pages with no new jobs.")
                    return
                continue
            consecutive_empty_pages = 0
            for job_id in new_ids:
                self.seen_job_ids.add(job_id)
                if self._limit_reached() or self.should_stop():
                    return
                if not self._consume_external_recovery():
                    return
                try:
                    self._process_job(job_id, location)
                except Exception as exc:
                    # A single malformed job/application must never terminate the run. Browser
                    # disconnects are infrastructure events, not application failures. Recover
                    # first and record a neutral skip so the results CSV does not double-count a
                    # closed Chrome window as a failed job application.
                    log.exception("Job %s failed outside the application flow", job_id)
                    job = JobInfo(job_id=job_id, url=f"https://www.linkedin.com/jobs/view/{job_id}/")
                    if isinstance(exc, WebDriverException):
                        recovered = self._recover_browser()
                        self.stats.skipped += 1
                        self.stats.processed += 1
                        reason = "browser session interrupted; recovered safely" if recovered else "browser session interrupted; recovery failed"
                        try:
                            self._record(job, "skipped", reason)
                        except Exception:
                            pass
                        self._progress(job)
                        if not recovered:
                            return
                        continue
                    self.stats.failed += 1
                    self.stats.processed += 1
                    try:
                        self._record(job, "failed", f"job exception: {type(exc).__name__}: {exc}")
                    except Exception:
                        pass
                    try:
                        self._dismiss_modal()
                    except Exception:
                        pass
                    self._progress(job)

    def _load_search_results(self) -> None:
        assert self.driver is not None
        # Scroll both legacy result panes and the document so virtualized cards load.
        for selector in (
            "[data-component-type='LazyColumn']",
            ".jobs-search-results-list",
            ".scaffold-layout__list",
            "main",
        ):
            for el in deep_query_all(self.driver, selector)[:2]:
                try:
                    for fraction in (0.3, 0.6, 1.0):
                        self.driver.execute_script(
                            "arguments[0].scrollTop = arguments[0].scrollHeight * arguments[1];",
                            el,
                            fraction,
                        )
                        time.sleep(0.35)
                except Exception:
                    pass
        try:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
        except Exception:
            pass

    def _post_open_location_blocks(self, requested_location: str, job: JobInfo) -> bool:
        """Optional secondary location gate. Off by default for maximum coverage.

        The configured location always scopes the LinkedIn search. This method only
        adds a second rejection layer when the user explicitly enables it. The
        deprecated strict_location_filter field is intentionally ignored so an old
        config cannot silently re-enable location-based skipping after an upgrade.
        """
        return bool(
            self.config.post_open_location_filter
            and requested_location
            and should_block_location(
                requested_location,
                job.location,
                job.location_confidence,
            )
        )

    def _process_job(self, job_id: str, requested_location: str = "") -> None:
        assert self.driver is not None
        if job_id in self.previously_applied_ids:
            self._status(f"Filtered previously submitted job: {job_id}.")
            self.stats.filtered += 1
            self.stats.processed += 1
            self._progress(JobInfo(job_id=job_id))
            return

        self.driver.get(f"https://www.linkedin.com/jobs/view/{job_id}/")
        time.sleep(self._delay())
        job = self._read_job_info(job_id)
        self._progress(job)

        if requested_location and not self.config.post_open_location_filter:
            log.info(
                "Post-open location filtering is disabled; location only scopes the LinkedIn search. "
                "Continuing job=%s returned for %r even if page metadata is broader, remote, missing, or conflicting.",
                job.job_id,
                requested_location,
            )

        if self.config.post_open_location_filter and requested_location:
            location_state = classify_location_match(requested_location, job.location)
            if self._post_open_location_blocks(requested_location, job):
                self._status(
                    f"Filtering verified location conflict: {job.location} "
                    f"(configured search: {requested_location})."
                )
                self._record(
                    job,
                    "filtered",
                    f"verified location conflict: {job.location}; configured search {requested_location}; source={job.location_source}",
                )
                self.stats.filtered += 1
                self.stats.processed += 1
                self._progress(job)
                return
            if location_state == "conflict" and job.location:
                log.info(
                    "Potential location conflict %r came from %s-confidence source %r; continuing because only high-confidence dedicated/structured location metadata may filter a job.",
                    job.location, job.location_confidence or "unknown", job.location_source or "unknown",
                )
            elif location_state == "unknown":
                log.info(
                    "Job location could not be verified from the current LinkedIn UI; "
                    "continuing because the search itself is scoped to %r. job=%s",
                    requested_location,
                    job.job_id,
                )
            elif location_state == "compatible" and job.location:
                log.info(
                    "Job location %r is broader/compatible with configured search %r; continuing.",
                    job.location, requested_location,
                )

        if self._is_blacklisted(job):
            self._status(f"Filtered by blacklist: {job.title or job.job_id} — {job.company}.")
            self._record(job, "filtered", "blacklisted")
            self.stats.filtered += 1
            self.stats.processed += 1
            self._progress(job)
            return

        if self._already_applied():
            self._status(f"Filtered because LinkedIn reports it was already applied: {job.title or job.job_id}.")
            self._record(job, "filtered", "already applied")
            self.stats.filtered += 1
            self.stats.processed += 1
            self._progress(job)
            return

        button = self._find_easy_apply_control()
        if not button:
            self._status(f"Filtered because no Easy Apply control is available: {job.title or job.job_id}.")
            self._record(job, "filtered", "no Easy Apply control")
            self.stats.filtered += 1
            self.stats.processed += 1
            self._progress(job)
            return

        self._status(f"Easy Apply: {job.title or job.job_id} — {job.company}")
        if not safe_click(self.driver, button):
            self._record(job, "failed", "could not open Easy Apply")
            self.stats.failed += 1
            self.stats.processed += 1
            self._progress(job)
            return
        time.sleep(1.0)
        self._handle_transient_apply_dialogs()
        self.stats.attempted += 1
        self._progress(job)

        try:
            result, reason = self._complete_application(job)
        except Exception as exc:
            log.exception("Application failed")
            result, reason = False, f"exception: {type(exc).__name__}: {exc}"

        self.stats.processed += 1
        if result:
            self.stats.applied += 1
            self.previously_applied_ids.add(job_id)
            self._record(job, "applied", reason)
        else:
            if reason.startswith("skipped") or reason.startswith("user"):
                self.stats.skipped += 1
                self._record(job, "skipped", reason)
            else:
                self.stats.failed += 1
                self._record(job, "failed", reason)
            self._dismiss_modal()
        self._progress(job)

    def _find_easy_apply_control(self):
        assert self.driver is not None
        selectors = (
            "button.jobs-apply-button",
            "button[aria-label^='Easy Apply']",
            "button[aria-label^='LinkedIn Apply to']",
            "a[href*='openSDUIApplyFlow=true']",
        )
        for selector in selectors:
            for element in deep_query_all(self.driver, selector):
                try:
                    label = (element.get_attribute("aria-label") or "") + " " + (element.text or "")
                    href = element.get_attribute("href") or ""
                    normalized = label.lower()
                    if (
                        "easy apply" in normalized
                        or "linkedin apply to" in normalized
                        or "opensdiuapplyflow=true" in href.lower()
                        or "opensduiapplyflow=true" in href.lower()
                    ):
                        return element
                except StaleElementReferenceException:
                    continue
        # Text fallback for legacy/localised variants.
        for element in deep_query_all(self.driver, "button, a"):
            try:
                label = normalize_question((element.text or "").strip())
                if any(token in label for token in (
                    "easy apply", "candidatura simplificada", "candidatura facil",
                    "solicitud sencilla", "candidature simplifiee"
                )):
                    return element
            except Exception:
                pass
        return None

    def _already_applied(self) -> bool:
        assert self.driver is not None
        text = deep_text(self.driver).lower()
        phrases = (
            "you applied on",
            "you've applied",
            "you have applied",
            "application submitted",
            "candidatura enviada",
            "candidatura submetida",
            "já se candidatou",
            "ja se candidatou",
            "solicitud enviada",
        )
        if any(phrase in text for phrase in phrases):
            return True
        for selector in (
            "button[aria-label='Applied']",
            "button[aria-label^='Applied']",
            "span[aria-label='Applied']",
        ):
            if deep_query_all(self.driver, selector):
                return True
        return False

    def _handle_transient_apply_dialogs(self) -> bool:
        """Handle LinkedIn safety/remume-draft interstitials without treating them as form steps."""
        assert self.driver is not None
        changed = False
        for element in deep_query_all(self.driver, "button, [role='button']"):
            try:
                if not element.is_displayed() or not element.is_enabled():
                    continue
                label = normalize_question((element.get_attribute("aria-label") or "") + " " + (element.text or ""))
                if any(token in label for token in (
                    "continue applying", "continuar candidatura", "continuar a candidatura",
                    "continuar aplicacao", "continuar aplicação"
                )):
                    if safe_click(self.driver, element):
                        self._status("Resumed a saved Easy Apply draft.")
                        changed = True
                        break
            except Exception:
                continue
        # LinkedIn may show a job-search safety reminder over the application.
        try:
            page_text = normalize_question(deep_text(self.driver))
            if "job search safety reminder" in page_text:
                for selector in ("button[aria-label='Dismiss']", "button[aria-label='Close']", "button.artdeco-modal__dismiss"):
                    for button in deep_query_all(self.driver, selector):
                        try:
                            if button.is_displayed() and safe_click(self.driver, button):
                                self._status("Dismissed LinkedIn's job-search safety reminder.")
                                return True
                        except Exception:
                            pass
        except Exception:
            pass
        return changed

    def _complete_application(self, job: JobInfo) -> tuple[bool, str]:
        assert self.driver is not None
        last_state = ""
        stagnant_steps = 0
        for step in range(24):
            if self.should_stop():
                return False, "user stopped"
            if not self._consume_external_recovery():
                return False, "browser recovery failed"
            self._status(f"Easy Apply step {step + 1}: inspecting the current form…")
            time.sleep(0.45)
            if self._handle_transient_apply_dialogs():
                time.sleep(0.35)
            text = deep_text(self.driver).lower()
            if any(phrase in text for phrase in SUCCESS_PHRASES):
                return True, "submission confirmed"

            state_before = self._application_state_fingerprint()
            if state_before and state_before == last_state:
                stagnant_steps += 1
            else:
                stagnant_steps = 0
                last_state = state_before
            if stagnant_steps >= 3:
                errors = self._validation_errors()
                if errors:
                    self._status("The application stayed on the same step and LinkedIn reports validation errors; retrying fields once.")
                    if not self._fill_visible_controls_with_retries(2):
                        detail = f": {self._last_form_issue}" if self._last_form_issue else ""
                        return False, f"skipped: unresolved validation error after stalled step{detail}"
                    stagnant_steps = 0
                    last_state = ""
                    continue
                return False, "application stalled on the same step"

            self._upload_documents()
            if not self._fill_visible_controls_with_retries(3):
                detail = f": {self._last_form_issue}" if self._last_form_issue else ""
                return False, f"skipped: required question was not answered after live-DOM retries{detail}"
            self._set_follow_company()

            submit = self._find_action_button("submit")
            if submit:
                if self.config.review_before_submit and not self.confirm_submit(job):
                    return False, "user declined submission"
                if safe_click(self.driver, submit):
                    self._status("Submit clicked; waiting for LinkedIn confirmation…")
                    outcome = self._wait_for_action_outcome(state_before, timeout=5.5)
                    if outcome == "submitted":
                        return True, "submission confirmed structurally"
                    # Some LinkedIn variants leave the modal shell mounted while
                    # changing only the Applied state. Keep this secondary check
                    # after the language-neutral structural confirmation path.
                    if self._already_applied():
                        return True, "submission confirmed by Applied state"
                continue

            review = self._find_action_button("review")
            if review and safe_click(self.driver, review):
                self._status("Review/forward action clicked.")
                outcome = self._wait_for_action_outcome(state_before)
                if outcome == "submitted":
                    return True, "submission confirmed structurally"
                continue

            next_button = self._find_action_button("next")
            if next_button and safe_click(self.driver, next_button):
                self._status("Advanced using the Easy Apply primary action.")
                outcome = self._wait_for_action_outcome(state_before)
                if outcome == "submitted":
                    return True, "submission confirmed structurally"
                continue

            errors = self._validation_errors()
            if errors:
                self._status("LinkedIn reports validation errors; checking required fields.")
                if not self._fill_visible_controls_with_retries(2):
                    detail = f": {self._last_form_issue}" if self._last_form_issue else ""
                    return False, f"skipped: unresolved validation error{detail}"
                continue

            # Give delayed SDUI action buttons one bounded chance to render.
            for _ in range(6):
                time.sleep(0.3)
                if self._find_action_button("submit") or self._find_action_button("review") or self._find_action_button("next"):
                    break
            else:
                return False, "no supported next/review/submit action found"
        return False, "application exceeded safe step limit"

    def _application_state_fingerprint(self) -> str:
        assert self.driver is not None
        try:
            controls = inspect_form_controls(self.driver)
            parts: list[str] = []
            for item in controls[:80]:
                q = normalize_question(str(item.get("question") or ""))
                typ = str(item.get("type") or "")
                value = str(item.get("value") or "")[:80]
                parts.append(f"{typ}|{q}|{value}")
            for action in ("next", "review", "submit"):
                el = self._find_action_button(action)
                if el is not None:
                    try:
                        label = (el.get_attribute("aria-label") or "") + " " + (el.text or "")
                    except Exception:
                        label = action
                    parts.append(f"action:{action}:{normalize_question(label)}")
            return "||".join(parts)
        except Exception:
            return ""

    def _wait_for_application_change(self, before: str, timeout: float = 4.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end and not self.should_stop():
            time.sleep(0.2)
            if self._application_state_fingerprint() != before:
                return True
        return False

    def _wait_for_action_outcome(self, before: str, timeout: float = 5.0) -> str:
        """Return changed | submitted | unchanged without depending on UI language."""
        end = time.monotonic() + timeout
        saw_dialog = self._application_dialog_present()
        while time.monotonic() < end and not self.should_stop():
            time.sleep(0.2)
            try:
                text = deep_text(self.driver).lower()
                if any(phrase in text for phrase in SUCCESS_PHRASES):
                    return "submitted"
                dialog_now = self._application_dialog_present()
                if saw_dialog and not dialog_now:
                    # A forward primary action that closes the Easy Apply dialog
                    # with no validation error is the strongest language-neutral
                    # submission signal available in the browser DOM.
                    if not self._validation_errors():
                        return "submitted"
                if self._application_state_fingerprint() != before:
                    return "changed"
            except Exception:
                pass
        return "unchanged"

    def _is_application_action(self, element) -> bool:
        assert self.driver is not None
        try:
            return bool(self.driver.execute_script(
                """
                const e=arguments[0];
                if (!e) return false;
                const modal=e.closest && e.closest('[role=dialog], .jobs-easy-apply-modal, .artdeco-modal, form');
                const label=((e.getAttribute && e.getAttribute('aria-label')) || '') + ' ' + (e.innerText || e.textContent || '');
                const actionLabel=/submit application|review your application|review application|continue to next step|enviar candidatura|submeter candidatura|revisar|rever|continuar|pr[oó]ximo|seguinte/i.test(label);
                if (modal) {
                  const cls=String(modal.className || '').toLowerCase();
                  if (cls.includes('jobs-easy-apply')) return true;
                  if (modal.querySelector && modal.querySelector('input,select,textarea')) return true;
                  if (actionLabel) return true;
                }
                const root=e.getRootNode && e.getRootNode();
                if (root instanceof ShadowRoot && ((root.querySelector && root.querySelector('input,select,textarea')) || actionLabel)) return true;
                return false;
                """, element
            ))
        except Exception:
            return False

    def _find_action_button(self, action: str):
        assert self.driver is not None
        selectors_by_action = {
            "next": (
                "button[aria-label='Continue to next step']",
                "button[aria-label^='Continue']",
                "button[data-easy-apply-next-button]",
                "button[data-test-easy-apply-next-button]",
                "button[data-test-dialog-primary-btn]",
                "button.artdeco-button--primary",
                "[role='button'].artdeco-button--primary",
            ),
            "review": (
                "button[aria-label='Review your application']",
                "button[aria-label='Review application']",
                "button[aria-label^='Review']",
            ),
            "submit": (
                "button[aria-label='Submit application']",
                "button[aria-label^='Submit']",
                "button[data-test-easy-apply-submit-button]",
                "button[data-easy-apply-submit-button]",
                "button[data-control-name*='submit']",
                "button[data-test*='submit']",
            ),
        }
        text_needles = {
            "next": ("next", "continue", "continuar", "proximo", "próximo", "seguinte", "siguiente", "continuer", "suivant", "weiter", "avanti"),
            "review": ("review", "revisar", "rever", "revisao", "revisão", "revisión", "revoir", "überprüfen", "uberprufen", "rivedi"),
            "submit": ("submit application", "submit", "enviar candidatura", "submeter candidatura", "enviar inscrição", "enviar inscricao", "enviar solicitud", "envoyer", "bewerbung senden", "invia"),
        }
        for selector in selectors_by_action[action]:
            for element in deep_query_all(self.driver, selector):
                try:
                    if element.is_displayed() and element.is_enabled() and self._is_application_action(element):
                        return element
                except Exception:
                    continue
        for element in deep_query_all(self.driver, "button, [role='button']"):
            try:
                if not element.is_displayed() or not element.is_enabled() or not self._is_application_action(element):
                    continue
                text = ((element.get_attribute("aria-label") or "") + " " + (element.text or "")).strip().lower()
                folded = normalize_question(text)
                if any(normalize_question(needle) in folded for needle in text_needles[action]):
                    return element
            except Exception:
                pass

        # Final language-agnostic fallback. LinkedIn's action bar marks its
        # forward action as the primary button even when the label itself is
        # localised. Treat it as a generic forward action, never as a confirmed
        # submit. If it happens to be the final submit, _wait_for_action_outcome
        # below confirms submission structurally after the click.
        if action == "next":
            candidates = []
            for selector in (
                "button[data-test-dialog-primary-btn]",
                "button.artdeco-button--primary",
                "[role='button'].artdeco-button--primary",
            ):
                for element in deep_query_all(self.driver, selector):
                    try:
                        if element.is_displayed() and element.is_enabled() and self._is_application_action(element):
                            candidates.append(element)
                    except Exception:
                        continue
            if candidates:
                log.warning("Using structural primary-action fallback because the button label was not understood.")
                return candidates[-1]
        return None

    def _upload_documents(self) -> None:
        """Fill file controls that belong to the active Easy Apply form only.

        A page can contain unrelated hidden file inputs (profile/photo widgets).  The
        form inspector is already scoped to the active Easy Apply dialog/Shadow DOM,
        so reuse it instead of scanning the whole LinkedIn page.
        """
        assert self.driver is not None
        try:
            file_items = [i for i in inspect_form_controls(self.driver) if str(i.get("type") or "").lower() == "file"]
        except Exception:
            file_items = []
        for index, item in enumerate(file_items):
            element = item.get("element")
            if element is None:
                continue
            try:
                value = element.get_attribute("value") or ""
                if value:
                    continue
                context = " ".join(
                    str(item.get(key) or "")
                    for key in ("question", "name", "dataTest", "id", "autocomplete")
                )
                context_lower = normalize_question(context)
                path = ""
                cover_tokens = ("cover", "cover letter", "motivation", "carta", "lettre", "anschreiben")
                resume_tokens = ("resume", "cv", "curriculum", "curriculo", "currículo")
                if any(token in context_lower for token in cover_tokens) and self.config.cover_letter_path:
                    path = self.config.cover_letter_path
                elif any(token in context_lower for token in resume_tokens) and self.config.resume_path:
                    path = self.config.resume_path
                elif index == 0 and self.config.resume_path:
                    # Current Easy Apply's primary file control is the CV/resume.
                    path = self.config.resume_path
                elif self.config.cover_letter_path:
                    path = self.config.cover_letter_path
                if path and Path(path).expanduser().is_file():
                    element.send_keys(str(Path(path).expanduser().resolve()))
            except Exception as exc:
                log.debug("Easy Apply file upload field skipped: %s", exc)

    def _fill_visible_controls_with_retries(self, attempts: int = 3) -> bool:
        """Fill the current Easy Apply step with bounded live-DOM retries.

        React/SDUI can replace radio/select nodes after an event. A single stale
        snapshot should not abandon the whole application, so automatic and
        supervised runs both re-inspect the form before giving up.
        """
        attempts = max(1, int(attempts))
        for attempt in range(attempts):
            if self._fill_visible_controls(force_required=attempt > 0):
                return True
            if attempt + 1 < attempts:
                issue = self._last_form_issue or "unknown field"
                log.info(
                    "Easy Apply field recovery %d/%d for %r: waiting for LinkedIn to settle and re-inspecting live controls.",
                    attempt + 1, attempts - 1, issue,
                )
                time.sleep(0.35 + (0.2 * attempt))
                self._handle_transient_apply_dialogs()
        return False

    def _fill_visible_controls(self, force_required: bool = False) -> bool:
        assert self.driver is not None
        self._last_form_issue = ""
        try:
            controls = inspect_form_controls(self.driver)
        except Exception as exc:
            log.warning("Could not inspect Easy Apply controls: %s", exc)
            if force_required:
                self._last_form_issue = f"could not inspect form controls: {exc}"
            return not force_required

        radio_groups: dict[str, list[dict]] = {}
        checkbox_groups: dict[str, list[dict]] = {}
        simple: list[dict] = []
        for item in controls:
            try:
                t = str(item.get("type", "")).lower()
                group_key = str(item.get("groupKey") or item.get("name") or item.get("question") or id(item))
                if t in {"radio", "aria-radio"}:
                    radio_groups.setdefault(group_key, []).append(item)
                elif t in {"checkbox", "aria-checkbox", "aria-switch"}:
                    checkbox_groups.setdefault(group_key, []).append(item)
                elif t != "file":
                    simple.append(item)
            except Exception:
                continue

        # Every control is isolated. One broken DOM node can never crash the run.
        for group in radio_groups.values():
            try:
                if not self._handle_choice_group(group, "radio", force_required):
                    return False
            except Exception as exc:
                log.warning("Radio question could not be handled: %s", exc)
                if force_required or any(bool(i.get("required")) or bool(i.get("invalid")) for i in group):
                    self._last_form_issue = str(group[0].get("question") or "radio choice")
                    return False
                continue
        for group in checkbox_groups.values():
            try:
                if not self._handle_choice_group(group, "checkbox", force_required):
                    return False
            except Exception as exc:
                log.warning("Checkbox question could not be handled: %s", exc)
                if force_required or any(bool(i.get("required")) or bool(i.get("invalid")) for i in group):
                    self._last_form_issue = str(group[0].get("question") or "checkbox choice")
                    return False
                continue
        for item in simple:
            try:
                if not self._handle_simple_control(item, force_required):
                    return False
            except Exception as exc:
                log.warning("Application field could not be handled: %s", exc)
                if force_required or bool(item.get("required")) or bool(item.get("invalid")):
                    self._last_form_issue = str(item.get("question") or "application field")
                    return False
                continue

        # Re-read the live DOM after React/SDUI processed all events. This catches
        # the exact failure shown by LinkedIn where a control looked filled to
        # Selenium but remained on a placeholder or aria-invalid=true.
        return self._verify_required_controls()

    def _handle_simple_control(self, item: dict, force_required: bool) -> bool:
        element = item.get("element")
        if element is None:
            return True
        typ = str(item.get("type") or "").lower()
        try:
            enabled = element.is_enabled()
        except Exception:
            enabled = str(item.get("ariaDisabled") or "").lower() != "true"
        if not enabled:
            return True
        # Native inputs/selects/textareas must be visible. Custom ARIA/contenteditable
        # controls can be represented by a visible wrapper even when Selenium does
        # not consider the underlying node traditionally displayed.
        try:
            displayed = element.is_displayed()
        except Exception:
            displayed = True
        if not displayed and not typ.startswith("aria-") and typ != "contenteditable":
            return True

        question = str(item.get("question") or "Required field").strip()
        required = bool(item.get("required")) or bool(item.get("invalid"))
        effective_required = required or force_required
        current = str(item.get("value") or "").strip()
        tag = str(getattr(element, "tag_name", "") or "").lower()

        options: list[str] = []
        option_values: list[str] = []
        select: Select | None = None
        if typ in {"select-one", "select-multiple"} or tag == "select":
            try:
                select = Select(element)
                options, option_values, current = self._read_native_select(
                    select, required=effective_required
                )
            except Exception as exc:
                log.warning("Select inspection failed for %r: %s", question, exc)
                current = ""

        # Non-input ARIA comboboxes behave like custom selects: open first, then
        # inspect the live role=option list. Do this before resolution so the answer
        # engine receives the recruiter's actual choices.
        if typ == "aria-combobox" or (
            str(item.get("role") or "").lower() == "combobox" and bool(item.get("readOnly"))
        ):
            return self._handle_aria_combobox(item, force_required)

        autocomplete_like = looks_like_autocomplete(element, item)
        metadata = dict(item)
        metadata["choiceValues"] = option_values
        resolution = resolve_answer(self.config, question, typ or tag, options, current, metadata=metadata)
        answer = resolution.answer
        log.info(
            "Answer field question=%r type=%s required=%s source=%s choices=%d current=%r",
            question, typ or tag, required, resolution.source, len(options), current,
        )
        if resolution.source.startswith("autonomous-"):
            log.warning("Autonomous language-agnostic fallback used for %r: %r", question, resolution.answer)
            self._status(f"Autonomous fallback used for an unmapped choice: {question}")

        if resolution.should_prompt and not current:
            answer = self._ask_and_store(
                question, options, "", signature=str(item.get("fieldSignature") or "")
            )

        # Existing values are accepted only after we have proved they are real. A
        # native select placeholder is normalized to current='' by _read_native_select.
        if current and resolution.source == "existing" and not autocomplete_like:
            return self._control_valid_now(element, typ, effective_required)
        if current and resolution.source == "existing" and autocomplete_like:
            answer = current
        if not answer:
            if effective_required:
                self._last_form_issue = question
                self._status(f"Could not resolve required question safely: {question}")
                return False
            return True

        if select is not None:
            if self._select_option(select, element, str(answer), required=effective_required, question=question):
                return True
            # A saved/profile answer may no longer match the recruiter's current
            # choices. Supervised mode asks once with the live options and stores it.
            if self.config.run_mode == "supervised":
                retry = self._ask_and_store(
                    question, options, str(answer), signature=str(item.get("fieldSignature") or "")
                )
                if retry and self._select_option(
                    select, element, retry, required=effective_required, question=question
                ):
                    return True
            if effective_required:
                self._last_form_issue = question
                self._status(f"Could not select a valid option for: {question}")
                return False
            return True

        # LinkedIn frequently renders locations/schools/companies as input-backed
        # ARIA comboboxes. Typing text is insufficient: commit a concrete option.
        if autocomplete_like:
            definition = match_question(question)
            autocomplete_token = str(item.get("autocomplete") or "").lower()
            stable_name = str(item.get("name") or "").lower()
            location_like = bool(
                definition
                and definition.key in {
                    "current_location", "city", "county", "country", "address",
                    "passport_country", "nationality"
                }
            ) or autocomplete_token in {
                "address-level1", "address-level2", "address-level3", "country",
                "country-name", "street-address", "postal-code"
            } or any(token in stable_name for token in (
                "location", "city", "county", "country", "address"
            )) or any(token in normalize_question(question) for token in (
                "location", "city", "town", "county", "country", "address", "based", "located"
            ))
            ok = fill_autocomplete(
                self.driver, element, str(answer), location_like=location_like,
                timeout=7.0 if location_like else 5.0,
            )
            if ok and self._control_valid_now(element, typ, effective_required):
                self._status(f"Selected autocomplete answer for: {question}")
                return True
            self._status(f"Could not commit a valid autocomplete option for: {question}")
            if self.config.run_mode == "supervised":
                retry = self._ask_and_store(
                    question, [], str(answer), signature=str(item.get("fieldSignature") or "")
                )
                if retry and fill_autocomplete(
                    self.driver, element, retry, location_like=location_like, timeout=7.0
                ) and self._control_valid_now(element, typ, effective_required):
                    return True
            if effective_required:
                self._last_form_issue = question
                return False
            return True

        answer = self._prepare_scalar_answer(str(answer), item, typ, resolution.source)
        if not self._set_control_value(element, answer, question, effective_required, typ=typ):
            self._last_form_issue = question
            return False
        return True

    @staticmethod
    def _is_placeholder_option(text: str) -> bool:
        normalized = normalize_question(text)
        return normalized in {"select", "select an option", "choose", "choose an option", "please select", "--"} or normalized.startswith("select ")

    def _option_is_placeholder(self, option, index: int, *, required: bool = False) -> bool:
        try:
            label = str(option.text or "").strip()
        except Exception:
            label = ""
        try:
            value_attr = option.get_attribute("value")
            value = "" if value_attr is None else str(value_attr).strip()
        except Exception:
            value = ""
        try:
            disabled = not option.is_enabled()
        except Exception:
            disabled = False
        try:
            hidden = option.get_attribute("hidden") is not None
        except Exception:
            hidden = False
        if disabled or hidden:
            return True
        if self._is_placeholder_option(label):
            return True
        # The most reliable language-neutral placeholder signal is the first
        # option with an empty value. This is how LinkedIn's native Easy Apply
        # select renders “Select an option” in the current UI.
        if index == 0 and not value:
            return True
        if required and index == 0 and not label:
            return True
        return False

    def _read_native_select(self, select: Select, *, required: bool) -> tuple[list[str], list[str], str]:
        labels: list[str] = []
        values: list[str] = []
        current: list[str] = []
        for index, option in enumerate(select.options):
            if self._option_is_placeholder(option, index, required=required):
                continue
            try:
                label = str(option.text or "").strip()
                value = str(option.get_attribute("value") or "").strip()
            except Exception:
                continue
            if not label:
                label = value
            if not label:
                continue
            labels.append(label)
            values.append(value)
            try:
                if option.is_selected():
                    current.append(label)
            except Exception:
                pass
        # Critically, if the only selected option is a placeholder, current is
        # empty. The answer engine must never treat that state as LinkedIn autofill.
        return labels, values, "; ".join(current)

    def _control_valid_now(self, element, typ: str, required: bool) -> bool:
        assert self.driver is not None
        try:
            if str(element.get_attribute("aria-invalid") or "").lower() == "true":
                return False
        except Exception:
            pass
        typ = str(typ or "").lower()
        if typ in {"select-one", "select-multiple"} or str(getattr(element, "tag_name", "") or "").lower() == "select":
            try:
                select = Select(element)
                labels, _values, current = self._read_native_select(select, required=required)
                if required and not current:
                    return False
                if current and labels:
                    return True
                return not required
            except Exception:
                return not required
        if typ in {"radio", "checkbox", "aria-radio", "aria-checkbox", "aria-switch"}:
            item = {"element": element, "type": typ}
            return self._choice_selected(item) if required else True
        try:
            validity = self.driver.execute_script(
                "const e=arguments[0]; return !e.validity || e.validity.valid !== false;", element
            )
            if validity is False:
                return False
        except Exception:
            pass
        try:
            if typ in {"contenteditable", "aria-combobox", "aria-textbox"}:
                value = str(self.driver.execute_script(
                    "return (arguments[0].value || arguments[0].getAttribute('aria-valuetext') || arguments[0].innerText || arguments[0].textContent || '').trim();", element
                ) or "").strip()
            else:
                value = str(element.get_attribute("value") or element.get_attribute("aria-valuenow") or "").strip()
        except Exception:
            value = ""
        if value and self._is_placeholder_option(value):
            return False
        return bool(value) if required else True

    def _aria_combobox_options(self, element) -> list:
        assert self.driver is not None
        try:
            scoped = self.driver.execute_script(
                r"""
                const e=arguments[0], out=[];
                const root=e.getRootNode && e.getRootNode();
                const ids=String((e.getAttribute && (e.getAttribute('aria-controls') || e.getAttribute('aria-owns'))) || '').split(/\s+/).filter(Boolean);
                for (const id of ids) {
                  let box=null;
                  try { box=(root && root.querySelector && root.querySelector('#'+CSS.escape(id))) || document.getElementById(id); } catch (_) {}
                  if (box && box.querySelectorAll) for (const o of box.querySelectorAll('[role=option], option')) out.push(o);
                }
                if (!out.length) {
                  const box=e.closest && e.closest('[role=dialog], form, .jobs-easy-apply-modal, .artdeco-modal');
                  if (box && box.querySelectorAll) for (const o of box.querySelectorAll('[role=option]')) out.push(o);
                }
                return out;
                """,
                element,
            ) or []
            result = []
            for option in scoped:
                try:
                    if option.is_displayed() and option.is_enabled():
                        result.append(option)
                except Exception:
                    continue
            if result:
                return result
        except Exception:
            pass
        return visible_autocomplete_options(self.driver)

    def _aria_combobox_commit_verified(self, element, option, label: str, *, required: bool) -> bool:
        """Verify a custom combobox committed a concrete option, not just a click."""
        assert self.driver is not None
        wanted = normalize_question(label)
        for _ in range(5):
            try:
                state = self.driver.execute_script(
                    r"""
                    const e=arguments[0], o=arguments[1];
                    const val=String((e && (e.value || e.getAttribute('aria-valuetext') || e.getAttribute('data-value'))) || '').trim();
                    const text=String((e && (e.innerText || e.textContent)) || '').trim();
                    return {
                      invalid: !!(e && e.getAttribute('aria-invalid') === 'true'),
                      expanded: e ? e.getAttribute('aria-expanded') : null,
                      active: String((e && e.getAttribute('aria-activedescendant')) || ''),
                      optionId: String((o && o.id) || ''),
                      optionSelected: !!(o && o.getAttribute && o.getAttribute('aria-selected') === 'true'),
                      value: val, text: text
                    };
                    """,
                    element, option,
                ) or {}
                if bool(state.get("invalid")):
                    return False
                if bool(state.get("optionSelected")):
                    return True
                if state.get("optionId") and state.get("active") == state.get("optionId"):
                    return True
                actual = normalize_question(str(state.get("value") or ""))
                if actual and not self._is_placeholder_option(actual):
                    if actual == wanted or (len(wanted) >= 3 and wanted in actual) or (len(actual) >= 3 and actual in wanted):
                        return True
                # Some SDUI comboboxes update only after the popup closes and put
                # the selected label into the wrapper text rather than .value.
                text = normalize_question(str(state.get("text") or ""))
                if str(state.get("expanded") or "").lower() == "false" and text:
                    if text == wanted or (len(wanted) >= 3 and wanted in text):
                        return True
            except Exception:
                # The option often becomes stale after a successful selection. If
                # the combobox itself is now valid and has a concrete value, accept.
                if self._control_valid_now(element, "aria-combobox", required):
                    return True
            time.sleep(0.06)
        return self._control_valid_now(element, "aria-combobox", required)

    def _handle_aria_combobox(self, item: dict, force_required: bool) -> bool:
        element = item.get("element")
        if element is None:
            return True
        question = str(item.get("question") or "Required choice").strip()
        required = bool(item.get("required")) or bool(item.get("invalid"))
        effective_required = required or force_required
        current = str(item.get("value") or "").strip()
        if current and not self._is_placeholder_option(current) and self._control_valid_now(element, "aria-combobox", effective_required):
            return True
        safe_click(self.driver, element)
        time.sleep(0.12)
        option_elements = self._aria_combobox_options(element)
        choices: list[str] = []
        usable: list[tuple[object, str]] = []
        for option in option_elements:
            try:
                label = str(option.text or option.get_attribute("aria-label") or option.get_attribute("textContent") or "").strip()
            except Exception:
                continue
            if not label or self._is_placeholder_option(label):
                continue
            choices.append(label)
            usable.append((option, label))
        metadata = dict(item)
        metadata["choiceValues"] = [
            str(option.get_attribute("data-value") or option.get_attribute("value") or label)
            for option, label in usable
        ]
        resolution = resolve_answer(self.config, question, "select-one", choices, "", metadata=metadata)
        answer = resolution.answer
        if resolution.should_prompt:
            answer = self._ask_and_store(
                question, choices, "", signature=str(item.get("fieldSignature") or "")
            )
        if not answer:
            if effective_required:
                self._last_form_issue = question
                return False
            return True
        adapted = adapt_answer_to_choices(str(answer), choices) or str(answer)
        target = normalize_question(adapted)
        for option, label in usable:
            candidate = normalize_question(label)
            if candidate == target or (len(target) >= 3 and target in candidate) or (len(candidate) >= 3 and candidate in target):
                if safe_click(self.driver, option):
                    time.sleep(0.12)
                    if self._aria_combobox_commit_verified(
                        element, option, label, required=effective_required
                    ):
                        return True
        if self.config.run_mode == "supervised" and choices:
            retry = self._ask_and_store(
                question, choices, str(answer), signature=str(item.get("fieldSignature") or "")
            )
            if retry:
                retry_target = normalize_question(adapt_answer_to_choices(retry, choices) or retry)
                for option, label in usable:
                    if normalize_question(label) == retry_target and safe_click(self.driver, option):
                        if self._aria_combobox_commit_verified(
                            element, option, label, required=effective_required
                        ):
                            return True
        if effective_required:
            self._last_form_issue = question
            return False
        return True

    def _choice_available(self, item: dict) -> bool:
        assert self.driver is not None
        element = item.get("element")
        if element is None:
            return False
        try:
            if not element.is_enabled():
                return False
        except Exception:
            try:
                if str(element.get_attribute("aria-disabled") or "").lower() == "true":
                    return False
            except Exception:
                pass
        try:
            if element.is_displayed():
                return True
        except Exception:
            pass
        # LinkedIn frequently hides the native radio/checkbox and makes its label
        # the visible click target. Treat that as an available control.
        try:
            return bool(self.driver.execute_script(
                r"""
                const e=arguments[0];
                function visible(x){ if(!x) return false; const s=getComputedStyle(x), r=x.getBoundingClientRect(); return s.display!=='none' && s.visibility!=='hidden' && r.width>0 && r.height>0; }
                const root=e.getRootNode && e.getRootNode();
                let label=null;
                if (e.labels && e.labels.length) label=e.labels[0];
                if (!label && e.id && root && root.querySelector) { try { label=root.querySelector('label[for="'+CSS.escape(e.id)+'"]'); } catch(_){} }
                return visible(label) || visible(e.closest && e.closest('label'));
                """, element
            ))
        except Exception:
            return False

    def _choice_selected(self, item: dict) -> bool:
        """Read the selected state from the concrete element snapshot."""
        element = item.get("element")
        typ = str(item.get("type") or "").lower()
        if element is None:
            return False
        if typ.startswith("aria-"):
            try:
                return str(element.get_attribute("aria-checked") or "").lower() == "true"
            except Exception:
                return bool(item.get("selected"))
        try:
            return bool(element.is_selected())
        except Exception:
            try:
                return bool(element.get_property("checked"))
            except Exception:
                return bool(item.get("selected"))

    def _fresh_choice_candidates(self, item: dict) -> list[dict]:
        """Re-find a radio/checkbox after React/SDUI has re-rendered the form.

        LinkedIn can replace the native input immediately after a label click. The
        old WebElement then becomes stale, and checking it falsely reports that the
        click failed. This matcher re-inspects the active Easy Apply form and finds
        the same logical option using stable group/signature/value metadata.
        """
        assert self.driver is not None
        try:
            controls = inspect_form_controls(self.driver)
        except Exception:
            return []
        wanted_type = str(item.get("type") or "").lower()
        family = "radio" if "radio" in wanted_type else "checkbox"
        wanted_group = str(item.get("groupKey") or "")
        wanted_sig = str(item.get("fieldSignature") or "")
        wanted_name = str(item.get("name") or "")
        wanted_value = normalize_question(str(item.get("rawValue") or item.get("value") or ""))
        wanted_choice = normalize_question(str(item.get("choice") or ""))

        ranked: list[tuple[int, dict]] = []
        for fresh in controls:
            typ = str(fresh.get("type") or "").lower()
            fresh_family = "radio" if "radio" in typ else ("checkbox" if any(x in typ for x in ("checkbox", "switch")) else "")
            if fresh_family != family:
                continue
            score = 0
            if wanted_group and str(fresh.get("groupKey") or "") == wanted_group:
                score += 100
            if wanted_sig and str(fresh.get("fieldSignature") or "") == wanted_sig:
                score += 80
            if wanted_name and str(fresh.get("name") or "") == wanted_name:
                score += 30
            fresh_value = normalize_question(str(fresh.get("rawValue") or fresh.get("value") or ""))
            fresh_choice = normalize_question(str(fresh.get("choice") or ""))
            if wanted_value and fresh_value == wanted_value:
                score += 60
            if wanted_choice and fresh_choice == wanted_choice:
                score += 50
            if score > 0:
                ranked.append((score, fresh))
        ranked.sort(key=lambda row: row[0], reverse=True)
        return [item for _score, item in ranked]

    def _choice_selected_live(self, item: dict) -> bool:
        if self._choice_selected(item):
            return True
        for fresh in self._fresh_choice_candidates(item)[:4]:
            if self._choice_selected(fresh):
                return True
        return False

    def _activate_choice_once(self, item: dict, desired: bool = True) -> bool:
        """Try all safe click/setter routes on one current DOM option."""
        assert self.driver is not None
        element = item.get("element")
        typ = str(item.get("type") or "").lower()
        if element is None:
            return False
        if self._choice_selected(item) == desired:
            return True
        # Prefer the visible label/wrapper because LinkedIn often hides native inputs.
        try:
            clicked_label = bool(self.driver.execute_script(
                r"""
                const e=arguments[0]; const root=e.getRootNode && e.getRootNode(); let label=null;
                if (e.labels && e.labels.length) label=e.labels[0];
                if (!label && e.id && root && root.querySelector) { try { label=root.querySelector('label[for="'+CSS.escape(e.id)+'"]'); } catch(_){} }
                if (!label) label=e.closest && e.closest('label');
                const wrapper = label || (e.closest && e.closest('[role="radio"],[role="checkbox"],[role="switch"],.fb-dash-form-element,.fb-text-selectable__option'));
                if (wrapper) { wrapper.click(); return true; }
                return false;
                """, element
            ))
            if clicked_label:
                time.sleep(0.12)
                if self._choice_selected_live(item) == desired:
                    return True
        except Exception:
            pass
        if safe_click(self.driver, element):
            time.sleep(0.12)
            if self._choice_selected_live(item) == desired:
                return True

        # Keyboard route for custom/ARIA radio and checkbox controls. Some LinkedIn
        # variants keep the native input hidden and only commit selection when the
        # focusable label/wrapper receives SPACE.
        try:
            focus_target = self.driver.execute_script(
                r"""
                const e=arguments[0]; const root=e.getRootNode && e.getRootNode(); let label=null;
                if (e.labels && e.labels.length) label=e.labels[0];
                if (!label && e.id && root && root.querySelector) { try { label=root.querySelector('label[for="'+CSS.escape(e.id)+'"]'); } catch(_){} }
                if (!label) label=e.closest && e.closest('label');
                return label || (e.closest && e.closest('[role="radio"],[role="checkbox"],[role="switch"],.fb-text-selectable__option')) || e;
                """,
                element,
            )
            if focus_target is not None:
                try:
                    self.driver.execute_script("arguments[0].focus();", focus_target)
                except Exception:
                    pass
                focus_target.send_keys(Keys.SPACE)
                time.sleep(0.12)
                if self._choice_selected_live(item) == desired:
                    return True
        except Exception:
            pass

        # Last DOM-safe fallback for native controls. React sees input/change/click,
        # and verification is performed against a fresh DOM snapshot.
        if typ in {"radio", "checkbox"}:
            try:
                self.driver.execute_script(
                    """
                    const e=arguments[0], wanted=arguments[1];
                    const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'checked')?.set;
                    if (setter) setter.call(e, wanted); else e.checked=wanted;
                    e.dispatchEvent(new Event('input',{bubbles:true}));
                    e.dispatchEvent(new Event('change',{bubbles:true}));
                    e.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));
                    """, element, bool(desired)
                )
                time.sleep(0.12)
                if self._choice_selected_live(item) == desired:
                    return True
            except Exception:
                pass
        return False

    def _activate_choice(self, item: dict, desired: bool = True) -> bool:
        assert self.driver is not None
        if self._choice_selected_live(item) == desired:
            return True
        if self._activate_choice_once(item, desired):
            return True
        # The first click may have re-rendered the option. Retry against fresh nodes
        # matched by group/signature/value instead of a stale WebElement.
        for fresh in self._fresh_choice_candidates(item)[:4]:
            if self._activate_choice_once(fresh, desired):
                return True
        return self._choice_selected_live(item) == desired

    def _verify_required_controls(self) -> bool:
        assert self.driver is not None
        try:
            controls = inspect_form_controls(self.driver)
        except Exception:
            return True
        groups: dict[tuple[str, str], list[dict]] = {}
        simple: list[dict] = []
        for item in controls:
            typ = str(item.get("type") or "").lower()
            if typ in {"radio", "aria-radio", "checkbox", "aria-checkbox", "aria-switch"}:
                key = ("radio" if "radio" in typ else "checkbox", str(item.get("groupKey") or item.get("name") or item.get("question") or ""))
                groups.setdefault(key, []).append(item)
            elif typ != "file":
                simple.append(item)
        for (kind, _key), group in groups.items():
            must = any(bool(i.get("required")) or bool(i.get("invalid")) for i in group)
            if not must:
                continue
            if kind == "checkbox":
                individually_required = [i for i in group if bool(i.get("nativeRequired"))]
                satisfied = (
                    all(self._choice_selected(i) for i in individually_required)
                    if individually_required
                    else any(self._choice_selected(i) for i in group)
                )
            else:
                satisfied = any(self._choice_selected(i) for i in group)
            if not satisfied:
                question = str(group[0].get("question") or f"{kind} choice")
                self._last_form_issue = question
                log.warning("Required %s group remained unanswered after fill: %r", kind, question)
                return False
        for item in simple:
            if not (bool(item.get("required")) or bool(item.get("invalid"))):
                continue
            element = item.get("element")
            if element is None:
                continue
            typ = str(item.get("type") or "").lower()
            if not self._control_valid_now(element, typ, True):
                question = str(item.get("question") or "application field")
                self._last_form_issue = question
                log.warning("Required control remained invalid after fill: %r type=%s", question, typ)
                return False
        return True

    def _prepare_scalar_answer(self, answer: str, item: dict, typ: str, source: str) -> str:
        """Fit scalar answers to browser constraints without changing their meaning unnecessarily."""
        raw = str(answer or "").strip()
        typ = str(typ or "").lower()

        if typ in {"number", "range", "aria-spinbutton"}:
            try:
                value = float(raw.replace(",", "."))
            except Exception:
                try:
                    value = float(str(getattr(self.config, "default_numeric_answer", "0")).replace(",", "."))
                except Exception:
                    value = 0.0
            try:
                minimum = float(str(item.get("min") or ""))
                value = max(value, minimum)
            except Exception:
                minimum = 0.0
            try:
                maximum = float(str(item.get("max") or ""))
                value = min(value, maximum)
            except Exception:
                maximum = None
            try:
                step = float(str(item.get("step") or ""))
                if step > 0:
                    base = minimum if str(item.get("min") or "").strip() else 0.0
                    value = base + round((value - base) / step) * step
                    if maximum is not None:
                        value = min(value, maximum)
            except Exception:
                pass
            return str(int(value)) if float(value).is_integer() else ("%.10f" % value).rstrip("0").rstrip(".")

        if typ in {"date", "month", "week", "time", "datetime-local"}:
            now = datetime.now()
            formats = {
                "date": (r"^\d{4}-\d{2}-\d{2}$", now.strftime("%Y-%m-%d")),
                "month": (r"^\d{4}-\d{2}$", now.strftime("%Y-%m")),
                "week": (r"^\d{4}-W\d{2}$", f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"),
                "time": (r"^\d{2}:\d{2}(?::\d{2})?$", now.strftime("%H:%M")),
                "datetime-local": (r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$", now.strftime("%Y-%m-%dT%H:%M")),
            }
            pattern, fallback = formats[typ]
            if not re.match(pattern, raw):
                raw = str(item.get("min") or "").strip() or fallback
                log.warning("Autonomous browser-valid temporal fallback used for type=%s value=%r", typ, raw)
            minimum = str(item.get("min") or "").strip()
            maximum = str(item.get("max") or "").strip()
            if minimum and raw < minimum:
                raw = minimum
            if maximum and raw > maximum:
                raw = maximum
            return raw

        try:
            max_length = int(item.get("maxLength", -1))
        except Exception:
            max_length = -1
        try:
            min_length = int(item.get("minLength", -1))
        except Exception:
            min_length = -1
        if max_length > 0 and len(raw) > max_length:
            raw = raw[:max_length]
        if min_length > 0 and len(raw) < min_length and (source.startswith("default-") or source.startswith("resolver-error")):
            filler = " Not applicable"
            while len(raw) < min_length:
                raw += filler
            if max_length > 0:
                raw = raw[:max_length]
        return raw

    def _set_control_value(self, element, answer: str, question: str, required: bool, *, typ: str = "") -> bool:
        assert self.driver is not None
        typ = str(typ or "").lower()

        def read_value() -> str:
            try:
                if typ == "contenteditable":
                    return str(self.driver.execute_script(
                        "return (arguments[0].innerText || arguments[0].textContent || '').trim();", element
                    ) or "").strip()
                return str(element.get_attribute("value") or element.get_attribute("aria-valuenow") or "").strip()
            except Exception:
                return ""

        def accepted() -> bool:
            actual = read_value()
            if not actual:
                return False
            wanted = normalize_question(str(answer))
            got = normalize_question(actual)
            if got == wanted or (len(wanted) >= 3 and wanted in got) or (len(got) >= 3 and got in wanted):
                return self._control_valid_now(element, typ, required)
            # Number/date inputs can canonicalize the representation. If the DOM
            # validity API says the control is valid and it retained a value, accept.
            if typ in {"number", "range", "date", "month", "week", "time", "datetime-local", "aria-spinbutton"}:
                return self._control_valid_now(element, typ, required)
            return False

        try:
            element.clear()
        except Exception:
            pass
        try:
            element.send_keys(answer)
            time.sleep(0.08)
            if accepted():
                return True
        except Exception as first_exc:
            log.debug("Native typing failed for %r: %s", question, first_exc)

        # React/SDUI can ignore WebDriver typing or replace the DOM node's value.
        # Use the native property setter and emit the full input/change/blur chain.
        try:
            self.driver.execute_script(
                """
                const e=arguments[0], value=arguments[1], type=arguments[2];
                if (type === 'contenteditable' || e.isContentEditable) {
                  e.textContent=value;
                } else if (e.tagName === 'TEXTAREA') {
                  const setter=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')?.set;
                  if (setter) setter.call(e,value); else e.value=value;
                } else if (e.tagName === 'INPUT') {
                  const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')?.set;
                  if (setter) setter.call(e,value); else e.value=value;
                } else {
                  e.setAttribute('aria-valuenow', value);
                  if ('value' in e) e.value=value; else e.textContent=value;
                }
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
                e.dispatchEvent(new Event('blur',{bubbles:true}));
                """,
                element, answer, typ,
            )
            time.sleep(0.1)
            if accepted():
                return True
        except Exception as second_exc:
            log.warning("Could not fill %r through native setter: %s", question, second_exc)

        log.warning("Field %r did not retain/validate requested value %r", question, answer)
        return not required

    def _handle_choice_group(self, group: list[dict], kind: str, force_required: bool) -> bool:
        if not group:
            return True
        available = [item for item in group if self._choice_available(item)]
        if not available:
            # A required group with no interactable choice is a real form issue; do
            # not silently pretend it was answered.
            required = any(bool(i.get("required")) or bool(i.get("invalid")) for i in group)
            if required or force_required:
                self._last_form_issue = str(group[0].get("question") or f"{kind} choice")
                return False
            return True

        # Respect a genuinely selected choice, including aria-checked. Native
        # checkbox `required` applies to that checkbox individually; a group-level
        # required marker/asterisk only requires at least one selected option.
        selected = [item for item in available if self._choice_selected(item)]
        if kind == "radio" and selected:
            return True
        if kind == "checkbox":
            individually_required = [item for item in available if bool(item.get("nativeRequired"))]
            if individually_required and all(self._choice_selected(item) for item in individually_required):
                return True
            if not individually_required and selected:
                return True

        question = str(available[0].get("question") or "Required choice").strip()
        required = any(bool(i.get("required")) or bool(i.get("invalid")) for i in available)
        effective_required = required or force_required
        choices = [str(i.get("choice") or i.get("rawValue") or i.get("value") or "").strip() for i in available]
        choices = [c for c in choices if c]
        single_checkbox = kind == "checkbox" and len(available) == 1
        resolver_choices = [] if single_checkbox else choices
        metadata = dict(available[0])
        metadata["choiceValues"] = [str(i.get("rawValue") or i.get("value") or "") for i in available]
        uploaded_resume_choice = self._uploaded_resume_choice(question, resolver_choices)
        resolution = (
            resolve_answer(
                self.config, question, "boolean" if single_checkbox else kind, resolver_choices, "", metadata=metadata
            )
            if not uploaded_resume_choice
            else None
        )
        if uploaded_resume_choice:
            answer = uploaded_resume_choice
            answer_source = "uploaded-resume"
        else:
            assert resolution is not None
            answer = resolution.answer
            answer_source = resolution.source
        log.info(
            "Answer choice question=%r type=%s required=%s source=%s choices=%d",
            question, kind, required, answer_source, len(choices),
        )
        if answer_source.startswith("autonomous-"):
            log.warning("Autonomous language-agnostic fallback used for choice %r: %r", question, answer)
            self._status(f"Autonomous fallback selected a valid option for: {question}")
        if resolution and resolution.should_prompt:
            answer = self._ask_and_store(
                question, ["Yes", "No"] if single_checkbox else choices, "",
                signature=str(available[0].get("fieldSignature") or "")
            )
        if not answer:
            if effective_required:
                self._last_form_issue = question
                self._status(f"Could not resolve required choice safely: {question}")
                return False
            return True

        if single_checkbox:
            normalized_answer = normalize_question(str(answer))
            wants_checked = normalized_answer in {
                "yes", "y", "true", "1", "agree", "i agree", "accept", "accepted", "checked"
            }
            if (
                effective_required
                and self.config.run_mode == "automatic"
                and getattr(self.config, "automatic_choice_strategy", "first_valid") == "first_valid"
            ):
                wants_checked = True
                log.warning("Autonomous required-checkbox fallback used for %r", question)
            if wants_checked:
                ok = self._activate_choice(available[0], True)
                if not ok and effective_required:
                    self._last_form_issue = question
                return ok or not effective_required
            # Optional checkbox + No is already a valid answer. A required consent
            # checkbox cannot be satisfied by leaving it unchecked.
            if effective_required:
                self._last_form_issue = question
                return False
            return True

        requested = [x.strip() for x in re.split(r"[;|]", str(answer)) if x.strip()]
        if not requested:
            requested = [str(answer).strip()]
        matched_any = False
        for requested_answer in requested:
            adapted = adapt_answer_to_choices(requested_answer, choices) or requested_answer
            target = normalize_question(adapted)
            for item in available:
                choice_text = str(item.get("choice") or item.get("rawValue") or item.get("value") or "").strip()
                choice = normalize_question(choice_text)
                if choice == target or (len(target) >= 3 and target in choice) or (len(choice) >= 3 and choice in target):
                    clicked = self._activate_choice(item, True)
                    matched_any = matched_any or clicked
                    if clicked and kind == "radio":
                        # Verify the browser really changed the radio state; clicking
                        # a hidden input without this check caused false success.
                        return self._choice_selected_live(item)
                    if clicked:
                        break
        if matched_any:
            return True

        if self.config.run_mode == "supervised":
            retry = self._ask_and_store(
                question, choices, str(answer), signature=str(available[0].get("fieldSignature") or "")
            )
            if retry:
                adapted_retry = adapt_answer_to_choices(retry, choices) or retry
                target_retry = normalize_question(adapted_retry)
                for item in available:
                    choice_text = str(item.get("choice") or item.get("rawValue") or item.get("value") or "").strip()
                    choice = normalize_question(choice_text)
                    if choice == target_retry or (len(target_retry) >= 3 and target_retry in choice) or (len(choice) >= 3 and choice in target_retry):
                        if self._activate_choice(item, True):
                            return True

        if effective_required:
            self._last_form_issue = question
            self._status(f"Could not select a valid choice for: {question}")
            return False
        return True

    def _uploaded_resume_choice(self, question: str, choices: list[str]) -> str | None:
        """Return the LinkedIn option matching the configured local resume file."""
        resume_path = str(getattr(self.config, "resume_path", "") or "").strip()
        question_normalized = normalize_question(question)
        if not resume_path or not Path(resume_path).expanduser().is_file():
            return None
        if not any(token in question_normalized for token in ("resume", "cv", "curriculum", "curriculo")):
            return None

        filename = Path(resume_path).expanduser().name
        filename_normalized = normalize_question(filename)
        stem_normalized = normalize_question(Path(filename).stem)
        for choice in choices:
            choice_normalized = normalize_question(choice)
            if filename_normalized and filename_normalized in choice_normalized:
                return choice
            if len(stem_normalized) >= 3 and stem_normalized in choice_normalized:
                return choice
        return None

    def _known_answer(self, normalized_question: str) -> str:
        # Kept for backwards compatibility with external callers/tests.
        exact = self.config.answers.get(normalized_question, "")
        if exact:
            return exact
        for saved_q, saved_a in self.config.answers.items():
            if len(saved_q) >= 18 and (saved_q in normalized_question or normalized_question in saved_q):
                return saved_a
        return ""

    def _ask_and_store(self, question: str, choices: list[str], default: str, signature: str = "") -> str | None:
        try:
            answer = self.ask_question(question, choices, default)
        except Exception as exc:
            # UI callback failures must be converted into a clean skip, never a crash.
            log.exception("Question prompt failed for %r", question)
            self._status(f"Question prompt failed safely: {exc}")
            return None
        if answer is None or not str(answer).strip():
            return None
        answer = str(answer).strip()
        self.config.remember_answer(question, answer, signature=signature)
        if getattr(self, "persist_answers", True):
            try:
                self.config.save()
            except Exception:
                log.exception("Could not persist learned answer")
        return answer

    def _select_option(
        self, select: Select, element, answer: str, *, required: bool, question: str = ""
    ) -> bool:
        assert self.driver is not None
        option_rows: list[tuple[int, object, str, str]] = []
        for index, option in enumerate(select.options):
            if self._option_is_placeholder(option, index, required=required):
                continue
            try:
                label = str(option.text or "").strip()
                value = str(option.get_attribute("value") or "").strip()
            except Exception:
                continue
            if not label:
                label = value
            if label:
                option_rows.append((index, option, label, value))
        if not option_rows:
            return False

        labels = [row[2] for row in option_rows]
        values = [row[3] for row in option_rows]
        requested = [x.strip() for x in re.split(r"[;|]", str(answer)) if x.strip()]
        if not requested:
            requested = [str(answer).strip()]

        target_indices: list[int] = []
        for raw_answer in requested:
            adapted = adapt_answer_to_choices(raw_answer, labels)
            matched_index: int | None = None
            if adapted:
                target = normalize_question(adapted)
                for index, _option, label, _value in option_rows:
                    if normalize_question(label) == target:
                        matched_index = index
                        break
            if matched_index is None:
                # Some LinkedIn selects expose localized labels but stable raw values
                # (e.g. true/false). Match those as a second structural route.
                adapted_value = adapt_answer_to_choices(raw_answer, values)
                if adapted_value:
                    target_value = normalize_question(adapted_value)
                    for index, _option, _label, value in option_rows:
                        if normalize_question(value) == target_value:
                            matched_index = index
                            break
            if matched_index is None:
                raw_target = normalize_question(raw_answer)
                for index, _option, label, value in option_rows:
                    if raw_target in {normalize_question(label), normalize_question(value)}:
                        matched_index = index
                        break
            if matched_index is not None and matched_index not in target_indices:
                target_indices.append(matched_index)

        if not target_indices:
            return False
        if not select.is_multiple:
            target_indices = target_indices[:1]

        def verify() -> bool:
            try:
                selected_indices = self.driver.execute_script(
                    "return Array.from(arguments[0].options).map((o,i)=>o.selected?i:-1).filter(i=>i>=0);",
                    element,
                ) or []
                selected_indices = [int(i) for i in selected_indices]
            except Exception:
                selected_indices = []
                for index, option in enumerate(select.options):
                    try:
                        if option.is_selected():
                            selected_indices.append(index)
                    except Exception:
                        pass
            if not selected_indices:
                return False
            if any(
                self._option_is_placeholder(select.options[index], index, required=required)
                for index in selected_indices if 0 <= index < len(select.options)
            ):
                return False
            wanted = set(target_indices)
            got = set(selected_indices)
            if select.is_multiple:
                if not wanted.issubset(got):
                    return False
            elif not wanted.intersection(got):
                return False
            try:
                if str(element.get_attribute("aria-invalid") or "").lower() == "true":
                    return False
            except Exception:
                pass
            return self._control_valid_now(element, "select-multiple" if select.is_multiple else "select-one", required)

        # Route 1: Selenium's Select API.
        try:
            if select.is_multiple:
                try:
                    select.deselect_all()
                except Exception:
                    pass
                for index in target_indices:
                    select.select_by_index(index)
            else:
                select.select_by_index(target_indices[0])
            self.driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true})); arguments[0].dispatchEvent(new Event('change',{bubbles:true})); arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));",
                element,
            )
            time.sleep(0.1)
            if verify():
                return True
        except Exception as exc:
            log.debug("Selenium Select route failed for %r: %s", question, exc)

        # Route 2: click the concrete option.
        try:
            if not select.is_multiple:
                target = target_indices[0]
                select.options[target].click()
                self.driver.execute_script(
                    "arguments[0].dispatchEvent(new Event('input',{bubbles:true})); arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                    element,
                )
                time.sleep(0.1)
                if verify():
                    return True
        except Exception as exc:
            log.debug("Option click route failed for %r: %s", question, exc)

        # Route 3: native DOM selection. This is important for React/SDUI selects
        # where WebDriver reports a click but LinkedIn keeps the placeholder.
        try:
            self.driver.execute_script(
                """
                const e=arguments[0], rawIndices=arguments[1], indices=new Set(rawIndices), multiple=arguments[2];
                if (!multiple && rawIndices.length) {
                  const target=e.options[rawIndices[0]];
                  const setter=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value')?.set;
                  if (target && setter) setter.call(e, target.value);
                  else if (target) e.value=target.value;
                  e.selectedIndex=rawIndices[0];
                } else {
                  Array.from(e.options).forEach((o,i)=>{ o.selected=indices.has(i); });
                }
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
                e.dispatchEvent(new Event('blur',{bubbles:true}));
                """,
                element, target_indices, bool(select.is_multiple),
            )
            time.sleep(0.12)
            if verify():
                return True
        except Exception as exc:
            log.warning("Native select fallback failed for %r: %s", question, exc)

        log.warning("Select %r did not retain a valid option for answer %r", question, answer)
        return False

    def _set_follow_company(self) -> None:
        assert self.driver is not None
        for checkbox in deep_query_all(self.driver, "input[type='checkbox']"):
            try:
                context = self.driver.execute_script(
                    "const e=arguments[0]; const p=e.closest('label,div'); return (p&&p.innerText)||'';",
                    checkbox,
                ) or ""
                if "follow" in str(context).lower() and "company" in str(context).lower():
                    selected = checkbox.is_selected()
                    if selected != self.config.follow_company:
                        safe_click(self.driver, checkbox)
            except Exception:
                pass

    def _validation_errors(self) -> list[str]:
        assert self.driver is not None
        errors: list[str] = []
        for selector in (
            ".artdeco-inline-feedback__message",
            ".fb-dash-form-element__error-field",
            "[role='alert']",
        ):
            for el in deep_query_all(self.driver, selector):
                try:
                    text = (el.text or "").strip()
                    if text and text not in errors:
                        errors.append(text)
                except Exception:
                    pass
        return errors

    def _application_dialog_present(self) -> bool:
        assert self.driver is not None
        return bool(deep_query_all(self.driver, "div[role='dialog'], .jobs-easy-apply-modal, .artdeco-modal"))

    def _dismiss_modal(self) -> None:
        assert self.driver is not None
        for selector in (
            "button[aria-label='Dismiss']",
            "button[aria-label='Close']",
            "button.artdeco-modal__dismiss",
        ):
            elements = deep_query_all(self.driver, selector)
            if elements and safe_click(self.driver, elements[0]):
                time.sleep(0.4)
                break
        for element in deep_query_all(self.driver, "button"):
            try:
                text = (element.text or "").strip().lower()
                normalized = normalize_question(text)
                if normalized in {"discard", "discard application", "descartar", "descartar candidatura", "descartar aplicacao", "descartar aplicação"}:
                    safe_click(self.driver, element)
                    break
            except Exception:
                pass

    def _read_job_info(self, job_id: str) -> JobInfo:
        assert self.driver is not None
        structured = extract_job_metadata(self.driver)
        title = self._first_text("h1, .job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title")
        company = self._first_text(
            ".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name, a[href*='/company/']"
        )
        if not title or normalize_question(title) in {"csv", "jobs", "linkedin"}:
            title = structured.get("title", "") or title
        if not company:
            company = structured.get("company", "")
        if not title:
            title = (self.driver.title or "").split(" | ")[0].strip()
        location_info = extract_job_location_info(self.driver)
        location = location_info.get("value", "") or structured.get("location", "")
        location_source = location_info.get("source", "")
        location_confidence = location_info.get("confidence", "")
        if not location_info.get("value") and structured.get("location", ""):
            location_source = "job-metadata-jsonld"
            location_confidence = "high"

        location_source, location_confidence = sanitize_location_evidence(
            location, title=title, company=company, source=location_source, confidence=location_confidence
        )

        return JobInfo(
            job_id=job_id, title=title, company=company, location=location,
            location_source=location_source, location_confidence=location_confidence,
            url=self.driver.current_url,
        )

    def _first_text(self, selector: str) -> str:
        assert self.driver is not None
        for element in deep_query_all(self.driver, selector):
            try:
                text = (element.text or "").strip()
                if text:
                    return text
            except Exception:
                pass
        return ""

    def _is_blacklisted(self, job: JobInfo) -> bool:
        title = job.title.lower()
        company = job.company.lower()
        return any(x.lower() in company for x in self.config.blacklist_companies) or any(
            x.lower() in title for x in self.config.blacklist_titles
        )

    def _delay(self) -> float:
        return random.uniform(self.config.min_delay_seconds, self.config.max_delay_seconds)

    def _limit_reached(self) -> bool:
        limit = int(self.config.max_applications)
        return limit > 0 and self.stats.applied >= limit

    def _record(self, job: JobInfo, result: str, reason: str) -> None:
        path = Path(self.config.output_csv).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        exists = path.exists() and path.stat().st_size > 0
        fieldnames = ["timestamp", "job_id", "title", "company", "url", "result", "reason", "location"]
        if exists:
            with path.open("r", newline="", encoding="utf-8-sig") as handle:
                previous_fields = next(csv.reader(handle), [])
            if len(set(previous_fields)) != len(previous_fields) or not set(fieldnames[:-1]).issubset(previous_fields):
                raise ValueError("Unrecognized application history columns")
            fieldnames = previous_fields
            if "location" not in fieldnames:
                fieldnames = [*fieldnames, "location"]
                self._add_history_location_column(path, fieldnames)
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if not exists:
                writer.writeheader()
            writer.writerow(
                {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "job_id": job.job_id,
                    "title": job.title,
                    "company": job.company,
                    "url": job.url,
                    "result": result,
                    "reason": reason,
                    "location": job.location,
                }
            )

    @staticmethod
    def _add_history_location_column(path: Path, fieldnames: list[str]) -> None:
        # Publish a complete CSV so an active history reader never sees a half-migrated file.
        staging = path.with_name(f".{path.name}.{uuid4().hex}.writing")
        try:
            with path.open("r", newline="", encoding="utf-8-sig") as source:
                with staging.open("x", newline="", encoding="utf-8") as target:
                    reader = csv.DictReader(source, strict=True)
                    writer = csv.DictWriter(target, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in reader:
                        if None in row or any(value is None for value in row.values()):
                            raise ValueError("Incomplete application history row")
                        writer.writerow(row)
                    target.flush()
                    os.fsync(target.fileno())
            os.replace(staging, path)
        finally:
            staging.unlink(missing_ok=True)

    def _load_recent_job_ids(self) -> set[str]:
        path = Path(self.config.output_csv).expanduser() if self.config.output_csv else None
        if not path or not path.exists():
            return set()
        result: set[str] = set()
        try:
            with path.open("r", newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    if row.get("result") == "applied" and row.get("job_id"):
                        result.add(str(row["job_id"]))
        except Exception:
            pass
        return result
