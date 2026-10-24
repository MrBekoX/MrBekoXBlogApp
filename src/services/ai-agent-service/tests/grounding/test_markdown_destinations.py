"""URL gates operate on rendered destinations, independently of model verdicts."""

import json

import pytest

from agent_core.grounding import GroundingEvidence, _links_allowed, _parse_verdict, split_answer

SOURCE = "The approved guide describes bounded queues and memory use."


@pytest.mark.parametrize("answer", [
    "[Guide](https://invented.invalid/pay)",
    "[Guide][r]\n\n[r]: https&colon;//invented.invalid/pay",
    "[Guide][r]\n\n[r]: /unapproved",
    "[Guide](https&#58;//invented.invalid/pay)",
    "<https&colon;//invented.invalid/pay>",
    "[Guide](/admin)",  # external /admin never grants local /admin
    "[Guide](https://vendor.example/admin/)",
    "[Guide](https://vendor.example/Admin)",
    "[Guide](https://vendor.example/admin?key=VALUE)",
    "[Guide](https://vendor.example/admin&NewLine;.invented)",
])
def test_unapproved_reference_entity_relative_and_changed_destinations_are_rejected(answer):
    evidence = [GroundingEvidence("S1", SOURCE, ("https://vendor.example/admin", "https://vendor.example/admin?key=value"))]
    assert not _links_allowed(answer, evidence)


@pytest.mark.parametrize("answer", [
    "[Guide](https://vendor.example/admin)",
    "[Guide][r]\n\n[r]: https&colon;//vendor.example/admin",
    "[Guide](https&#58;//vendor.example/admin)",
    "<https://vendor.example/admin>",
    "Read https://vendor.example/admin.",
    "[Guide](HTTPS://VENDOR.EXAMPLE/admin)",
    "[Guide](/about#education)",
    "[Guide][r]\n\n[r]: /about#education",
])
def test_approved_exact_inline_reference_autolink_and_profile_relative_targets_are_kept(answer):
    assert _links_allowed(answer, [GroundingEvidence("S1", SOURCE,
        ("https://vendor.example/admin", "/about#education"))])


def test_balanced_parenthesis_destination_is_checked_in_full_not_as_approved_prefix():
    assert not _links_allowed("[Guide](https://vendor.example/path(foo)/unapproved)",
        [GroundingEvidence("S1", SOURCE, ("https://vendor.example/path(foo",))])
    assert _links_allowed("[Guide](https://vendor.example/path(foo))",
        [GroundingEvidence("S1", SOURCE, ("https://vendor.example/path(foo)",))])


def test_literal_source_code_urls_are_not_treated_as_new_navigation_targets():
    code = "```python\n# Approved literal source example\nurl = 'https&colon;//vendor.example/admin/'\n```"
    verdict = {"segments": [{"id": "A1", "supported": True,
        "evidence": [{"source": "S1", "quote": "Approved literal source example"}]}]}
    result = _parse_verdict(json.dumps(verdict), split_answer(code), [GroundingEvidence("S1", code)])
    assert result.answer == code


def test_approved_multiline_reference_definition_survives_segment_verification():
    answer = "[r]:\n  /about#education"
    assert len(split_answer(answer)) == 1
    raw = {"segments": [{"id": "A1", "supported": True,
        "evidence": [{"source": "S1", "quote": SOURCE}]}]}
    result = _parse_verdict(json.dumps(raw), split_answer(answer),
                           [GroundingEvidence("S1", SOURCE, ("/about#education",))])
    assert result.answer == answer


@pytest.mark.parametrize("answer", ["[Guide](https&#58;//vendor.example/posts/123)",
    "[r]: https&colon;//vendor.example/posts/123", "[123]: https://vendor.example/posts/123"])
def test_approved_link_markup_numbers_are_not_mistaken_for_factual_claims(answer):
    raw = {"segments": [{"id": "A1", "supported": True,
        "evidence": [{"source": "S1", "quote": SOURCE}]}]}
    result = _parse_verdict(json.dumps(raw), split_answer(answer),
        [GroundingEvidence("S1", SOURCE, ("https://vendor.example/posts/123",))])
    assert result.answer == answer


def test_encoded_factual_number_is_still_checked_against_evidence():
    answer = "The recommended queue size is &#57;&#48;&#48;&#48;."
    source = "The recommended queue size is 1000."
    raw = {"segments": [{"id": "A1", "supported": True,
        "evidence": [{"source": "S1", "quote": source}]}]}
    assert not _parse_verdict(json.dumps(raw), split_answer(answer), [GroundingEvidence("S1", source)]).answer
