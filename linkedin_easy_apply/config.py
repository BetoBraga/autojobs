from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .question_catalog import QUESTION_CATALOG


def app_data_dir() -> Path:
    if os.name == "nt" and os.getenv("APPDATA"):
        base = Path(os.environ["APPDATA"])
    elif sys_platform() == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / "autojobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_app_data_dir() -> Path:
    """Location used by pre-autojobs builds, retained only for migration."""
    if os.name == "nt" and os.getenv("APPDATA"):
        base = Path(os.environ["APPDATA"])
    elif sys_platform() == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "LinkedInEasyApplyAssistant"


def sys_platform() -> str:
    import sys
    return sys.platform


DATE_FILTERS = {
    "Any time": "",
    "Past 24 hours": "r86400",
    "Past week": "r604800",
    "Past month": "r2592000",
}

EXPERIENCE_LEVELS = {
    1: "Internship",
    2: "Entry level",
    3: "Associate",
    4: "Mid-Senior level",
    5: "Director",
    6: "Executive",
}

ANSWER_PROFILE_SCHEMA = "linkedin-easy-apply-answer-profile"
ANSWER_PROFILE_VERSION = 2

# LinkedIn does not publish a guaranteed "safe" automation interval. These are
# deliberately conservative UX thresholds for long unattended runs, not a
# promise that throttling/challenges cannot occur.
RECOMMENDED_MIN_DELAY_SECONDS = 3.0
RECOMMENDED_MAX_DELAY_SECONDS = 7.0
LOW_DELAY_WARNING_MAX_SECONDS = 5.0


def delay_is_aggressive(min_seconds: float, max_seconds: float) -> bool:
    """Return True when the configured action delay is unusually aggressive.

    This is only a heuristic warning. LinkedIn can rate-limit or challenge an
    account at any cadence depending on volume, account state, and server-side
    controls.
    """
    try:
        minimum = float(min_seconds)
        maximum = float(max_seconds)
    except (TypeError, ValueError):
        return True
    return minimum < RECOMMENDED_MIN_DELAY_SECONDS or maximum < LOW_DELAY_WARNING_MAX_SECONDS


def delay_warning_text(min_seconds: float, max_seconds: float) -> str:
    return (
        f"Current delay: {float(min_seconds):g}-{float(max_seconds):g} sec. Very low delays may "
        "increase the chance of LinkedIn throttling, challenge prompts, or temporary account "
        "restrictions (sometimes described as a soft ban). LinkedIn does not publish a guaranteed "
        f"safe interval. For long unattended runs, consider about {RECOMMENDED_MIN_DELAY_SECONDS:g}-"
        f"{RECOMMENDED_MAX_DELAY_SECONDS:g} sec or slower."
    )


WORK_TYPES = {
    1: "On-site",
    2: "Remote",
    3: "Hybrid",
}


ANYWHERE_LOCATION_ALIASES = {
    "",
    "any",
    "anywhere",
    "any location",
    "all",
    "all locations",
    "global",
    "worldwide",
    "remote",
    "remote anywhere",
    "remote worldwide",
}


def resolve_search_location(location: str) -> str:
    """Return the LinkedIn search-location scope without hard-coding a city.

    Users may target a city, a country, multiple countries, or broad remote work.
    Broad aliases intentionally resolve to Worldwide; the Remote work-type filter
    is controlled separately by f_WT=2.
    """
    value = str(location or "").strip()
    if value.casefold() in ANYWHERE_LOCATION_ALIASES:
        return "Worldwide"
    return value


@dataclass
class AppConfig:
    positions: list[str] = field(default_factory=lambda: ["Software Engineer"])
    locations: list[str] = field(default_factory=lambda: ["Worldwide"])
    phone_number: str = ""
    salary: str = ""
    hourly_rate: str = ""
    resume_path: str = ""
    cover_letter_path: str = ""
    blacklist_companies: list[str] = field(default_factory=list)
    blacklist_titles: list[str] = field(default_factory=list)
    experience_levels: list[int] = field(default_factory=list)
    work_types: list[int] = field(default_factory=list)
    date_posted: str = "r86400"
    max_applications: int = 10
    max_pages_per_search: int = 3
    min_delay_seconds: float = 3.0
    max_delay_seconds: float = 7.0
    review_before_submit: bool = True
    follow_company: bool = False
    run_mode: str = "supervised"  # supervised | automatic
    default_numeric_answer: str = "0"
    default_text_answer: str = "N/A"
    default_boolean_answer: str = "No"
    social_question_strategy: str = "prefer_not_to_say"  # prefer_not_to_say | use_defaults
    profile_answers: dict[str, str] = field(default_factory=dict)
    answers: dict[str, str] = field(default_factory=dict)
    answer_labels: dict[str, str] = field(default_factory=dict)
    answer_signatures: dict[str, str] = field(default_factory=dict)
    automatic_choice_strategy: str = "first_valid"  # first_valid | skip
    output_csv: str = ""
    chrome_profile_dir: str = ""
    headless_browser: bool = False
    strict_location_filter: bool = False  # deprecated compatibility field; forced off
    post_open_location_filter: bool = False
    theme_name: str = "Cadente"
    failsafe_seconds: int = 60
    onboarding_completed: bool = False
    show_run_disclaimer: bool = True

    def normalized(self) -> "AppConfig":
        self.positions = _clean_list(self.positions)
        self.locations = _clean_list(self.locations)
        if not self.locations:
            # Empty location means broad search, not Dublin. LinkedIn still needs a
            # search scope for predictable results, so use its broadest portable
            # scope instead of silently restoring a city-specific default.
            self.locations = ["Worldwide"]
        self.blacklist_companies = _clean_list(self.blacklist_companies)
        self.blacklist_titles = _clean_list(self.blacklist_titles)
        self.experience_levels = _clean_codes(self.experience_levels, EXPERIENCE_LEVELS)
        self.work_types = _clean_codes(self.work_types, WORK_TYPES)
        self.max_applications = max(0, int(self.max_applications))
        self.max_pages_per_search = max(0, int(self.max_pages_per_search))
        self.min_delay_seconds = max(0.0, float(self.min_delay_seconds))
        self.max_delay_seconds = max(self.min_delay_seconds, float(self.max_delay_seconds))
        if self.date_posted not in DATE_FILTERS.values():
            self.date_posted = "r86400"
        root = app_data_dir()
        if not self.output_csv:
            self.output_csv = str(root / "applications.csv")
        if not self.chrome_profile_dir:
            self.chrome_profile_dir = str(root / "chrome-profile")
        if self.run_mode not in {"supervised", "automatic"}:
            self.run_mode = "supervised"
        if self.social_question_strategy not in {"prefer_not_to_say", "use_defaults"}:
            self.social_question_strategy = "prefer_not_to_say"
        self.default_numeric_answer = _normalize_numeric_default(self.default_numeric_answer)
        self.default_text_answer = str(self.default_text_answer).strip() or "N/A"
        self.default_boolean_answer = _normalize_boolean_default(self.default_boolean_answer)
        if self.automatic_choice_strategy not in {"first_valid", "skip"}:
            self.automatic_choice_strategy = "first_valid"
        self.headless_browser = bool(self.headless_browser)
        self.strict_location_filter = False  # legacy strict gate is intentionally disabled
        self.post_open_location_filter = bool(self.post_open_location_filter)
        self.theme_name = str(self.theme_name).strip() or "Cadente"
        try:
            self.failsafe_seconds = min(900, max(15, int(self.failsafe_seconds)))
        except (TypeError, ValueError):
            self.failsafe_seconds = 60
        self.onboarding_completed = bool(self.onboarding_completed)
        self.show_run_disclaimer = bool(self.show_run_disclaimer)
        self.profile_answers = {
            str(k).strip(): str(v).strip() for k, v in self.profile_answers.items()
            if str(k).strip() and str(v).strip()
        }
        normalized_answers: dict[str, str] = {}
        normalized_labels: dict[str, str] = {}
        for k, v in self.answers.items():
            nk = normalize_question(k)
            if nk and str(v).strip():
                normalized_answers[nk] = str(v).strip()
                normalized_labels[nk] = str(self.answer_labels.get(k) or self.answer_labels.get(nk) or k).strip()
        self.answers = normalized_answers
        self.answer_labels = normalized_labels
        self.answer_signatures = {
            normalize_field_signature(k): str(v).strip()
            for k, v in (self.answer_signatures or {}).items()
            if normalize_field_signature(k) and str(v).strip()
        }
        return self


    def answer_profile_payload(self) -> dict[str, Any]:
        """Return a portable answer-only profile.

        Every catalog question is exported, including unanswered questions. This
        intentionally makes the JSON useful as an editable template. Search
        criteria, file paths, Chrome profile data and application history remain
        excluded.
        """
        self.normalized()
        complete_answers = {
            definition.key: self.profile_answers.get(definition.key, "")
            for definition in QUESTION_CATALOG
        }
        questions = [
            {
                "key": definition.key,
                "question": definition.label,
                "category": definition.category,
                "type": definition.answer_type,
                "choices": list(definition.choices),
                "dublin_recommended": definition.dublin_recommended,
                "social": definition.social,
                "answer": complete_answers[definition.key],
            }
            for definition in QUESTION_CATALOG
        ]
        return {
            "schema": ANSWER_PROFILE_SCHEMA,
            "version": ANSWER_PROFILE_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "defaults": {
                "numeric": self.default_numeric_answer,
                "text": self.default_text_answer,
                "boolean": self.default_boolean_answer,
                "social_question_strategy": self.social_question_strategy,
                "automatic_choice_strategy": self.automatic_choice_strategy,
            },
            # Kept for simple key/value editing and compatibility with existing tools.
            # Unlike v1, all catalog keys are present, even when their value is "".
            "profile_answers": complete_answers,
            # Human-readable catalog view of the same answers.
            "questions": questions,
            "learned_answers": dict(sorted(self.answers.items())),
            "learned_field_signatures": dict(sorted(self.answer_signatures.items())),
        }

    def export_answer_profile(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.answer_profile_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def import_answer_profile(self, path: Path, *, replace: bool = False) -> dict[str, int | bool | str]:
        """Import a portable answer profile without touching search/browser settings.

        Imported values win on key conflicts. With replace=True, existing explicit
        question and learned-answer dictionaries are cleared first.
        """
        path = Path(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Could not read JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Answer profile JSON must contain an object at the top level.")

        schema = payload.get("schema")
        if schema and schema != ANSWER_PROFILE_SCHEMA:
            raise ValueError(f"Unsupported answer profile schema: {schema}")
        version = payload.get("version", 1)
        try:
            version = int(version)
        except Exception as exc:
            raise ValueError("Answer profile version must be a number.") from exc
        if version > ANSWER_PROFILE_VERSION:
            raise ValueError(
                f"This answer profile uses version {version}; this app supports up to {ANSWER_PROFILE_VERSION}."
            )

        defaults = payload.get("defaults", {})
        profile_answers = payload.get("profile_answers", {})
        learned_answers = payload.get("learned_answers", payload.get("answers", {}))
        learned_signatures = payload.get("learned_field_signatures", payload.get("answer_signatures", {}))
        questions = payload.get("questions", [])

        # Compatibility with a full app config JSON, if a user selected one by mistake.
        if not defaults and any(k in payload for k in ("default_numeric_answer", "default_text_answer", "default_boolean_answer")):
            defaults = {
                "numeric": payload.get("default_numeric_answer"),
                "text": payload.get("default_text_answer"),
                "boolean": payload.get("default_boolean_answer"),
                "social_question_strategy": payload.get("social_question_strategy"),
                "automatic_choice_strategy": payload.get("automatic_choice_strategy"),
            }
        if not profile_answers and isinstance(payload.get("profile_answers"), dict):
            profile_answers = payload.get("profile_answers", {})

        if not isinstance(defaults, dict) or not isinstance(profile_answers, dict) or not isinstance(learned_answers, dict) or not isinstance(learned_signatures, dict):
            raise ValueError("Invalid answer profile structure.")
        if questions is None:
            questions = []
        if not isinstance(questions, list):
            raise ValueError("The 'questions' field must be a list when present.")

        # v2 adds a complete, human-readable questions list. Accept it in addition
        # to the v1 profile_answers object. Non-empty values from questions win;
        # blanks remain blanks and never erase existing answers in Merge mode.
        question_answers: dict[str, str] = {}
        for item in questions:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            answer = item.get("answer", "")
            question_answers[key] = "" if answer is None else str(answer).strip()

        merged_profile_answers = dict(profile_answers)
        for key, answer in question_answers.items():
            if answer or key not in merged_profile_answers:
                merged_profile_answers[key] = answer
        profile_answers = merged_profile_answers

        if not defaults and not profile_answers and not learned_answers and not questions:
            raise ValueError("No answer settings were found in this JSON file.")

        if replace:
            self.profile_answers = {}
            self.answers = {}
            self.answer_labels = {}
            self.answer_signatures = {}

        if defaults.get("numeric") is not None:
            self.default_numeric_answer = str(defaults.get("numeric"))
        if defaults.get("text") is not None:
            self.default_text_answer = str(defaults.get("text"))
        if defaults.get("boolean") is not None:
            self.default_boolean_answer = str(defaults.get("boolean"))
        if defaults.get("social_question_strategy") in {"prefer_not_to_say", "use_defaults"}:
            self.social_question_strategy = str(defaults.get("social_question_strategy"))
        if defaults.get("automatic_choice_strategy") in {"first_valid", "skip"}:
            self.automatic_choice_strategy = str(defaults.get("automatic_choice_strategy"))

        imported_profile = {
            str(k).strip(): str(v).strip() for k, v in profile_answers.items()
            if str(k).strip() and str(v).strip()
        }
        imported_learned: dict[str, str] = {}
        imported_labels: dict[str, str] = {}
        for k, v in learned_answers.items():
            if not str(k).strip() or not str(v).strip():
                continue
            nk = normalize_question(k)
            imported_learned[nk] = str(v).strip()
            imported_labels[nk] = str(k).strip()
        imported_signatures = {
            normalize_field_signature(k): str(v).strip()
            for k, v in learned_signatures.items()
            if normalize_field_signature(k) and str(v).strip()
        }
        self.profile_answers.update(imported_profile)
        self.answers.update(imported_learned)
        self.answer_labels.update(imported_labels)
        self.answer_signatures.update(imported_signatures)
        self.normalized()
        self.save()
        return {
            "profile_answers": len(imported_profile),
            "learned_answers": len(imported_learned),
            "learned_field_signatures": len(imported_signatures),
            "defaults_imported": bool(defaults),
            "mode": "replace" if replace else "merge",
        }

    def remember_answer(self, question: str, answer: str, signature: str = "") -> None:
        key = normalize_question(question)
        value = str(answer).strip()
        if not value:
            return
        if key:
            self.answers[key] = value
            self.answer_labels[key] = str(question).strip() or key
        sig = normalize_field_signature(signature)
        if sig:
            self.answer_signatures[sig] = value

    def remember_signature_answer(self, signature: str, answer: str) -> None:
        sig = normalize_field_signature(signature)
        value = str(answer).strip()
        if sig and value:
            self.answer_signatures[sig] = value

    def forget_answer(self, question_or_key: str) -> None:
        key = normalize_question(question_or_key)
        self.answers.pop(key, None)
        self.answer_labels.pop(key, None)

    def save(self, path: Path | None = None) -> Path:
        self.normalized()
        path = path or (app_data_dir() / "config.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        explicit_path = path is not None
        path = path or (app_data_dir() / "config.json")

        # One-time compatibility bridge for users upgrading from the earlier
        # LinkedIn Easy Apply Assistant builds. We read the old config only when
        # autojobs has no config yet; future saves go to the new autojobs folder.
        source_path = path
        if not explicit_path and not path.exists():
            legacy = legacy_app_data_dir() / "config.json"
            if legacy.exists():
                source_path = legacy

        if not source_path.exists():
            return cls().normalized()
        try:
            data: dict[str, Any] = json.loads(source_path.read_text(encoding="utf-8"))
            allowed = cls.__dataclass_fields__.keys()
            config = cls(**{k: v for k, v in data.items() if k in allowed}).normalized()
            if not explicit_path and source_path != path:
                try:
                    config.save(path)
                except Exception:
                    pass
            return config
        except Exception:
            return cls().normalized()



def _unicode_tokenize(value: str, extra: str = "") -> str:
    allowed = set(extra)
    chars: list[str] = []
    for ch in value:
        if ch.isalnum() or ch.isspace() or ch in allowed:
            chars.append(ch)
        else:
            chars.append(" ")
    return " ".join("".join(chars).strip().lower().split())


def normalize_field_signature(text: str) -> str:
    """Normalize a DOM-derived field signature without depending on display language."""
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("\n", " ").replace("’", "'")
    return _unicode_tokenize(value, extra="_:.#|/@+-")


def normalize_question(text: str) -> str:
    """Canonical question key that preserves Unicode scripts.

    Learned/custom answers therefore work for CJK, Cyrillic, Arabic and other
    scripts instead of collapsing non-Latin questions to an empty key. Accents,
    punctuation and line wrapping are still normalized for stable reuse.
    """
    value = unicodedata.normalize("NFKD", str(text))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("\n", " ").replace("’", "'")
    return _unicode_tokenize(value, extra="%+/#.'-_")


def _clean_list(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _clean_codes(values: list[int], allowed: dict[int, str]) -> list[int]:
    result: set[int] = set()
    for value in values:
        try:
            code = int(value)
        except (TypeError, ValueError):
            continue
        if code in allowed:
            result.add(code)
    return sorted(result)


def _normalize_numeric_default(value: Any) -> str:
    raw = str(value).strip().replace(",", ".") or "0"
    try:
        float(raw)
        return raw
    except ValueError:
        return "0"


def _normalize_boolean_default(value: Any) -> str:
    raw = str(value).strip().lower()
    if raw in {"yes", "y", "true", "1", "agree", "i agree"}:
        return "Yes"
    if raw in {"no", "n", "false", "0", "disagree", "i disagree"}:
        return "No"
    return "No"
