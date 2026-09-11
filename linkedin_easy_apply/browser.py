from __future__ import annotations

import logging
import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys

from .autocomplete import autocomplete_score, looks_like_autocomplete

log = logging.getLogger(__name__)


DEEP_QUERY_ALL_JS = r"""
const selector = arguments[0];
const found = [];
const seen = new Set();
function walk(root) {
  if (!root || seen.has(root)) return;
  seen.add(root);
  if (root.querySelectorAll) {
    for (const el of root.querySelectorAll(selector)) found.push(el);
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  }
}
walk(document);
return found;
"""

DEEP_TEXT_JS = r"""
const chunks = [];
const seen = new Set();
function walk(root) {
  if (!root || seen.has(root)) return;
  seen.add(root);
  if (root === document) {
    if (document.body && document.body.innerText) chunks.push(document.body.innerText);
  } else if (root.host && root.host.innerText) {
    chunks.push(root.host.innerText);
  }
  if (root.querySelectorAll) {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  }
}
walk(document);
return chunks.join('\n');
"""

FORM_CONTROLS_JS = r"""
const results = [];
const seenRoots = new Set();
const seenControls = new Set();
const applicationContainers = [];
const seenContainers = new Set();
const CONTROL_SELECTOR = [
  'input', 'textarea', 'select',
  '[contenteditable="true"]',
  '[role="textbox"]:not(input):not(textarea)',
  '[role="spinbutton"]:not(input)',
  '[role="radio"]:not(input)',
  '[role="checkbox"]:not(input)',
  '[role="switch"]:not(input)',
  '[role="combobox"]:not(input):not(select)'
].join(', ');

function textOf(el) { return el ? (el.innerText || el.textContent || '').trim() : ''; }
function folded(value) {
  return String(value || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}
function actionish(container) {
  if (!container || !container.querySelectorAll) return false;
  if (container.querySelector(
      'button[data-test-dialog-primary-btn], button[data-easy-apply-next-button], button[data-test-easy-apply-next-button], button[data-test-easy-apply-submit-button], button.artdeco-button--primary, button[type="submit"]'
  )) return true;
  const needles = [
    'next','continue','review','submit','continue applying','done',
    'proximo','próximo','continuar','seguinte','rever','revisar','enviar','submeter',
    'siguiente','continuar','revisar','enviar solicitud',
    'continuer','suivant','revoir','envoyer',
    'weiter','uberprufen','überprüfen','bewerbung senden',
    'avanti','continua','rivedi','invia'
  ].map(folded);
  for (const b of container.querySelectorAll('button, [role="button"]')) {
    const txt = folded((b.getAttribute && b.getAttribute('aria-label')) || '') + ' ' + folded(textOf(b));
    if (needles.some(n => txt.includes(n))) return true;
  }
  return false;
}
function addContainer(container) {
  if (!container || seenContainers.has(container) || !container.querySelectorAll) return;
  const controls = container.querySelectorAll(CONTROL_SELECTOR);
  if (!controls.length) return;
  const cls = folded(container.className || '');
  const role = folded(container.getAttribute && container.getAttribute('role'));
  const isKnownModal = role === 'dialog' || cls.includes('easy-apply') || cls.includes('artdeco-modal');
  if (!isKnownModal && !actionish(container)) return;
  seenContainers.add(container);
  applicationContainers.push(container);
}
function discover(root) {
  if (!root || seenRoots.has(root) || !root.querySelectorAll) return;
  seenRoots.add(root);
  for (const c of root.querySelectorAll('[role="dialog"], .jobs-easy-apply-modal, .artdeco-modal, form')) addContainer(c);
  if (root instanceof ShadowRoot && actionish(root)) addContainer(root);
  for (const el of root.querySelectorAll('*')) if (el.shadowRoot) discover(el.shadowRoot);
}
discover(document);

function rootQueryById(root, id) {
  if (!root || !id) return null;
  try {
    if (root.getElementById) {
      const found = root.getElementById(id);
      if (found) return found;
    }
    if (root.querySelector) return root.querySelector(`#${CSS.escape(id)}`);
  } catch (_) {}
  return null;
}
function nativeType(el) {
  const tag = String(el.tagName || '').toLowerCase();
  const role = folded(el.getAttribute && el.getAttribute('role'));
  if (tag === 'select') return el.multiple ? 'select-multiple' : 'select-one';
  if (tag === 'textarea') return 'textarea';
  if (tag === 'input') return folded(el.type || 'text') || 'text';
  if (role === 'radio') return 'aria-radio';
  if (role === 'checkbox') return 'aria-checkbox';
  if (role === 'switch') return 'aria-switch';
  if (role === 'combobox') return 'aria-combobox';
  if (role === 'spinbutton') return 'aria-spinbutton';
  if (role === 'textbox' || el.isContentEditable) return 'contenteditable';
  return role || tag || 'text';
}
function groupFor(el) {
  return el.closest && el.closest(
    '[role="radiogroup"], [role="group"], fieldset, .jobs-easy-apply-form-section__grouping, .fb-dash-form-element, [data-test-form-element], [data-test-form-builder-radio-button-form-component], [data-test-checkbox-form-component], [data-component-type], section, form'
  );
}
function questionFor(el, type) {
  const root = el.getRootNode && el.getRootNode();
  const labelled = el.getAttribute && el.getAttribute('aria-labelledby');
  if (labelled) {
    const pieces = [];
    for (const id of labelled.split(/\s+/)) {
      const node = rootQueryById(root, id) || rootQueryById(document, id);
      const txt = textOf(node);
      if (txt) pieces.push(txt);
    }
    if (pieces.length) return pieces.join(' ').trim();
  }
  const fs = el.closest && el.closest('fieldset');
  if (fs) {
    const legend = fs.querySelector('legend');
    if (legend && textOf(legend)) return textOf(legend);
  }
  const group = groupFor(el);
  if (group) {
    const legend = group.querySelector && group.querySelector('legend');
    if (legend && textOf(legend)) return textOf(legend);
    const labelledGroup = group.getAttribute && group.getAttribute('aria-labelledby');
    if (labelledGroup) {
      const pieces = [];
      for (const id of labelledGroup.split(/\s+/)) {
        const node = rootQueryById(group.getRootNode && group.getRootNode(), id) || rootQueryById(document, id);
        const txt = textOf(node);
        if (txt) pieces.push(txt);
      }
      if (pieces.length) return pieces.join(' ').trim();
    }
  }
  if (!['radio','checkbox','aria-radio','aria-checkbox','aria-switch'].includes(type) && el.id && root && root.querySelector) {
    try {
      const lab = root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab && textOf(lab)) return textOf(lab);
    } catch (_) {}
  }
  if (group && group.querySelectorAll) {
    const candidates = group.querySelectorAll('legend, .fb-dash-form-element__label, [data-test-form-element-label], h3, h4, label');
    for (const candidate of candidates) {
      const txt = textOf(candidate);
      if (!txt) continue;
      if (['radio','checkbox','aria-radio','aria-checkbox','aria-switch'].includes(type) && el.id && candidate.getAttribute && candidate.getAttribute('for') === el.id) continue;
      return txt;
    }
  }
  const aria = el.getAttribute && (el.getAttribute('aria-label') || el.getAttribute('placeholder'));
  if (aria) return aria.trim();
  return (el.getAttribute && el.getAttribute('name')) || el.id || 'Application field';
}
function choiceFor(el, type) {
  const root = el.getRootNode && el.getRootNode();
  if (el.id && root && root.querySelector) {
    try {
      const lab = root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab && textOf(lab)) return textOf(lab);
    } catch (_) {}
  }
  const parent = el.closest && el.closest('label');
  if (parent && textOf(parent)) return textOf(parent);
  if (type === 'aria-radio' || type === 'aria-checkbox' || type === 'aria-switch') {
    const aria = el.getAttribute && el.getAttribute('aria-label');
    if (aria) return aria.trim();
    const txt = textOf(el);
    if (txt) return txt;
  }
  return (el.getAttribute && el.getAttribute('value')) || el.value || '';
}
function selectedState(el, type) {
  try {
    if (type === 'radio' || type === 'checkbox') return !!el.checked;
    if (type === 'aria-radio' || type === 'aria-checkbox' || type === 'aria-switch') return folded(el.getAttribute('aria-checked')) === 'true';
  } catch (_) {}
  return false;
}
function groupKeyFor(el, question) {
  const type = nativeType(el);
  const ownName = (el.getAttribute && el.getAttribute('name')) || '';
  // Native radio groups are defined by name. Prefer that over a broad form/section
  // ancestor so two separate questions can never be merged accidentally.
  if ((type === 'radio' || type === 'checkbox') && ownName) return `${type}|${ownName}`;
  const group = groupFor(el);
  if (group) {
    const key = group.getAttribute && (group.getAttribute('name') || group.getAttribute('id') || group.getAttribute('aria-labelledby') || group.getAttribute('data-test'));
    if (key) return `${type}|${key}`;
  }
  return `${type}|${ownName || question || el.id || ''}`;
}
function collect(container) {
  if (!container || !container.querySelectorAll) return;
  for (const el of container.querySelectorAll(CONTROL_SELECTOR)) {
    if (seenControls.has(el)) continue;
    // Do not double-count ARIA wrappers that only proxy a native input we also collect.
    if (!el.matches('input,textarea,select') && el.querySelector && el.querySelector('input[type="radio"], input[type="checkbox"], input[role="combobox"], textarea, select')) continue;
    seenControls.add(el);
    const type = nativeType(el);
    if (['hidden','submit','button','reset','image'].includes(type)) continue;
    const question = questionFor(el, type);
    let invalid = false;
    try { invalid = (el.getAttribute('aria-invalid') === 'true') || (el.validity && el.validity.valid === false); } catch (_) {}
    const nativeRequired = !!el.required || el.getAttribute('aria-required') === 'true';
    const required = nativeRequired || /\*/.test(question || '');
    let value = '';
    let selectedIndex = -1;
    let selectedText = '';
    let selectedValue = '';
    let selectedDisabled = false;
    let selectedHidden = false;
    try {
      if (type === 'select-one' || type === 'select-multiple') {
        selectedIndex = Number(el.selectedIndex);
        if (selectedIndex >= 0 && el.options && el.options[selectedIndex]) {
          const opt = el.options[selectedIndex];
          selectedText = textOf(opt);
          selectedValue = String(opt.value || '');
          selectedDisabled = !!opt.disabled;
          selectedHidden = !!opt.hidden;
        }
        value = selectedValue;
      } else if (el.isContentEditable) {
        value = textOf(el);
      } else {
        value = String(el.value || el.getAttribute('aria-valuenow') || '');
      }
    } catch (_) {}
    results.push({
      element: el,
      type,
      question,
      choice: ['radio','checkbox','aria-radio','aria-checkbox','aria-switch'].includes(type) ? choiceFor(el, type) : '',
      name: (el.getAttribute && el.getAttribute('name')) || question || el.id,
      groupKey: groupKeyFor(el, question),
      required,
      nativeRequired,
      invalid,
      selected: selectedState(el, type),
      value,
      selectedIndex,
      selectedText,
      selectedValue,
      selectedDisabled,
      selectedHidden,
      multiple: !!el.multiple,
      role: (el.getAttribute && el.getAttribute('role')) || '',
      ariaChecked: (el.getAttribute && el.getAttribute('aria-checked')) || '',
      ariaExpanded: (el.getAttribute && el.getAttribute('aria-expanded')) || '',
      ariaAutocomplete: (el.getAttribute && el.getAttribute('aria-autocomplete')) || '',
      ariaControls: (el.getAttribute && (el.getAttribute('aria-controls') || el.getAttribute('aria-owns'))) || '',
      className: typeof el.className === 'string' ? el.className : '',
      id: el.id || '',
      rawValue: (el.getAttribute && el.getAttribute('value')) || value || '',
      autocomplete: (el.getAttribute && el.getAttribute('autocomplete')) || '',
      inputMode: (el.getAttribute && el.getAttribute('inputmode')) || '',
      pattern: (el.getAttribute && el.getAttribute('pattern')) || '',
      min: (el.getAttribute && el.getAttribute('min')) || '',
      max: (el.getAttribute && el.getAttribute('max')) || '',
      step: (el.getAttribute && el.getAttribute('step')) || '',
      minLength: Number.isFinite(el.minLength) ? el.minLength : -1,
      maxLength: Number.isFinite(el.maxLength) ? el.maxLength : -1,
      readOnly: !!el.readOnly || (el.getAttribute && el.getAttribute('aria-readonly') === 'true'),
      ariaDisabled: (el.getAttribute && el.getAttribute('aria-disabled')) || '',
      dataTest: (el.getAttribute && (el.getAttribute('data-test') || el.getAttribute('data-testid'))) || '',
      componentKey: (el.getAttribute && el.getAttribute('componentkey')) || '',
      pageLang: (document.documentElement && document.documentElement.lang) || '',
      fieldSignature: [
        type, (el.getAttribute && el.getAttribute('name')) || '', (el.getAttribute && el.getAttribute('autocomplete')) || '',
        (el.getAttribute && (el.getAttribute('data-test') || el.getAttribute('data-testid'))) || '',
        (el.getAttribute && el.getAttribute('componentkey')) || '',
        (el.getAttribute && el.getAttribute('role')) || '',
        (el.getAttribute && el.getAttribute('aria-controls')) || '',
        el.id || ''
      ].filter(Boolean).join('|'),
      autocompleteLike: type === 'aria-combobox' || ((el.getAttribute && el.getAttribute('role')) || '').toLowerCase() === 'combobox' ||
                        !!(el.getAttribute && el.getAttribute('aria-autocomplete')) ||
                        !!(el.getAttribute && (el.getAttribute('aria-controls') || el.getAttribute('aria-owns'))) ||
                        /typeahead|autocomplete|combobox/i.test(typeof el.className === 'string' ? el.className : '')
    });
  }
}

for (const container of applicationContainers) collect(container);
return results;
"""


JOB_METADATA_JS = r"""
function clean(v) {
  if (v && typeof v === 'object') return clean(v.name || v.value || v.addressCountry || '');
  return String(v || '').replace(/\s+/g, ' ').trim();
}
const result = {title:'', company:'', location:''};
for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
  try {
    const parsed = JSON.parse(script.textContent || '{}');
    const items = Array.isArray(parsed) ? parsed : [parsed];
    for (const item of items) {
      if (!item || typeof item !== 'object') continue;
      const type = Array.isArray(item['@type']) ? item['@type'].join(' ') : item['@type'];
      if (!/jobposting/i.test(String(type || '')) && !item.jobLocation && !item.hiringOrganization) continue;
      result.title = clean(item.title || item.name || result.title);
      const org = item.hiringOrganization;
      if (typeof org === 'string') result.company = clean(org);
      else if (org && typeof org === 'object') result.company = clean(org.name || result.company);
      const locs = Array.isArray(item.jobLocation) ? item.jobLocation : [item.jobLocation];
      for (const loc of locs) {
        const a = loc && loc.address;
        if (!a) continue;
        if (typeof a === 'string') result.location = clean(a);
        else if (typeof a === 'object') {
          result.location = [a.addressLocality, a.addressRegion, a.addressCountry].map(clean).filter(Boolean).join(', ');
        }
        if (result.location) break;
      }
      if (result.title || result.company || result.location) return result;
    }
  } catch (_) {}
}
return result;
"""

JOB_LOCATION_JS = r"""
function clean(v) {
  if (v && typeof v === 'object') return clean(v.name || v.value || v.addressCountry || '');
  return String(v || '').replace(/\s+/g, ' ').trim();
}
function result(value, source, confidence) {
  return {value: clean(value), source: String(source || ''), confidence: String(confidence || '')};
}
function fromJsonLd() {
  const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
  for (const script of scripts) {
    try {
      const parsed = JSON.parse(script.textContent || '{}');
      const items = Array.isArray(parsed) ? parsed : [parsed];
      for (const item of items) {
        if (!item || typeof item !== 'object') continue;
        const type = Array.isArray(item['@type']) ? item['@type'].join(' ') : item['@type'];
        if (!/jobposting/i.test(String(type || '')) && !item.jobLocation) continue;
        const locations = Array.isArray(item.jobLocation) ? item.jobLocation : [item.jobLocation];
        for (const loc of locations) {
          const address = loc && loc.address;
          if (!address) continue;
          if (typeof address === 'string' && clean(address)) return result(address, 'jsonld-jobLocation', 'high');
          if (typeof address === 'object') {
            const parts = [address.addressLocality, address.addressRegion, address.addressCountry]
              .map(clean).filter(Boolean);
            if (parts.length) return result(parts.join(', '), 'jsonld-jobLocation', 'high');
          }
        }
      }
    } catch (_) {}
  }
  return result('', '', '');
}
const structured = fromJsonLd();
if (structured.value) return structured;

// Only dedicated location nodes are trusted strongly enough to reject a job.
// Generic .tvm__text, description text and body-wide scans are intentionally not
// used as negative evidence because they frequently contain job titles, company
// office locations or prose such as "offices in Switzerland...".
const highSelectors = [
  '[data-test-job-location]',
  '[data-testid="job-location"]',
  '[data-testid*="job-location"]',
  '[data-view-name="job-details"] [class*="job-location"]',
  '[class*="job-details"] [class*="job-location"]',
  '[class*="top-card"] [class*="job-location"]',
  '[class*="top-card"] [class~="location"]'
];
for (const selector of highSelectors) {
  for (const el of document.querySelectorAll(selector)) {
    const text = clean(el.innerText || el.textContent);
    if (text && text.length <= 180) return result(text, selector, 'high');
  }
}

// Top-card summary containers are useful for display/debugging but only medium
// confidence. Python will never block an application solely from this source.
const summarySelectors = [
  '.job-details-jobs-unified-top-card__primary-description-container',
  '.job-details-jobs-unified-top-card__tertiary-description-container',
  '.jobs-unified-top-card__primary-description',
  '.jobs-unified-top-card__bullet'
];
for (const selector of summarySelectors) {
  for (const el of document.querySelectorAll(selector)) {
    const text = clean(el.innerText || el.textContent);
    if (!text) continue;
    const pieces = text.split(/\s*[·•|]\s*|\n+/).map(clean).filter(Boolean);
    for (const piece of pieces) {
      if (piece.length > 120) continue;
      // Keep obvious geography for diagnostics, but do not trust prose.
      const words = piece.split(/\s+/).filter(Boolean);
      if (words.length > 10) continue;
      if (/\b(remote|hybrid|ireland|portugal|united kingdom|united states|spain|france|germany|italy|netherlands)\b/i.test(piece)) {
        return result(piece, selector, 'medium');
      }
    }
  }
}
return result('', '', '');
"""

JOB_IDS_JS = r"""
const ids = new Set();
const seenRoots = new Set();
function addCandidate(value) {
  if (!value) return;
  const s = String(value);
  let m = s.match(/(?:jobPosting:|\/jobs\/view\/|job-card-component-ref-)(\d{5,})/);
  if (!m && /^\d{5,}$/.test(s)) m = [s, s];
  if (m) ids.add(m[1]);
}
function walk(root) {
  if (!root || seenRoots.has(root)) return;
  seenRoots.add(root);
  if (!root.querySelectorAll) return;
  for (const el of root.querySelectorAll('[data-job-id], [data-occludable-job-id], [data-entity-urn], [componentkey^="job-card-component-ref-"], a[href*="/jobs/view/"]')) {
    addCandidate(el.getAttribute('data-job-id'));
    addCandidate(el.getAttribute('data-occludable-job-id'));
    addCandidate(el.getAttribute('data-entity-urn'));
    addCandidate(el.getAttribute('componentkey'));
    addCandidate(el.href || el.getAttribute('href'));
  }
  for (const el of root.querySelectorAll('*')) if (el.shadowRoot) walk(el.shadowRoot);
}
walk(document);
return Array.from(ids);
"""


def build_chrome_driver(profile_dir: str, *, headless: bool = False) -> webdriver.Chrome:
    profile = Path(profile_dir).expanduser().resolve()
    profile.mkdir(parents=True, exist_ok=True)

    options = Options()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")
    options.add_argument(f"--user-data-dir={profile}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-features=CalculateNativeWinOcclusion")
    chrome_binary = os.environ.get("CHROME_BIN", "").strip()
    if chrome_binary:
        options.binary_location = chrome_binary
    # Normal desktop installations use Selenium Manager so Chrome/driver
    # compatibility is resolved at runtime. Nix/managed environments can
    # explicitly provide CHROMEDRIVER_PATH and CHROME_BIN without forcing
    # that requirement onto Windows/macOS users.
    chromedriver = os.environ.get("CHROMEDRIVER_PATH", "").strip()
    if chromedriver:
      driver = webdriver.Chrome(service=Service(chromedriver), options=options)
    else:
      driver = webdriver.Chrome(options=options)
    try:
      driver.execute_cdp_cmd("Emulation.setFocusEmulationEnabled", {"enabled": True})
    except Exception:
      driver.quit()
      raise
    return driver


def deep_query_all(driver: webdriver.Chrome, selector: str):
    return driver.execute_script(DEEP_QUERY_ALL_JS, selector) or []


def deep_text(driver: webdriver.Chrome) -> str:
    return str(driver.execute_script(DEEP_TEXT_JS) or "")


def inspect_form_controls(driver: webdriver.Chrome) -> list[dict]:
    return list(driver.execute_script(FORM_CONTROLS_JS) or [])


def collect_job_ids(driver: webdriver.Chrome) -> list[str]:
    return [str(x) for x in (driver.execute_script(JOB_IDS_JS) or [])]


def extract_job_metadata(driver: webdriver.Chrome) -> dict[str, str]:
    try:
        raw = driver.execute_script(JOB_METADATA_JS) or {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v or "").strip() for k, v in raw.items()}
    except Exception:
        return {}


def extract_job_location_info(driver: webdriver.Chrome) -> dict[str, str]:
    """Return location text plus provenance/confidence from the current job page.

    Only ``high`` confidence is safe negative evidence. Medium-confidence top-card
    summaries are retained for diagnostics but must not be used to reject a job.
    """
    try:
        raw = driver.execute_script(JOB_LOCATION_JS) or {}
        if isinstance(raw, dict):
            return {
                "value": str(raw.get("value") or "").strip(),
                "source": str(raw.get("source") or "").strip(),
                "confidence": str(raw.get("confidence") or "").strip().lower(),
            }
        # Backward compatibility with an older injected script shape.
        value = str(raw or "").strip()
        return {"value": value, "source": "legacy", "confidence": "medium" if value else ""}
    except Exception:
        return {"value": "", "source": "", "confidence": ""}


def extract_job_location(driver: webdriver.Chrome) -> str:
    return extract_job_location_info(driver).get("value", "")


def safe_click(driver: webdriver.Chrome, element) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        element.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            return False


AUTOCOMPLETE_OPTION_SELECTOR = (
    "[role='option'], "
    "[data-test-single-typeahead-entity-form-search-result], "
    ".basic-typeahead__selectable, .search-typeahead-v2__hit, "
    ".typeahead-option, .dropdown-item, .suggestion-item"
)



def visible_autocomplete_options(driver: webdriver.Chrome) -> list:
    """Collect visible autocomplete options across normal DOM and open shadow roots."""
    options = []
    seen: set[str] = set()
    for element in deep_query_all(driver, AUTOCOMPLETE_OPTION_SELECTOR):
        try:
            if not element.is_displayed() or not element.is_enabled():
                continue
            text = (element.text or element.get_attribute("innerText") or element.get_attribute("textContent") or "").strip()
            if not text:
                continue
            key = f"{text}|{element.get_attribute('id') or ''}|{element.get_attribute('data-test') or ''}"
            if key in seen:
                continue
            seen.add(key)
            options.append(element)
        except Exception:
            continue
    return options


def fill_autocomplete(
    driver: webdriver.Chrome,
    element,
    value: str,
    *,
    location_like: bool = False,
    timeout: float = 6.0,
) -> bool:
    """Fill an ARIA/typeahead field and commit a real suggestion.

    LinkedIn location fields are often text inputs backed by a selectable
    suggestion list. Typing text alone is not enough: the form can look filled
    while LinkedIn still considers the field invalid. This helper always tries
    to select a concrete visible option and only reports success after a commit.
    """
    value = str(value).strip()
    if not value:
        return False
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].focus();", element)
    except Exception:
        pass

    # Clear through both native events and keys so React/SDUI sees the change.
    try:
        driver.execute_script(
            """
            const e=arguments[0];
            const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(e, ''); else e.value='';
            e.dispatchEvent(new Event('input', {bubbles:true}));
            e.dispatchEvent(new Event('change', {bubbles:true}));
            """,
            element,
        )
    except Exception:
        try:
            element.clear()
        except Exception:
            pass
    # Location widgets differ in how much geography they accept. Try the full
    # profile location first, then progressively shorter factual forms while
    # still scoring suggestions against the original complete value.
    queries = [value]
    if location_like and "," in value:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if len(parts) >= 3:
            queries.append(f"{parts[0]}, {parts[-1]}")
        if parts:
            queries.append(parts[0])
    queries = list(dict.fromkeys(q for q in queries if q))

    per_query_timeout = max(0.8, float(timeout) / max(1, len(queries)))
    for query_value in queries:
        try:
            driver.execute_script(
                """
                const e=arguments[0];
                const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                if (setter) setter.call(e, ''); else e.value='';
                e.dispatchEvent(new Event('input', {bubbles:true}));
                """,
                element,
            )
        except Exception:
            try:
                element.clear()
            except Exception:
                pass
        try:
            element.click()
        except Exception:
            pass
        try:
            element.send_keys(query_value)
        except Exception:
            try:
                driver.execute_script(
                    """
                    const e=arguments[0], value=arguments[1];
                    const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                    if (setter) setter.call(e, value); else e.value=value;
                    e.dispatchEvent(new Event('input', {bubbles:true}));
                    e.dispatchEvent(new Event('change', {bubbles:true}));
                    """,
                    element,
                    query_value,
                )
            except Exception:
                continue

        deadline = __import__('time').monotonic() + per_query_timeout
        best = None
        best_score = -1.0
        while __import__('time').monotonic() < deadline:
            options = visible_autocomplete_options(driver)
            for option in options:
                try:
                    text = (option.text or option.get_attribute("innerText") or option.get_attribute("textContent") or "").strip()
                except Exception:
                    continue
                score = autocomplete_score(value, text, location_like=location_like)
                if score > best_score:
                    best, best_score = option, score
            # A visible listbox elsewhere on the page must never be mistaken for
            # this field. We require a genuine textual/geographic relationship.
            if best is not None and best_score >= 50.0:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'nearest'});", best)
                except Exception:
                    pass
                if safe_click(driver, best):
                    __import__('time').sleep(0.25)
                    try:
                        element.send_keys(Keys.TAB)
                    except Exception:
                        pass
                    return True
            __import__('time').sleep(0.2)

    # Never blindly commit the first suggestion for a location field. A location
    # control can legally offer Dublin, Ohio before Dublin, Ireland; ArrowDown +
    # Enter here would defeat the strict geographic filter. If no suggestion was
    # safely matched above, fail this field and let Supervised/skip handling take
    # over. Keyboard fallback remains available for non-location comboboxes.
    if location_like:
        return False

    # Last-resort keyboard commit for other accessible comboboxes.
    try:
        expanded = str(element.get_attribute("aria-expanded") or "").lower() == "true"
        if expanded or str(element.get_attribute("role") or "").lower() == "combobox":
            element.send_keys(Keys.ARROW_DOWN)
            __import__('time').sleep(0.15)
            element.send_keys(Keys.ENTER)
            __import__('time').sleep(0.25)
            element.send_keys(Keys.TAB)
            __import__('time').sleep(0.2)
            invalid = str(element.get_attribute("aria-invalid") or "").lower() == "true"
            still_expanded = str(element.get_attribute("aria-expanded") or "").lower() == "true"
            committed_value = str(element.get_attribute("value") or "").strip()
            return bool(committed_value) and not invalid and not still_expanded
    except Exception:
        pass
    return False
