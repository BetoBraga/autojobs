from linkedin_easy_apply.bot import EasyApplyBot
from linkedin_easy_apply.config import AppConfig
from linkedin_easy_apply.answer_engine import resolve_answer


class FakeOption:
    def __init__(self, text, value, *, selected=False, enabled=True, hidden=False):
        self.text = text
        self._value = value
        self._selected = selected
        self._enabled = enabled
        self._hidden = hidden
        self.owner = None

    def get_attribute(self, name):
        if name == "value":
            return self._value
        if name == "hidden":
            return "true" if self._hidden else None
        return None

    def is_enabled(self):
        return self._enabled

    def is_selected(self):
        return self._selected

    def click(self):
        if self.owner is not None and not self.owner.is_multiple:
            for option in self.owner.options:
                option._selected = False
        self._selected = True


class FakeSelect:
    def __init__(self, options, *, multiple=False):
        self.options = options
        self.is_multiple = multiple
        self.all_selected_options = [o for o in options if o._selected]
        for option in options:
            option.owner = self

    def _sync(self):
        self.all_selected_options = [o for o in self.options if o._selected]

    def select_by_index(self, index):
        if not self.is_multiple:
            for option in self.options:
                option._selected = False
        self.options[index]._selected = True
        self._sync()

    def deselect_all(self):
        for option in self.options:
            option._selected = False
        self._sync()


class FakeSelectElement:
    tag_name = "select"

    def __init__(self, fake_select):
        self.fake_select = fake_select
        self.options = fake_select.options

    def get_attribute(self, name):
        if name == "aria-invalid":
            return "false"
        return ""


class FakeDriver:
    def execute_script(self, script, *args):
        if "Array.from(arguments[0].options).map" in script:
            element = args[0]
            return [i for i, option in enumerate(element.options) if option._selected]
        if "label.click(); return true" in script:
            element = args[0]
            element._selected = True
            return True
        if "e.validity.valid" in script:
            return True
        return None


class FakeRadio:
    def __init__(self, value, *, displayed=False):
        self._value = value
        self._selected = False
        self._displayed = displayed

    def is_displayed(self):
        return self._displayed

    def is_enabled(self):
        return True

    def is_selected(self):
        return self._selected

    def get_property(self, name):
        return self._selected if name == "checked" else None

    def get_attribute(self, name):
        if name == "value":
            return self._value
        if name in {"aria-disabled", "aria-checked"}:
            return "false"
        return ""

    def click(self):
        self._selected = True


def make_bot(config=None):
    bot = EasyApplyBot.__new__(EasyApplyBot)
    bot.config = (config or AppConfig(run_mode="automatic", default_boolean_answer="No")).normalized()
    bot.driver = FakeDriver()
    bot._last_form_issue = ""
    bot._status = lambda _message: None
    return bot


def test_native_linkedin_yes_no_select_placeholder_is_not_existing_answer():
    bot = make_bot()
    select = FakeSelect([
        FakeOption("Select an option", "", selected=True),
        FakeOption("Yes", "Yes"),
        FakeOption("No", "No"),
    ])
    labels, values, current = bot._read_native_select(select, required=True)
    assert labels == ["Yes", "No"]
    assert values == ["Yes", "No"]
    assert current == ""

    resolution = resolve_answer(
        bot.config,
        "Do you have experience with Edge Device Update Management?",
        "select-one",
        labels,
        current,
        metadata={"choiceValues": values},
    )
    assert resolution.answer == "No"
    assert resolution.source == "default-boolean"


def test_native_linkedin_yes_no_select_commits_and_verifies_no():
    bot = make_bot()
    select = FakeSelect([
        FakeOption("Select an option", "", selected=True),
        FakeOption("Yes", "Yes"),
        FakeOption("No", "No"),
    ])
    element = FakeSelectElement(select)
    # Keep this regression focused on the selection/event/verification path;
    # browser validity itself is covered by source contract tests.
    bot._control_valid_now = lambda _el, _typ, _required: True
    assert bot._select_option(select, element, "No", required=True, question="Edge Device Update") is True
    assert select.options[2].is_selected() is True
    assert select.options[0].is_selected() is False


def test_hidden_native_radio_is_still_clickable_through_its_visible_label():
    bot = make_bot()
    yes = FakeRadio("Yes", displayed=False)
    no = FakeRadio("No", displayed=False)
    group = [
        {
            "element": yes,
            "type": "radio",
            "question": "Do you have production experience?",
            "choice": "Yes",
            "rawValue": "Yes",
            "required": True,
            "invalid": False,
            "fieldSignature": "radio|experience",
        },
        {
            "element": no,
            "type": "radio",
            "question": "Do you have production experience?",
            "choice": "No",
            "rawValue": "No",
            "required": True,
            "invalid": False,
            "fieldSignature": "radio|experience",
        },
    ]
    # Simulate LinkedIn's hidden input + visible label. _choice_available asks JS
    # whether the associated label is visible.
    original_execute = bot.driver.execute_script

    def execute(script, *args):
        if "visible(label)" in script:
            return True
        return original_execute(script, *args)

    bot.driver.execute_script = execute
    assert bot._handle_choice_group(group, "radio", False) is True
    assert no.is_selected() is True


def test_resume_choice_prefers_configured_uploaded_file(tmp_path):
    resume = tmp_path / "Roberto Braga (2026).pdf"
    resume.write_text("resume", encoding="utf-8")
    bot = make_bot(AppConfig(run_mode="automatic", resume_path=str(resume)))
    old_resume = FakeRadio("old-resume", displayed=True)
    uploaded_resume = FakeRadio("uploaded-resume", displayed=True)
    group = [
        {
            "element": old_resume,
            "type": "radio",
            "question": "Resume",
            "choice": "Resume - Older version.pdf",
            "rawValue": "old-resume",
            "required": True,
            "invalid": False,
        },
        {
            "element": uploaded_resume,
            "type": "radio",
            "question": "Resume",
            "choice": "Resume - Roberto Braga (2026).pdf",
            "rawValue": "uploaded-resume",
            "required": True,
            "invalid": False,
        },
    ]

    assert bot._handle_choice_group(group, "radio", False) is True
    assert uploaded_resume.is_selected() is True
    assert old_resume.is_selected() is False


def test_resume_choice_without_uploaded_file_uses_first_linkedin_option():
    bot = make_bot(AppConfig(run_mode="automatic"))
    newest_resume = FakeRadio("newest-resume", displayed=True)
    older_resume = FakeRadio("older-resume", displayed=True)
    group = [
        {
            "element": newest_resume,
            "type": "radio",
            "question": "Resume",
            "choice": "Resume - Newest version.pdf",
            "rawValue": "newest-resume",
            "required": True,
            "invalid": False,
        },
        {
            "element": older_resume,
            "type": "radio",
            "question": "Resume",
            "choice": "Resume - Older version.pdf",
            "rawValue": "older-resume",
            "required": True,
            "invalid": False,
        },
    ]

    assert bot._handle_choice_group(group, "radio", False) is True
    assert newest_resume.is_selected() is True
    assert older_resume.is_selected() is False


def test_structural_boolean_values_map_no_even_when_labels_are_unknown_language():
    config = AppConfig(run_mode="automatic", default_boolean_answer="No").normalized()
    result = resolve_answer(
        config,
        "未知の質問",
        "select-one",
        ["はい", "いいえ"],
        metadata={"choiceValues": ["true", "false"]},
    )
    assert result.answer == "いいえ"
    assert result.source == "default-boolean-structure"


def test_edge_device_update_yes_no_select_is_inferred_as_boolean_not_date():
    from linkedin_easy_apply.answer_engine import infer_answer_type

    inferred = infer_answer_type(
        "Do you have experience with Edge Device Update Management?",
        "select-one",
        ["Yes", "No"],
        metadata={"choiceValues": ["Yes", "No"]},
    )
    assert inferred == "boolean"


def test_full_simple_control_path_replaces_linkedin_placeholder_with_default_no(monkeypatch):
    import linkedin_easy_apply.bot as bot_module

    bot = make_bot()
    select = FakeSelect([
        FakeOption("Select an option", "", selected=True),
        FakeOption("Yes", "Yes"),
        FakeOption("No", "No"),
    ])
    element = FakeSelectElement(select)
    element.is_enabled = lambda: True
    element.is_displayed = lambda: True
    monkeypatch.setattr(bot_module, "Select", lambda el: el.fake_select)

    item = {
        "element": element,
        "type": "select-one",
        "question": "Do you have experience with Edge Device Update Management?*",
        "required": True,
        "invalid": True,
        "value": "",
        "name": "edge-device-update-management",
        "fieldSignature": "select-one|edge-device-update-management",
    }
    assert bot._handle_simple_control(item, False) is True
    assert select.options[2].is_selected() is True
    assert select.options[0].is_selected() is False


def test_required_single_checkbox_is_actually_checked_in_automatic_mode():
    bot = make_bot()
    checkbox = FakeRadio("true", displayed=True)
    item = {
        "element": checkbox,
        "type": "checkbox",
        "question": "Required acknowledgement",
        "choice": "Required acknowledgement",
        "rawValue": "true",
        "required": True,
        "invalid": False,
        "fieldSignature": "checkbox|required-acknowledgement",
    }
    assert bot._handle_choice_group([item], "checkbox", False) is True
    assert checkbox.is_selected() is True


def test_optional_single_checkbox_respects_boolean_yes_default():
    bot = make_bot(AppConfig(run_mode="automatic", default_boolean_answer="Yes"))
    checkbox = FakeRadio("true", displayed=True)
    item = {
        "element": checkbox,
        "type": "checkbox",
        "question": "Enable this option",
        "choice": "Enable this option",
        "rawValue": "true",
        "required": False,
        "invalid": False,
        "fieldSignature": "checkbox|enable-option",
    }
    assert bot._handle_choice_group([item], "checkbox", False) is True
    assert checkbox.is_selected() is True


def test_hidden_radio_with_localized_labels_uses_structural_true_false_values():
    bot = make_bot()
    yes = FakeRadio("true", displayed=False)
    no = FakeRadio("false", displayed=False)
    group = [
        {
            "element": yes,
            "type": "radio",
            "question": "未知の質問",
            "choice": "はい",
            "rawValue": "true",
            "required": True,
            "invalid": False,
            "fieldSignature": "radio|unknown-bool",
        },
        {
            "element": no,
            "type": "radio",
            "question": "未知の質問",
            "choice": "いいえ",
            "rawValue": "false",
            "required": True,
            "invalid": False,
            "fieldSignature": "radio|unknown-bool",
        },
    ]
    original_execute = bot.driver.execute_script

    def execute(script, *args):
        if "visible(label)" in script:
            return True
        return original_execute(script, *args)

    bot.driver.execute_script = execute
    assert bot._handle_choice_group(group, "radio", False) is True
    assert no.is_selected() is True
    assert yes.is_selected() is False


class RerenderRadio(FakeRadio):
    def __init__(self, value, *, displayed=False):
        super().__init__(value, displayed=displayed)
        self.stale = False

    def is_selected(self):
        if self.stale:
            raise RuntimeError("stale element")
        return self._selected

    def get_property(self, name):
        if self.stale:
            raise RuntimeError("stale element")
        return super().get_property(name)


def test_radio_click_that_rerenders_dom_is_verified_against_fresh_control(monkeypatch):
    import linkedin_easy_apply.bot as bot_module

    bot = make_bot()
    old_no = RerenderRadio("No", displayed=False)
    fresh_no = RerenderRadio("No", displayed=False)
    item = {
        "element": old_no,
        "type": "radio",
        "question": "Are you comfortable commuting to this job's location?\nRequired",
        "choice": "No",
        "rawValue": "No",
        "required": True,
        "invalid": False,
        "name": "commute",
        "groupKey": "radio|commute",
        "fieldSignature": "radio|commute",
    }
    fresh_item = dict(item)
    fresh_item["element"] = fresh_no

    def inspect(_driver):
        return [fresh_item]

    monkeypatch.setattr(bot_module, "inspect_form_controls", inspect)

    def execute(script, *args):
        if "visible(label)" in script:
            return True
        if "wrapper.click(); return true" in script:
            old_no.stale = True
            fresh_no._selected = True
            return True
        return None

    bot.driver.execute_script = execute
    assert bot._activate_choice(item, True) is True
    assert fresh_no.is_selected() is True


def test_post_open_location_filter_is_opt_in_and_legacy_strict_flag_cannot_block():
    from linkedin_easy_apply.models import JobInfo

    bot = make_bot(AppConfig(
        locations=["Dublin, County Dublin, Ireland"],
        strict_location_filter=True,
        post_open_location_filter=False,
    ))
    job = JobInfo(
        job_id="1",
        title="AI Engineer",
        company="Example",
        location="Lisbon, Portugal",
        location_source="jsonld-jobLocation",
        location_confidence="high",
    )
    assert bot._post_open_location_blocks("Dublin, County Dublin, Ireland", job) is False

    bot.config.post_open_location_filter = True
    assert bot._post_open_location_blocks("Dublin, County Dublin, Ireland", job) is True


def test_required_radio_has_keyboard_space_fallback_when_click_routes_do_not_commit(monkeypatch):
    import linkedin_easy_apply.bot as bot_module

    radio = FakeRadio("No", displayed=False)

    class KeyTarget:
        def send_keys(self, key):
            radio._selected = True

    class KeyboardOnlyDriver(FakeDriver):
        def execute_script(self, script, *args):
            if "wrapper.click(); return true" in script:
                return False
            if "return label ||" in script:
                return KeyTarget()
            if "arguments[0].focus()" in script:
                return None
            return super().execute_script(script, *args)

    bot = make_bot()
    bot.driver = KeyboardOnlyDriver()
    bot._fresh_choice_candidates = lambda _item: []
    monkeypatch.setattr(bot_module, "safe_click", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(bot_module.Keys, "SPACE", "SPACE", raising=False)
    item = {
        "element": radio,
        "type": "radio",
        "question": "Will you require sponsorship?",
        "choice": "No",
        "rawValue": "No",
        "required": True,
        "fieldSignature": "radio|sponsorship",
    }
    assert bot._activate_choice_once(item, True) is True
    assert radio.is_selected() is True
