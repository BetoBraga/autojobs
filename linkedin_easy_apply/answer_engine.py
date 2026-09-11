from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Mapping, Any

from .config import normalize_field_signature
from .question_catalog import PREFER_NOT, QuestionDefinition, is_social_question, match_question, normalize_for_match


@dataclass(frozen=True)
class AnswerResolution:
    answer: str | None
    source: str
    definition: QuestionDefinition | None = None
    should_prompt: bool = False


# Recruiters can author questions in any language. These aliases make boolean
# controls portable without pretending that arbitrary multiple-choice answers are
# interchangeable. Portuguese is intentionally first-class because it is common
# in the user's observed Easy Apply results, while the other aliases cover common
# European LinkedIn locales.
YES_ALIASES = {
    "yes", "y", "true", "1", "agree", "i agree", "accept", "accepted",
    "sim", "s", "verdadeiro", "concordo", "aceito",
    "si", "sí", "verdadero", "de acuerdo", "acepto",
    "oui", "vrai", "j accepte", "j’accepte", "d accord", "d'accord",
    "ja", "wahr", "stimme zu",
    "sì", "vero", "accetto",
    "tak", "ano",
}
NO_ALIASES = {
    "no", "n", "false", "0", "disagree", "i disagree", "decline",
    "nao", "não", "falso", "discordo", "nao aceito", "não aceito",
    "non", "faux", "je refuse",
    "nein", "falsch", "stimme nicht zu",
    "nope", "nie",
}
NA_ALIASES = {
    "n/a", "na", "not applicable", "not relevant", "none", "none of the above",
    "nao se aplica", "não se aplica", "nao aplicavel", "não aplicável", "nenhuma das anteriores",
    "no aplica", "no aplicable", "ninguna de las anteriores",
    "sans objet", "non applicable", "aucune de ces reponses", "aucune de ces réponses",
    "nicht zutreffend", "keine der oben genannten",
    "non applicabile", "nessuna delle precedenti",
}
PREFER_NOT_ALIASES = {
    *PREFER_NOT,
    "Prefer not to answer", "Prefer not to disclose", "I do not wish to answer",
    "Prefiro nao responder", "Prefiro não responder", "Prefiro nao informar", "Prefiro não informar",
    "Nao desejo responder", "Não desejo responder", "Nao desejo informar", "Não desejo informar",
    "Prefiero no responder", "Prefiero no decirlo", "Prefiero no informar",
    "Je prefere ne pas repondre", "Je préfère ne pas répondre", "Je ne souhaite pas repondre", "Je ne souhaite pas répondre",
    "Ich moechte nicht antworten", "Ich möchte nicht antworten",
}


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    chars: list[str] = []
    for ch in text:
        if ch.isalnum() or ch.isspace() or ch in "%+/#.'-_":
            chars.append(ch)
        else:
            chars.append(" ")
    return " ".join("".join(chars).lower().split())


def _canonical_boolean(value: str) -> bool | None:
    folded = _fold(value)
    yes = {_fold(v) for v in YES_ALIASES}
    no = {_fold(v) for v in NO_ALIASES}
    if folded in yes:
        return True
    if folded in no:
        return False
    return None


def infer_answer_type(question: str, input_type: str, choices: Iterable[str] = (), metadata: Mapping[str, Any] | None = None) -> str:
    definition = match_question(question)
    typ = (input_type or "").lower()
    meta = dict(metadata or {})
    normalized = _fold(question)
    input_mode = _fold(str(meta.get("inputMode") or meta.get("input_mode") or ""))
    autocomplete = _fold(str(meta.get("autocomplete") or ""))
    pattern = str(meta.get("pattern") or "")
    clean_choices = [str(x).strip() for x in choices if str(x).strip()]
    raw_choice_values = meta.get("choiceValues") or meta.get("choice_values") or []
    if not isinstance(raw_choice_values, (list, tuple)):
        raw_choice_values = []

    # A single checkbox/switch is represented as a boolean pseudo-type by the
    # form handler. Preserve the user's Yes/No default even when there are no
    # visible choice labels.
    if typ == "boolean":
        return "boolean"

    # DOM/control semantics are more trustworthy than recruiter wording. In
    # particular, “Update” contains the substring “date”, which previously made
    # a Yes/No select look like a date field. Boolean option structure therefore
    # wins before any lexical hint from the question.
    if clean_choices and looks_boolean_choices(clean_choices):
        return "boolean"
    if raw_choice_values:
        structural = {_canonical_boolean(str(v)) for v in raw_choice_values}
        if True in structural and False in structural:
            return "boolean"

    if typ in {"number", "range", "aria-spinbutton"} or input_mode in {"numeric", "decimal"} or re.search(r"\d|[0-9]", pattern):
        return "numeric"
    if typ in {"date", "month", "week", "time", "datetime-local"} or autocomplete in {"bday", "bday-day", "bday-month", "bday-year"}:
        return "date"

    # Catalog semantics are useful for text-looking fields (for example a years
    # question rendered as input[type=text]), but never override a stronger DOM
    # signal such as a Yes/No choice group or a native date/number control.
    if definition:
        return definition.answer_type

    numeric_cues = (
        "how many", "number of years", "years of", "percentage", "percent", "salary", "rate",
        "quantos", "quantas", "anos de experiencia", "anos de experiência", "percentagem", "porcentagem", "salario", "salário",
        "cuantos", "cuántos", "anos de experiencia", "años de experiencia", "porcentaje", "salario",
    )
    if any(_fold(token) in normalized for token in numeric_cues):
        return "numeric"

    # Word boundaries prevent false positives such as upDATE, valiDATE, candiDATE.
    if re.search(r"(?:^|\s)(date|data|fecha)(?:$|\s)", normalized):
        return "date"
    if typ in {"radio", "checkbox", "aria-radio", "aria-checkbox", "aria-switch", "select-one", "select-multiple", "aria-combobox"} or clean_choices:
        return "choice"
    return "text"


def looks_boolean_choices(choices: Iterable[str]) -> bool:
    vals = {_fold(v) for v in choices if str(v).strip()}
    if not vals or len(vals) > 8:
        return False
    has_yes = any(_canonical_boolean(v) is True for v in vals)
    has_no = any(_canonical_boolean(v) is False for v in vals)
    return has_yes and has_no


def _adapt_na(answer: str, clean: list[str]) -> str | None:
    if _fold(answer) not in {_fold(v) for v in NA_ALIASES}:
        return None
    aliases = {_fold(v) for v in NA_ALIASES}
    for choice in clean:
        if _fold(choice) in aliases:
            return choice
    return None


def _adapt_numeric_to_choices(answer: str, clean: list[str]) -> str | None:
    try:
        value = float(str(answer).strip().replace(",", "."))
    except Exception:
        return None
    for choice in clean:
        folded = _fold(choice)
        # Exact numeric option.
        numbers = re.findall(r"-?\d+(?:[.,]\d+)?", folded)
        parsed = []
        for token in numbers:
            try:
                parsed.append(float(token.replace(",", ".")))
            except ValueError:
                pass
        if len(parsed) == 1 and abs(parsed[0] - value) < 1e-9:
            return choice
        if len(parsed) >= 2:
            lo, hi = min(parsed[0], parsed[1]), max(parsed[0], parsed[1])
            if lo <= value <= hi:
                return choice
        if parsed:
            if any(token in folded for token in ("less than", "under", "menos de", "inferior a", "below")) and value < parsed[0]:
                return choice
            if any(token in folded for token in ("more than", "over", "mais de", "acima de", "above")) and value > parsed[-1]:
                return choice
    return None


def adapt_answer_to_choices(answer: str | None, choices: Iterable[str]) -> str | None:
    if answer is None:
        return None
    answer = str(answer).strip()
    if not answer:
        return None
    clean = [str(c).strip() for c in choices if str(c).strip()]
    if not clean:
        return answer
    an = _fold(answer)

    # Exact / containment first.
    for choice in clean:
        cn = _fold(choice)
        if cn == an or (len(an) >= 3 and an in cn) or (len(cn) >= 3 and cn in an):
            return choice

    # Canonical boolean adaptation across common LinkedIn locales.
    desired_bool = _canonical_boolean(answer)
    if desired_bool is not None:
        for choice in clean:
            if _canonical_boolean(choice) is desired_bool:
                return choice

    na = _adapt_na(answer, clean)
    if na:
        return na

    numeric = _adapt_numeric_to_choices(answer, clean)
    if numeric:
        return numeric
    return None


def prefer_not_to_say_choice(choices: Iterable[str]) -> str | None:
    clean = [str(c).strip() for c in choices if str(c).strip()]
    preferred_folded = {_fold(v) for v in PREFER_NOT_ALIASES}
    for choice in clean:
        cn = _fold(choice)
        if cn in preferred_folded:
            return choice
        if any(token in cn for token in (
            "prefer not", "decline", "rather not", "do not wish", "not disclose",
            "self identify", "self-identify", "prefer not to answer", "prefer not to disclose",
            "prefiro nao", "nao desejo", "prefiero no", "je prefere", "je ne souhaite", "mochte nicht", "moechte nicht",
        )):
            return choice
    return None


def _signature_answer(config, metadata: Mapping[str, Any] | None, choices: list[str]) -> tuple[str | None, str | None]:
    meta = dict(metadata or {})
    sig = normalize_field_signature(str(meta.get("fieldSignature") or meta.get("field_signature") or ""))
    if not sig:
        return None, None
    raw = str((getattr(config, "answer_signatures", {}) or {}).get(sig, "")).strip()
    if not raw:
        return None, None
    value = adapt_answer_to_choices(raw, choices) if choices else raw
    if not value and choices:
        value = _structural_boolean_from_values(raw, choices, metadata)
    if value:
        return value, "learned-signature"
    return None, None


def _profile_from_metadata(config, input_type: str, metadata: Mapping[str, Any] | None) -> str | None:
    """Resolve factual profile values from HTML semantics rather than display language."""
    meta = dict(metadata or {})
    typ = _fold(input_type)
    autocomplete = _fold(str(meta.get("autocomplete") or ""))
    name = _fold(str(meta.get("name") or ""))
    role = _fold(str(meta.get("role") or ""))
    profile = getattr(config, "profile_answers", {}) or {}

    def first(*keys: str) -> str | None:
        for key in keys:
            value = str(profile.get(key, "")).strip()
            if value:
                return value
        return None

    if typ == "email" or autocomplete == "email":
        return first("email")
    if typ == "tel" or autocomplete.startswith("tel"):
        return first("phone") or str(getattr(config, "phone_number", "") or "").strip() or None
    if typ == "url" or autocomplete == "url":
        return first("website_url", "linkedin_url")
    if autocomplete in {"given-name", "firstname", "first-name"}:
        return first("first_name")
    if autocomplete in {"family-name", "lastname", "last-name"}:
        return first("last_name")
    if autocomplete == "name":
        full = " ".join(x for x in (first("first_name"), first("last_name")) if x)
        return full or None
    if autocomplete in {"address-level2", "address-level3"}:
        return first("city", "current_location")
    if autocomplete == "address-level1":
        return first("county", "current_location")
    if autocomplete in {"country", "country-name"}:
        return first("country")
    if autocomplete in {"street-address", "address-line1", "address-line2"}:
        return first("address", "current_location")
    if autocomplete == "postal-code":
        return first("postal_code")
    if autocomplete == "organization":
        return first("current_company", "company")
    # Stable technical names often survive UI localisation. Keep these conservative.
    if any(token in name for token in ("email", "mail")):
        return first("email")
    if any(token in name for token in ("phone", "mobile", "telephone", "tel")):
        return first("phone") or str(getattr(config, "phone_number", "") or "").strip() or None
    if any(token in name for token in ("first_name", "firstname", "given_name")):
        return first("first_name")
    if any(token in name for token in ("last_name", "lastname", "family_name")):
        return first("last_name")
    if role == "combobox" and autocomplete in {"country", "country-name"}:
        return first("country")
    return None


def _structural_boolean_from_values(answer: str, choices: list[str], metadata: Mapping[str, Any] | None) -> str | None:
    meta = dict(metadata or {})
    values = meta.get("choiceValues") or meta.get("choice_values") or []
    if not isinstance(values, (list, tuple)) or len(values) != len(choices):
        return None
    desired = _canonical_boolean(answer)
    if desired is None:
        return None
    for label, raw in zip(choices, values):
        if _canonical_boolean(str(raw)) is desired:
            return label
    return None


def _first_valid_choice(choices: list[str]) -> str | None:
    for choice in choices:
        raw = str(choice).strip()
        if not raw:
            continue
        if all((not ch.isalnum()) for ch in raw):
            continue
        return raw
    return None



def _saved_answer(config, question: str, choices: list[str]) -> tuple[str | None, str | None]:
    """Match saved/learned/custom exact answers robustly.

    The UI historically called these "exact" answers while also telling users a
    stable fragment was acceptable. v2.5 makes that contract real: exact matches
    win, then a sufficiently descriptive saved fragment, then a conservative fuzzy
    wording match. Accents and punctuation do not break reuse.
    """
    learned = getattr(config, "answers", {}) or {}
    q = _fold(question)
    best: tuple[float, str, str] | None = None
    for saved_q, saved_a in learned.items():
        sq = _fold(saved_q)
        if not sq or not str(saved_a).strip():
            continue
        score = 0.0
        if sq == q:
            score = 1000.0
        elif len(sq) >= 8 and sq in q:
            # Deliberately allow a stable fragment added with "Add custom exact question".
            score = 900.0 + min(80.0, len(sq) / 4.0)
        elif len(q) >= 12 and q in sq:
            score = 850.0 + min(80.0, len(q) / 4.0)
        elif min(len(sq), len(q)) >= 18:
            ratio = SequenceMatcher(None, sq, q).ratio()
            if ratio >= 0.86:
                score = 700.0 + ratio * 100.0
        if score and (best is None or score > best[0]):
            best = (score, str(saved_a).strip(), str(saved_q))
    if not best:
        return None, None
    value = adapt_answer_to_choices(best[1], choices) if choices else best[1]
    return value, ("learned-exact" if best[0] >= 1000 else "learned-match")


def _multilingual_profile_hint(config, question: str, answer_type: str) -> str | None:
    """Use factual profile fields for common custom questions in Portuguese/European locales."""
    q = _fold(question)
    profile = getattr(config, "profile_answers", {}) or {}
    hints: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (("localizacao", "localização", "where are you based", "onde esta localizado", "onde está localizado", "ubicacion", "ubicación"), ("current_location", "address")),
        (("cidade", "city", "ciudad", "ville"), ("city", "current_location")),
        (("pais", "país", "country", "pais de residencia", "país de residência", "pays"), ("country",)),
        (("telefone", "telemovel", "telemóvel", "celular", "phone", "mobile", "telefono", "teléfono"), ("phone",)),
        (("email", "e-mail", "correo", "courriel"), ("email",)),
        (("website", "site", "portfolio", "portefolio", "portfólio"), ("website_url",)),
        (("linkedin",), ("linkedin_url",)),
        (("ingles", "inglês", "english", "anglais"), ("english_level", "english_fluent")),
        (("anos de experiencia", "anos de experiência", "years of experience", "años de experiencia", "annees d experience"), ("years_role_experience", "years_total_experience")),
        (("formacao", "formação", "degree", "diploma", "educacao", "educação"), ("highest_education", "degree_field")),
        (("universidade", "university", "universidad", "ecole", "école"), ("university",)),
    ]
    for needles, keys in hints:
        if any(_fold(needle) in q for needle in needles):
            for key in keys:
                value = str(profile.get(key, "")).strip()
                if value:
                    return value
    # Salary/rate are legacy top-level settings rather than catalog profile keys.
    if any(token in q for token in ("salario", "pretensao salarial", "pretensão salarial", "salary", "remuneracao", "remuneração", "compensacao", "compensação")):
        return str(getattr(config, "salary", "") or "").strip() or None
    if any(token in q for token in ("hourly rate", "daily rate", "valor hora", "taxa horaria", "taxa horária")):
        return str(getattr(config, "hourly_rate", "") or "").strip() or None
    return None


def resolve_answer(config, question: str, input_type: str, choices: Iterable[str] = (), current: str = "", metadata: Mapping[str, Any] | None = None) -> AnswerResolution:
    """Resolve without raising. Unknown questions never terminate a run.

    Priority:
      1. learned/custom exact answer
      2. configured catalog/profile answer
      3. multilingual factual profile hints / legacy quick fields
      4. existing LinkedIn/autofill value
      5. supervised prompt
      6. automatic typed default / social fallback
    """
    try:
        normalized = _fold(question)
        clean_choices = [str(c).strip() for c in choices if str(c).strip()]
        definition = match_question(question)

        signature_value, signature_source = _signature_answer(config, metadata, clean_choices)
        if signature_value:
            return AnswerResolution(signature_value, signature_source or "learned-signature", definition)

        saved, saved_source = _saved_answer(config, question, clean_choices)
        if saved:
            return AnswerResolution(saved, saved_source or "learned", definition)

        if definition:
            configured = getattr(config, "profile_answers", {}).get(definition.key, "")
            if str(configured).strip():
                value = adapt_answer_to_choices(str(configured), clean_choices) if clean_choices else str(configured).strip()
                if value:
                    return AnswerResolution(value, "profile", definition)

        answer_type = infer_answer_type(question, input_type, clean_choices, metadata)
        structural_profile = _profile_from_metadata(config, input_type, metadata)
        if structural_profile:
            value = adapt_answer_to_choices(structural_profile, clean_choices) if clean_choices else structural_profile
            if value:
                return AnswerResolution(value, "profile-structure", definition)
        hinted = _multilingual_profile_hint(config, question, answer_type)
        if hinted:
            value = adapt_answer_to_choices(hinted, clean_choices) if clean_choices else hinted
            if value:
                return AnswerResolution(value, "profile-hint", definition)

        # Backwards-compatible quick fields.
        if any(token in normalized for token in ("phone", "telefone", "telemovel", "telemóvel", "celular")) and getattr(config, "phone_number", ""):
            return AnswerResolution(str(config.phone_number), "profile", definition)
        if any(token in normalized for token in ("salary", "salario", "salário", "pretensao salarial", "pretensão salarial")) and getattr(config, "salary", ""):
            return AnswerResolution(str(config.salary), "profile", definition)
        if any(token in normalized for token in ("hourly", "daily rate", "rate", "taxa horaria", "taxa horária", "valor hora")) and getattr(config, "hourly_rate", ""):
            return AnswerResolution(str(config.hourly_rate), "profile", definition)

        # Existing browser/autofill value can remain untouched.
        if str(current).strip():
            return AnswerResolution(str(current).strip(), "existing", definition)

        mode = str(getattr(config, "run_mode", "supervised")).lower()
        if mode == "supervised":
            return AnswerResolution(None, "supervised", definition, should_prompt=True)

        # Automatic mode: never prompt. Sensitive/social questions must never fall
        # through to the generic "first valid choice" strategy, because that can
        # fabricate race, gender identity, sexual orientation, disability, etc.
        # Prefer a privacy-preserving option; otherwise leave the question unresolved
        # unless the user explicitly selected the legacy use-defaults policy.
        social = bool(definition.social) if definition else is_social_question(question)
        social_strategy = str(getattr(config, "social_question_strategy", "prefer_not_to_say"))
        if social and social_strategy == "prefer_not_to_say":
            if clean_choices:
                value = prefer_not_to_say_choice(clean_choices)
                if value:
                    return AnswerResolution(value, "social-prefer-not", definition)
            return AnswerResolution(None, "social-no-safe-choice", definition)

        # Immigration/work-right/citizenship answers are factual eligibility claims.
        # The catalog/profile/learned-answer paths above may answer them, but a generic
        # Boolean/Text fallback must not invent them. Users who want uninterrupted
        # automatic runs should configure these facts once in Answer Rules.
        if definition and definition.category == "Ireland & work eligibility":
            return AnswerResolution(None, "eligibility-unconfigured", definition)

        if answer_type == "boolean":
            raw = str(getattr(config, "default_boolean_answer", "No"))
        elif answer_type == "numeric":
            raw = str(getattr(config, "default_numeric_answer", "0"))
        else:
            raw = str(getattr(config, "default_text_answer", "N/A"))

        if clean_choices:
            adapted = adapt_answer_to_choices(raw, clean_choices)
            if adapted:
                return AnswerResolution(adapted, f"default-{answer_type}", definition)
            structural_bool = _structural_boolean_from_values(raw, clean_choices, metadata)
            if structural_bool:
                return AnswerResolution(structural_bool, "default-boolean-structure", definition)
            if social and social_strategy == "prefer_not_to_say":
                value = prefer_not_to_say_choice(clean_choices)
                if value:
                    return AnswerResolution(value, "social-prefer-not", definition)
            # Autonomous mode must not depend on knowing the display language. If
            # no semantic match is possible, use the first concrete option as a
            # deterministic last resort. This is explicitly logged as an assumption.
            # Users who prefer to skip ambiguous choices can set strategy=skip.
            if str(getattr(config, "automatic_choice_strategy", "first_valid")) == "first_valid":
                value = _first_valid_choice(clean_choices)
                if value:
                    return AnswerResolution(value, "autonomous-first-valid-choice", definition)
            return AnswerResolution(None, f"default-{answer_type}-no-matching-choice", definition)
        return AnswerResolution(raw, f"default-{answer_type}", definition)
    except Exception:
        mode = str(getattr(config, "run_mode", "supervised")).lower()
        if mode == "supervised":
            return AnswerResolution(None, "resolver-error", None, should_prompt=True)
        clean_choices = [str(c).strip() for c in choices if str(c).strip()]
        if clean_choices and str(getattr(config, "automatic_choice_strategy", "first_valid")) == "first_valid":
            value = _first_valid_choice(clean_choices)
            if value:
                return AnswerResolution(value, "resolver-error-autonomous-choice")
        return AnswerResolution(str(getattr(config, "default_text_answer", "N/A")), "resolver-error-default")
