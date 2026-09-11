from linkedin_easy_apply.autocomplete import (
    autocomplete_score, best_autocomplete_index, classify_location_match,
    looks_like_autocomplete, location_matches_requested, sanitize_location_evidence,
)


class FakeElement:
    def __init__(self, attrs=None):
        self.attrs = attrs or {}

    def get_attribute(self, name):
        return self.attrs.get(name, "")


def test_combobox_and_typeahead_are_detected():
    assert looks_like_autocomplete(FakeElement({"role": "combobox"}))
    assert looks_like_autocomplete(FakeElement({"aria-autocomplete": "list"}))
    assert looks_like_autocomplete(FakeElement({"class": "jobs-location-typeahead"}))
    assert not looks_like_autocomplete(FakeElement({"type": "text"}))


def test_location_autocomplete_prefers_complete_matching_location():
    requested = "Dublin, County Dublin, Ireland"
    exact = autocomplete_score(requested, "Dublin, County Dublin, Ireland", location_like=True)
    partial = autocomplete_score(requested, "Dublin, Ireland", location_like=True)
    wrong = autocomplete_score(requested, "Dublin, Ohio, United States", location_like=True)
    assert exact > partial > wrong


def test_best_location_suggestion_does_not_pick_wrong_dublin():
    candidates = [
        "Dublin, Ohio, United States",
        "Dublin, County Dublin, Ireland",
        "Dublin, Georgia, United States",
    ]
    assert best_autocomplete_index("Dublin, County Dublin, Ireland", candidates, location_like=True) == 1


def test_location_country_mismatch_is_rejected():
    assert autocomplete_score(
        "Dublin, County Dublin, Ireland",
        "Dublin, Ohio, United States",
        location_like=True,
    ) < 0
    assert best_autocomplete_index(
        "Dublin, County Dublin, Ireland",
        ["Dublin, Ohio, United States"],
        location_like=True,
    ) is None


def test_location_matching_ignores_accents_safely():
    idx = best_autocomplete_index(
        "Santos, São Paulo, Brazil",
        ["Santos, Sao Paulo, Brazil", "Santos, Florida, United States"],
        location_like=True,
    )
    assert idx == 0


def test_strict_location_guard_rejects_portugal_for_dublin_search():
    assert location_matches_requested("Dublin, County Dublin, Ireland", "Dublin, Ireland")
    assert location_matches_requested("Dublin, County Dublin, Ireland", "County Dublin, Ireland")
    assert not location_matches_requested("Dublin, County Dublin, Ireland", "Lisbon, Portugal")
    assert not location_matches_requested("Dublin, County Dublin, Ireland", "Portugal")


def test_location_guard_allows_unverifiable_metadata_instead_of_dropping_valid_jobs():
    assert classify_location_match("Dublin, County Dublin, Ireland", "") == "unknown"
    assert location_matches_requested("Dublin, County Dublin, Ireland", "")


def test_location_guard_distinguishes_match_compatible_and_verified_conflict():
    assert classify_location_match("Dublin, County Dublin, Ireland", "Dublin, Ireland") == "match"
    assert classify_location_match("Dublin, County Dublin, Ireland", "Ireland") == "compatible"
    assert classify_location_match("Dublin, County Dublin, Ireland", "Lisbon, Portugal") == "conflict"
    assert classify_location_match("Dublin, County Dublin, Ireland", "Cork, County Cork, Ireland") == "conflict"


def test_location_guard_blocks_only_high_confidence_conflicts():
    from linkedin_easy_apply.autocomplete import should_block_location
    requested = "Dublin, County Dublin, Ireland"
    assert should_block_location(requested, "Lisbon, Portugal", "high") is True
    assert should_block_location(requested, "Lisbon, Portugal", "medium") is False
    assert should_block_location(requested, "Web Developer, Ireland", "medium") is False
    assert should_block_location(requested, "", "") is False



def test_suspicious_location_evidence_is_downgraded_before_filtering():
    source, confidence = sanitize_location_evidence(
        "Web Developer, Ireland",
        title="Web Developer",
        source="[data-test-job-location]",
        confidence="high",
    )
    assert confidence == "medium"
    assert source.endswith("suspect-content")
    assert should_not_block_after_downgrade("Dublin, County Dublin, Ireland", "Web Developer, Ireland", confidence)

    source2, confidence2 = sanitize_location_evidence(
        "With offices in Switzerland, Singapore, Hong Kong and France, we support our Swiss and international clients",
        source="[data-testid=job-location]",
        confidence="high",
    )
    assert confidence2 == "medium"
    assert source2.endswith("suspect-content")

    source3, confidence3 = sanitize_location_evidence(
        "Lisbon, Portugal", source="jsonld-jobLocation", confidence="high"
    )
    assert (source3, confidence3) == ("jsonld-jobLocation", "high")


def should_not_block_after_downgrade(requested, candidate, confidence):
    from linkedin_easy_apply.autocomplete import should_block_location
    return not should_block_location(requested, candidate, confidence)
