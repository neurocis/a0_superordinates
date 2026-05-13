import sys

sys.path.insert(0, "/a0")

from usr.plugins.a0_superordinates.helpers.routing_matcher import (
    build_ambiguity_prompt,
    decide_route,
    normalize_text,
    score_name_match,
)


def candidates():
    return [
        {"ctxid": "a0", "name": "A0", "role": "Default owner and fallback coordinator"},
        {"ctxid": "cal", "name": "Calendar Dev", "role": "Calendar integration and scheduling specialist"},
        {"ctxid": "hist", "name": "History Dev", "role": "History timeline and archival specialist"},
        {"ctxid": "hero", "name": "Hero Mode", "role": "Hero routing and UI behavior specialist"},
    ]


def name_only_candidates():
    return [
        {"ctxid": "a0", "name": "A0", "role": "Default owner and fallback coordinator"},
        {"ctxid": "cal", "name": "Calendar Dev", "role": ""},
        {"ctxid": "hist", "name": "History Dev", "role": ""},
        {"ctxid": "hero", "name": "Hero Mode", "role": ""},
    ]


def test_normalize_text_is_case_punctuation_spacing_tolerant():
    assert normalize_text("Hero-Mode!!") == "hero mode"
    assert normalize_text("  HERO___mode  ") == "hero mode"


def test_exact_name_match_routes_with_highest_priority():
    decision = decide_route("Hero Mode", name_only_candidates())
    assert decision.action == "route"
    assert decision.selected["ctxid"] == "hero"
    assert decision.match_type == "exact_name"
    assert decision.confidence == 1.0


def test_token_partial_name_match_routes_when_clear():
    decision = decide_route("calendar", name_only_candidates())
    assert decision.action == "route"
    assert decision.selected["ctxid"] == "cal"
    assert decision.match_type == "token_name"


def test_substring_name_match_is_scored_below_token_match():
    match = score_name_match("story", {"ctxid": "hist", "name": "History Dev"})
    assert match is not None
    assert match.match_type == "substring_name"
    assert match.score < 0.86


def test_skill_match_takes_priority_over_name_fallback():
    decision = decide_route("scheduling", candidates())
    assert decision.action == "route"
    assert decision.selected["ctxid"] == "cal"
    assert decision.match_type == "skill"


def test_ambiguous_close_name_matches_ask_for_disambiguation():
    ambiguous = [
        {"ctxid": "a0", "name": "A0"},
        {"ctxid": "cal", "name": "Calendar Dev"},
        {"ctxid": "calc", "name": "Calculator Dev"},
    ]
    decision = decide_route("cal", ambiguous)
    assert decision.action == "disambiguate"
    assert decision.selected is None
    assert "won't auto-route" in decision.prompt
    assert "Calendar Dev" in decision.prompt
    assert "Calculator Dev" in decision.prompt


def test_no_match_falls_back_to_default_owner_a0():
    decision = decide_route("nonexistent plasma wrench", candidates())
    assert decision.action == "fallback"
    assert decision.selected["ctxid"] == "a0"
    assert decision.match_type == "default_owner"


def test_no_match_guidance_when_default_owner_unavailable():
    decision = decide_route("nonexistent plasma wrench", [{"ctxid": "x", "name": "Other"}])
    assert decision.action == "no_match"
    assert decision.selected is None
    assert "No confident" in decision.reason
