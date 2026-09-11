from __future__ import annotations

import re
import unicodedata


def looks_like_autocomplete(element, metadata: dict | None = None) -> bool:
    """Return True for LinkedIn typeahead/combobox fields, including location controls."""
    metadata = metadata or {}
    try:
        if bool(metadata.get("autocompleteLike")):
            return True
        role = str(metadata.get("role") or element.get_attribute("role") or "").lower()
        aria_auto = str(metadata.get("ariaAutocomplete") or element.get_attribute("aria-autocomplete") or "").lower()
        aria_controls = str(
            metadata.get("ariaControls")
            or element.get_attribute("aria-controls")
            or element.get_attribute("aria-owns")
            or ""
        )
        class_name = str(metadata.get("className") or element.get_attribute("class") or "")
        return (
            role == "combobox"
            or bool(aria_auto)
            or bool(aria_controls)
            or any(token in class_name.lower() for token in ("typeahead", "autocomplete", "combobox"))
        )
    except Exception:
        return bool(metadata.get("autocompleteLike"))


def normalize_option_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.replace("\n", " ").strip().lower().split())


def _location_parts(value: str) -> list[str]:
    return [normalize_option_text(part) for part in str(value).split(",") if normalize_option_text(part)]


def _country_key(value: str) -> str:
    text = normalize_option_text(value)
    compact = re.sub(r"[^a-z0-9]", "", text)
    aliases = {
        "ie": "ireland",
        "irl": "ireland",
        "eire": "ireland",
        "republicofireland": "ireland",
        "uk": "unitedkingdom",
        "gb": "unitedkingdom",
        "gbr": "unitedkingdom",
        "greatbritain": "unitedkingdom",
        "unitedkingdom": "unitedkingdom",
        "us": "unitedstates",
        "usa": "unitedstates",
        "unitedstatesofamerica": "unitedstates",
        "unitedstates": "unitedstates",
        "br": "brazil",
        "brasil": "brazil",
        "brazil": "brazil",
        "pt": "portugal",
        "prt": "portugal",
        "portugal": "portugal",
        "es": "spain",
        "esp": "spain",
        "espana": "spain",
        "spain": "spain",
        "fr": "france",
        "fra": "france",
        "france": "france",
        "de": "germany",
        "deu": "germany",
        "deutschland": "germany",
        "germany": "germany",
        "it": "italy",
        "ita": "italy",
        "italia": "italy",
        "italy": "italy",
        "nl": "netherlands",
        "nld": "netherlands",
        "netherlands": "netherlands",
    }
    return aliases.get(compact, compact)



def _known_country_key(value: str) -> str:
    key = _country_key(value)
    known = {
        "ireland", "unitedkingdom", "unitedstates", "brazil", "portugal",
        "spain", "france", "germany", "italy", "netherlands",
    }
    return key if key in known else ""

def autocomplete_score(requested: str, candidate: str, *, location_like: bool = False) -> float:
    """Score a visible autocomplete suggestion against the requested answer.

    For locations, city matches are useful but a known country mismatch is a
    hard rejection. This prevents e.g. a Dublin, Ireland profile from silently
    selecting Dublin, Ohio when LinkedIn happens to render that suggestion first.
    """
    req = normalize_option_text(requested)
    cand = normalize_option_text(candidate)
    if not req or not cand:
        return -1.0

    if location_like:
        req_parts = _location_parts(requested)
        cand_parts = _location_parts(candidate)
        # When both strings provide more than the city, their last component is
        # normally the country in LinkedIn's location suggestions. Reject a
        # conflicting country instead of trusting token overlap on the city name.
        if len(req_parts) >= 2 and len(cand_parts) >= 2:
            req_country = _country_key(req_parts[-1])
            cand_country = _country_key(cand_parts[-1])
            if req_country and cand_country and req_country != cand_country:
                return -500.0

    if req == cand:
        return 1000.0
    if cand.startswith(req):
        return 900.0
    if req.startswith(cand) and len(cand) >= 4:
        return 850.0
    if req in cand:
        return 800.0
    if cand in req and len(cand) >= 4:
        return 760.0

    req_tokens = {
        t.strip(" ,.;()[]")
        for t in req.replace(",", " ").split()
        if len(t.strip(" ,.;()[]")) >= 2
    }
    cand_tokens = {
        t.strip(" ,.;()[]")
        for t in cand.replace(",", " ").split()
        if len(t.strip(" ,.;()[]")) >= 2
    }
    if not req_tokens or not cand_tokens:
        return -1.0
    overlap = len(req_tokens & cand_tokens)
    if not overlap:
        return -1.0
    score = 100.0 * overlap / max(1, len(req_tokens))
    if location_like:
        req_parts = _location_parts(requested)
        cand_parts = _location_parts(candidate)
        city = req_parts[0] if req_parts else ""
        cand_city = cand_parts[0] if cand_parts else cand
        if city and city == cand_city:
            score += 300.0
        elif city and city in cand:
            score += 150.0
        if len(req_parts) >= 2 and len(cand_parts) >= 2 and _country_key(req_parts[-1]) == _country_key(cand_parts[-1]):
            score += 250.0
        if "," in candidate:
            score += 20.0
    return score


def best_autocomplete_index(requested: str, candidates: list[str], *, location_like: bool = False) -> int | None:
    """Return the safest best candidate index, or None when no candidate relates enough."""
    if not candidates:
        return None
    scores = [autocomplete_score(requested, candidate, location_like=location_like) for candidate in candidates]
    best_index = max(range(len(scores)), key=scores.__getitem__)
    best_score = scores[best_index]
    # Never select a completely unrelated sole option. Custom LinkedIn dropdowns
    # can coexist on the page and the first visible listbox is not always ours.
    return best_index if best_score >= 50.0 else None


def _detect_known_country(value: str) -> str:
    """Find a known country token inside a human-readable location string."""
    text = normalize_option_text(value)
    # Prefer comma-separated components because LinkedIn commonly renders
    # "City, Region, Country", but also handle strings such as "Ireland (Remote)".
    for part in reversed(_location_parts(value)):
        key = _known_country_key(part)
        if key:
            return key
    aliases = {
        "ireland": ("ireland", "eire", "republic of ireland"),
        "unitedkingdom": ("united kingdom", "great britain", " uk "),
        "unitedstates": ("united states", "united states of america", " usa "),
        "brazil": ("brazil", "brasil"),
        "portugal": ("portugal",),
        "spain": ("spain", "espana"),
        "france": ("france",),
        "germany": ("germany", "deutschland"),
        "italy": ("italy", "italia"),
        "netherlands": ("netherlands",),
    }
    padded = f" {text} "
    for key, names in aliases.items():
        if any(name in padded for name in names):
            return key
    return ""


def classify_location_match(requested: str, candidate: str) -> str:
    """Classify a post-search job location without over-filtering LinkedIn results.

    Returns one of: ``match``, ``compatible``, ``unknown`` or ``conflict``.

    The search URL remains the primary location filter. The post-search guard is
    deliberately fail-open for missing/ambiguous metadata and fail-closed only
    for a *verified* conflict such as Dublin/Ireland vs Lisbon/Portugal. This
    prevents current LinkedIn UI variants that hide job-location metadata from
    causing every legitimate Dublin result to be skipped.
    """
    req = normalize_option_text(requested)
    cand = normalize_option_text(candidate)
    if not req:
        return "compatible"
    if not cand:
        return "unknown"

    if req in {"remote", "worldwide", "anywhere"}:
        if any(token in cand for token in ("remote", "worldwide", "anywhere")):
            return "match"
        return "unknown"

    req_parts = _location_parts(requested)
    cand_parts = _location_parts(candidate)
    if not req_parts:
        return "unknown"

    req_city = req_parts[0]
    req_country = _detect_known_country(requested)
    cand_country = _detect_known_country(candidate)

    # A known country contradiction is the strongest safe negative signal.
    if req_country and cand_country and req_country != cand_country:
        return "conflict"

    # Exact city/county/region mentions are good enough even when LinkedIn omits
    # part of the configured location (e.g. "County Dublin, Ireland").
    if req_city and req_city in cand:
        return "match"

    # Country-only results such as "Ireland" or "Ireland (Remote)" are broader
    # than the requested city but not contradictory; allow them.
    if req_country and cand_country == req_country:
        if len(cand_parts) <= 1:
            return "compatible"
        first = cand_parts[0]
        generic = any(token in first for token in ("remote", "hybrid", "countrywide", "nationwide"))
        if generic:
            return "compatible"
        # A clearly city-specific same-country result with a different city is a
        # verified mismatch (e.g. Cork, Ireland for a Dublin search).
        if len(cand_parts) >= 2 and first and req_city not in first:
            return "conflict"
        return "compatible"

    # No reliable country/city metadata: trust LinkedIn's search scope instead of
    # dropping a potentially valid job.
    return "unknown"


def location_matches_requested(requested: str, candidate: str) -> bool:
    """Backward-compatible boolean helper: reject only verified conflicts."""
    return classify_location_match(requested, candidate) != "conflict"


def should_block_location(requested: str, candidate: str, confidence: str = "high") -> bool:
    """Return True only for a verified, high-confidence location conflict.

    LinkedIn's own search location remains the primary filter. Post-search
    extraction is intentionally fail-open unless the current job exposes a
    dedicated/structured location source with high confidence and that value
    contradicts the configured search.
    """
    return str(confidence or "").lower() == "high" and classify_location_match(requested, candidate) == "conflict"


def sanitize_location_evidence(
    candidate: str,
    *,
    title: str = "",
    company: str = "",
    source: str = "",
    confidence: str = "",
) -> tuple[str, str]:
    """Downgrade location evidence that is actually title/company/prose.

    LinkedIn UI experiments occasionally place non-location strings in elements
    whose class names contain ``location``. These values are still useful for
    diagnostics but must never become hard negative evidence.
    """
    level = str(confidence or "").strip().lower()
    origin = str(source or "").strip()
    if not candidate or level != "high":
        return origin, level
    folded_location = normalize_option_text(candidate)
    folded_title = normalize_option_text(title)
    folded_company = normalize_option_text(company)
    prose_markers = (
        "with offices", "offices in", "company based", "we are based",
        "our office", "we support", "international clients",
    )
    def starts_with_entity(text: str, entity: str) -> bool:
        if not entity or len(entity) < 4 or not text.startswith(entity):
            return False
        if len(text) == len(entity):
            return True
        return text[len(entity)] in " ,;:-–—|("

    looks_like_title = starts_with_entity(folded_location, folded_title)
    looks_like_company = starts_with_entity(folded_location, folded_company)
    looks_like_prose = any(marker in folded_location for marker in prose_markers) or len(candidate.split()) > 12
    if looks_like_title or looks_like_company or looks_like_prose:
        return f"{origin or 'unknown'}-suspect-content", "medium"
    return origin, level
