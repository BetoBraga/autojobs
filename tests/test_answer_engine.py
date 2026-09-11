from linkedin_easy_apply.answer_engine import resolve_answer
from linkedin_easy_apply.config import AppConfig
from linkedin_easy_apply.question_catalog import QUESTION_CATALOG, match_question


def test_catalog_is_broad_and_dublin_focused():
    assert len(QUESTION_CATALOG) >= 100
    assert sum(q.dublin_recommended for q in QUESTION_CATALOG) >= 35
    assert match_question("Are you legally authorised to work in Ireland?").key == "ie_work_authorized"
    assert match_question("Will you now or in the future require visa sponsorship?").key == "ie_sponsorship"
    assert match_question("How many days per week can you work in our Dublin office?").key == "hybrid_days"


def test_profile_answer_beats_defaults():
    config = AppConfig(run_mode="automatic", profile_answers={"ie_work_authorized": "Yes"}).normalized()
    result = resolve_answer(config, "Are you legally authorized to work in Ireland?", "radio", ["Yes", "No"])
    assert result.answer == "Yes"
    assert result.source == "profile"


def test_supervised_unknown_requests_prompt():
    config = AppConfig(run_mode="supervised").normalized()
    result = resolve_answer(config, "Tell us the name of your favourite internal framework", "text")
    assert result.answer is None
    assert result.should_prompt is True


def test_automatic_unknown_uses_typed_defaults():
    config = AppConfig(
        run_mode="automatic",
        default_numeric_answer="3",
        default_text_answer="Not applicable",
        default_boolean_answer="No",
    ).normalized()
    assert resolve_answer(config, "How many widgets have you shipped?", "number").answer == "3"
    assert resolve_answer(config, "Please add a short note", "text").answer == "Not applicable"
    assert resolve_answer(config, "Can you work weekends?", "radio", ["Yes", "No"]).answer == "No"


def test_social_prefers_non_disclosure_when_available():
    config = AppConfig(run_mode="automatic", social_question_strategy="prefer_not_to_say").normalized()
    result = resolve_answer(config, "What is your gender?", "select-one", ["Man", "Woman", "Prefer not to say"])
    assert result.answer == "Prefer not to say"
    assert result.source == "social-prefer-not"


def test_unknown_choice_never_raises_and_uses_autonomous_fallback_by_default():
    config = AppConfig(run_mode="automatic", default_text_answer="N/A").normalized()
    result = resolve_answer(config, "Choose your favourite cloud", "select-one", ["AWS", "Azure", "GCP"])
    assert result.answer == "AWS"
    assert result.source == "autonomous-first-valid-choice"


def test_learned_stable_fragment_is_reused():
    config = AppConfig(run_mode="automatic", answers={"do you have experience with kubernetes": "Yes"}).normalized()
    result = resolve_answer(config, "Do you have experience with Kubernetes in production?", "radio", ["Yes", "No"])
    assert result.answer == "Yes"
    assert result.source == "learned-match"


def test_portuguese_boolean_custom_question_uses_boolean_fallback():
    config = AppConfig(run_mode="automatic", default_boolean_answer="No").normalized()
    result = resolve_answer(config, "Você possui disponibilidade para trabalhar aos fins de semana?", "radio", ["Sim", "Não"])
    assert result.answer == "Não"
    assert result.source == "default-boolean"


def test_portuguese_social_question_prefers_privacy_choice():
    config = AppConfig(run_mode="automatic", social_question_strategy="prefer_not_to_say").normalized()
    result = resolve_answer(config, "Você possui alguma deficiência?", "select-one", ["Sim", "Não", "Prefiro não responder"])
    assert result.answer == "Prefiro não responder"


def test_learned_answer_survives_accents_and_punctuation_changes():
    config = AppConfig(run_mode="automatic").normalized()
    config.remember_answer("Você possui experiência com Kubernetes?", "Sim")
    result = resolve_answer(config, "Voce possui experiencia com Kubernetes em produção", "radio", ["Sim", "Não"])
    assert result.answer == "Sim"
    assert result.source.startswith("learned")


def test_unicode_question_keys_do_not_collapse_for_non_latin_scripts():
    from linkedin_easy_apply.config import normalize_question
    assert normalize_question("現在どこに住んでいますか？")
    assert normalize_question("Где вы сейчас живёте?")
    assert normalize_question("أين تقيم حاليًا؟")


def test_arbitrary_language_text_field_uses_html_semantics_for_email():
    config = AppConfig(run_mode="automatic", profile_answers={"email": "person@example.com"}).normalized()
    result = resolve_answer(
        config,
        "メールアドレスを入力してください",
        "email",
        metadata={"autocomplete": "email", "fieldSignature": "email|candidateEmail"},
    )
    assert result.answer == "person@example.com"
    assert result.source == "profile-structure"


def test_arbitrary_language_unknown_select_uses_autonomous_first_valid_choice():
    config = AppConfig(run_mode="automatic", automatic_choice_strategy="first_valid").normalized()
    result = resolve_answer(config, "希望する勤務形態を選択してください", "select-one", ["在宅勤務", "出社勤務"])
    assert result.answer == "在宅勤務"
    assert result.source == "autonomous-first-valid-choice"


def test_arbitrary_language_unknown_select_can_be_configured_to_skip():
    config = AppConfig(run_mode="automatic", automatic_choice_strategy="skip").normalized()
    result = resolve_answer(config, "希望する勤務形態を選択してください", "select-one", ["在宅勤務", "出社勤務"])
    assert result.answer is None


def test_learned_signature_survives_question_language_change_with_structural_boolean_values():
    config = AppConfig(run_mode="automatic").normalized()
    signature = "radio|work_authorized|data-test-work-auth"
    config.remember_answer("Are you legally authorised to work?", "No", signature=signature)
    result = resolve_answer(
        config,
        "就労許可をお持ちですか？",
        "radio",
        ["はい", "いいえ"],
        metadata={"fieldSignature": signature, "choiceValues": ["true", "false"]},
    )
    assert result.answer == "いいえ"
    assert result.source == "learned-signature"


def test_numeric_inputmode_is_detected_without_understanding_question_language():
    config = AppConfig(run_mode="automatic", default_numeric_answer="7").normalized()
    result = resolve_answer(
        config,
        "この技術を使った経験年数",
        "text",
        metadata={"inputMode": "numeric"},
    )
    assert result.answer == "7"
    assert result.source == "default-numeric"


def test_arbitrary_language_unmapped_text_falls_back_in_automatic_mode():
    config = AppConfig(run_mode="automatic", default_text_answer="N/A").normalized()
    result = resolve_answer(config, "يرجى كتابة ملاحظة إضافية", "text")
    assert result.answer == "N/A"
    assert result.source == "default-text"


def test_arbitrary_language_unmapped_question_prompts_in_supervised_mode_and_can_be_learned():
    question = "Czy możesz pracować w weekendy?"
    config = AppConfig(run_mode="supervised").normalized()
    first = resolve_answer(config, question, "radio", ["Tak", "Nie"])
    assert first.answer is None
    assert first.should_prompt is True
    config.remember_answer(question, "Nie")
    reused = resolve_answer(config, question, "radio", ["Tak", "Nie"])
    assert reused.answer == "Nie"
    assert reused.source.startswith("learned")


def test_sensitive_choice_never_uses_arbitrary_first_valid_fallback():
    config = AppConfig(run_mode="automatic", social_question_strategy="prefer_not_to_say", automatic_choice_strategy="first_valid").normalized()
    result = resolve_answer(
        config,
        "How would you describe your gender identity? (mark all that apply)",
        "checkbox",
        ["Man", "Woman", "Non-binary", "Other"],
    )
    assert result.answer is None
    assert result.source == "social-no-safe-choice"


def test_sensitive_choice_prefers_privacy_option_when_available():
    config = AppConfig(run_mode="automatic", social_question_strategy="prefer_not_to_say").normalized()
    result = resolve_answer(
        config,
        "How would you describe your racial/ethnic background?",
        "radio",
        ["White", "Black", "Asian", "Prefer not to self-identify"],
    )
    assert result.answer == "Prefer not to self-identify"
    assert result.source == "social-prefer-not"


def test_work_eligibility_never_uses_generic_boolean_fallback_when_unconfigured():
    config = AppConfig(run_mode="automatic", default_boolean_answer="No").normalized()
    result = resolve_answer(
        config,
        "Will you now or in the future require sponsorship for employment visa status?",
        "radio",
        ["Yes", "No"],
    )
    assert result.answer is None
    assert result.source == "eligibility-unconfigured"


def test_work_eligibility_uses_explicit_profile_answer_when_configured():
    config = AppConfig(run_mode="automatic", profile_answers={"ie_sponsorship": "No"}).normalized()
    result = resolve_answer(
        config,
        "Will you now or in the future require sponsorship for employment visa status?",
        "radio",
        ["Yes", "No"],
    )
    assert result.answer == "No"
    assert result.source == "profile"
