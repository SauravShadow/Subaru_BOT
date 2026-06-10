"""Tests for CEO delegation-tag parsing — directives vs. inline mentions."""
from app.graph.nodes.ceo import parse_delegations_from_response


def test_real_directive_at_line_start_parses():
    text = "On it — let's get this moving.\n[DELEGATE:browser] Find FastAPI backend roles on LinkedIn in Bangalore and apply."
    result = parse_delegations_from_response(text)
    assert result == [{"agent": "browser", "task": "Find FastAPI backend roles on LinkedIn in Bangalore and apply."}]


def test_inline_mention_does_not_parse_as_directive():
    text = "Say the word and I'll get [DELEGATE:browser] Maya moving on it right away."
    result = parse_delegations_from_response(text)
    assert result == []


def test_multiple_real_directives_parse_independently():
    text = (
        "Kicking off two things.\n"
        "[DELEGATE:backend] Build a REST endpoint for user search.\n"
        "[DELEGATE:browser] Apply to the Stripe backend role at https://stripe.com/jobs/123."
    )
    result = parse_delegations_from_response(text)
    assert result == [
        {"agent": "backend", "task": "Build a REST endpoint for user search."},
        {"agent": "browser", "task": "Apply to the Stripe backend role at https://stripe.com/jobs/123."},
    ]


def test_directive_followed_by_trailing_prose_stops_at_next_tag():
    text = (
        "[DELEGATE:browser] Search for Stripe roles and apply.\n"
        "[EMAIL_USER:Heads up] Just letting you know I kicked this off."
    )
    result = parse_delegations_from_response(text)
    assert result == [{"agent": "browser", "task": "Search for Stripe roles and apply."}]


def test_clean_delegations_output_has_no_delegate_tags():
    text = (
        "Sure thing.\n"
        "[DELEGATE:browser] Find backend roles and apply.\n"
        "I will let you know."
    )
    result = parse_delegations_from_response(text)
    assert len(result) == 1
    assert result[0]["agent"] == "browser"


def test_stray_mid_sentence_tag_ignored():
    text = "Say the word and I will get [DELEGATE:browser] Maya moving on it right away."
    result = parse_delegations_from_response(text)
    assert result == []


def test_multiple_directives_and_stray_mention():
    text = (
        "Say the word and I will get [DELEGATE:browser] Maya moving on it right away.\n"
        "[DELEGATE:backend] Build a REST endpoint for user search.\n"
        "Thanks!"
    )
    result = parse_delegations_from_response(text)
    assert len(result) == 1
    assert result[0]["agent"] == "backend"
    assert "Build a REST endpoint" in result[0]["task"]
