"""Tests for CEO delegation-tag parsing — directives vs. inline mentions."""
from app.services.delegation import parse_delegations


def test_real_directive_at_line_start_parses():
    text = "On it — let's get this moving.\n[DELEGATE:browser] Find FastAPI backend roles on LinkedIn in Bangalore and apply."
    result = parse_delegations(text)
    assert result == [("browser", "Find FastAPI backend roles on LinkedIn in Bangalore and apply.")]


def test_inline_mention_does_not_parse_as_directive():
    text = "Say the word and I'll get [DELEGATE:browser] Maya moving on it right away."
    result = parse_delegations(text)
    assert result == []


def test_multiple_real_directives_parse_independently():
    text = (
        "Kicking off two things.\n"
        "[DELEGATE:backend] Build a REST endpoint for user search.\n"
        "[DELEGATE:browser] Apply to the Stripe backend role at https://stripe.com/jobs/123."
    )
    result = parse_delegations(text)
    assert result == [
        ("backend", "Build a REST endpoint for user search."),
        ("browser", "Apply to the Stripe backend role at https://stripe.com/jobs/123."),
    ]


def test_directive_followed_by_trailing_prose_stops_at_next_tag():
    text = (
        "[DELEGATE:browser] Search for Stripe roles and apply.\n"
        "[EMAIL_USER:Heads up] Just letting you know I kicked this off."
    )
    result = parse_delegations(text)
    assert result == [("browser", "Search for Stripe roles and apply.")]
