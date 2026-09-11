"""Backward-compatible CLI entry point for the modernized Easy Apply bot.

The desktop GUI in app.py is recommended for normal use. This CLI keeps a
config.yaml workflow for contributors and existing users, but deliberately
uses a saved Chrome session instead of storing/typing the LinkedIn password.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from linkedin_easy_apply.bot import EasyApplyBot
from linkedin_easy_apply.config import AppConfig, app_data_dir


def load_legacy_yaml(path: str = "config.yaml") -> AppConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    uploads = data.get("uploads") or {}
    output = data.get("output_filename") or ""
    if isinstance(output, list):
        output = next((x for x in output if x), "")
    config = AppConfig(
        positions=data.get("positions") or [],
        locations=data.get("locations") or [],
        phone_number=str(data.get("phone_number") or ""),
        salary=str(data.get("salary") or ""),
        hourly_rate=str(data.get("rate") or ""),
        resume_path=str(uploads.get("Resume") or ""),
        cover_letter_path=str(uploads.get("Cover Letter") or ""),
        blacklist_companies=data.get("blacklist") or [],
        blacklist_titles=data.get("blackListTitles") or [],
        experience_levels=data.get("experience_level") or [],
        work_types=data.get("work_types") or [],
        date_posted=str(data.get("date_posted") or "r86400"),
        max_applications=int(data.get("max_applications") or 10),
        max_pages_per_search=int(data.get("max_pages_per_search") or 3),
        review_before_submit=bool(data.get("review_before_submit", True)),
        follow_company=bool(data.get("follow_company", False)),
        headless_browser=bool(data.get("headless_browser", False)),
        run_mode=str(data.get("run_mode") or "supervised"),
        default_numeric_answer=str(data.get("default_numeric_answer") or "0"),
        default_text_answer=str(data.get("default_text_answer") or "N/A"),
        default_boolean_answer=str(data.get("default_boolean_answer") or "No"),
        social_question_strategy=str(data.get("social_question_strategy") or "prefer_not_to_say"),
        profile_answers=data.get("profile_answers") or {},
        answers=data.get("answers") or {},
        output_csv=str(output or (app_data_dir() / "applications.csv")),
    )
    return config.normalized()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_legacy_yaml()

    def ask(question: str, choices: list[str], default: str) -> str | None:
        print(f"\nQuestion: {question}")
        if choices:
            print("Choices:", " | ".join(choices))
        value = input("Answer (blank = skip application): ").strip()
        return value or None

    def confirm(job) -> bool:
        if not config.review_before_submit:
            return True
        value = input(f"Submit {job.title} at {job.company}? [y/N] ").strip().lower()
        return value in {"y", "yes"}

    bot = EasyApplyBot(config, on_status=print, ask_question=ask, confirm_submit=confirm)
    stats = bot.run()
    print("Finished:", stats.as_dict())


if __name__ == "__main__":
    main()
