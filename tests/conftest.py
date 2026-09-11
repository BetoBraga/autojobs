"""Test-only Selenium stubs for offline Linux validation.

The Windows build installs the real Selenium dependency before packaging. The
offline validation environment has no internet access, so these stubs allow
pure unit tests to import modules that reference Selenium without pretending
to run a real browser.
"""
from __future__ import annotations

import importlib.util
import sys
import types

if importlib.util.find_spec("selenium") is None:
    selenium = types.ModuleType("selenium")
    webdriver = types.ModuleType("selenium.webdriver")
    common = types.ModuleType("selenium.common")
    exceptions = types.ModuleType("selenium.common.exceptions")
    webdriver_common = types.ModuleType("selenium.webdriver.common")
    by_mod = types.ModuleType("selenium.webdriver.common.by")
    keys_mod = types.ModuleType("selenium.webdriver.common.keys")
    chrome_mod = types.ModuleType("selenium.webdriver.chrome")
    chrome_options_mod = types.ModuleType("selenium.webdriver.chrome.options")
    chrome_service_mod = types.ModuleType("selenium.webdriver.chrome.service")
    support_mod = types.ModuleType("selenium.webdriver.support")
    support_ui_mod = types.ModuleType("selenium.webdriver.support.ui")

    class WebDriverException(Exception):
        pass

    class StaleElementReferenceException(WebDriverException):
        pass

    class NoSuchElementException(WebDriverException):
        pass

    class TimeoutException(WebDriverException):
        pass

    class By:
        ID = "id"
        XPATH = "xpath"
        LINK_TEXT = "link text"
        PARTIAL_LINK_TEXT = "partial link text"
        NAME = "name"
        TAG_NAME = "tag name"
        CLASS_NAME = "class name"
        CSS_SELECTOR = "css selector"

    class Keys:
        SPACE = "\ue00d"
        ENTER = "\ue007"
        TAB = "\ue004"
        ARROW_DOWN = "\ue015"
        CONTROL = "\ue009"

    class Options:
        def __init__(self):
            self.arguments = []
            self.experimental_options = {}
        def add_argument(self, arg):
            self.arguments.append(arg)
        def add_experimental_option(self, name, value):
            self.experimental_options[name] = value

    class Service:
        def __init__(self, executable_path=None):
            self.executable_path = executable_path

    class Select:
        def __init__(self, element):
            self._el = element
            self.options = getattr(element, "options", [])
            self.is_multiple = bool(getattr(element, "is_multiple", False))
            self.all_selected_options = [o for o in self.options if getattr(o, "is_selected", lambda: False)()]
        def select_by_index(self, index):
            for i, option in enumerate(self.options):
                if hasattr(option, "_selected"):
                    option._selected = i == index or self.is_multiple
            self.all_selected_options = [o for o in self.options if getattr(o, "is_selected", lambda: False)()]
        def deselect_all(self):
            for option in self.options:
                if hasattr(option, "_selected"):
                    option._selected = False
            self.all_selected_options = []

    class Chrome:
        def __init__(self, *args, **kwargs):
            raise WebDriverException("Real Selenium is not installed in this offline test environment")

    exceptions.WebDriverException = WebDriverException
    exceptions.StaleElementReferenceException = StaleElementReferenceException
    exceptions.NoSuchElementException = NoSuchElementException
    exceptions.TimeoutException = TimeoutException
    by_mod.By = By
    keys_mod.Keys = Keys
    chrome_options_mod.Options = Options
    chrome_service_mod.Service = Service
    support_ui_mod.Select = Select
    webdriver.Chrome = Chrome
    webdriver.chrome = chrome_mod
    selenium.webdriver = webdriver
    common.exceptions = exceptions

    for name, module in {
        "selenium": selenium,
        "selenium.webdriver": webdriver,
        "selenium.common": common,
        "selenium.common.exceptions": exceptions,
        "selenium.webdriver.common": webdriver_common,
        "selenium.webdriver.common.by": by_mod,
        "selenium.webdriver.common.keys": keys_mod,
        "selenium.webdriver.chrome": chrome_mod,
        "selenium.webdriver.chrome.options": chrome_options_mod,
        "selenium.webdriver.chrome.service": chrome_service_mod,
        "selenium.webdriver.support": support_mod,
        "selenium.webdriver.support.ui": support_ui_mod,
    }.items():
        sys.modules.setdefault(name, module)
