"""TagRegistry — maps tag names to handler modules.
To add a new output capability: create handlers/mytag.py and add one entry here.
"""

_registry: dict | None = None


def get_registry() -> dict:
    global _registry
    if _registry is None:
        from app.output.handlers import (
            speak, sing, image, email as email_handler,
            browser_apply, browser_discover, browser_company, browser_profile_match,
        )
        _registry = {
            "SPEAK":                 speak,
            "SING":                  sing,
            "GENERATE_IMAGE":        image,
            "EMAIL_USER":            email_handler,
            "BROWSER_APPLY":         browser_apply,
            "BROWSER_DISCOVER":      browser_discover,
            "BROWSER_COMPANY":       browser_company,
            "BROWSER_PROFILE_MATCH": browser_profile_match,
        }
    return _registry


# Alias used in tests via patch.dict("app.output.registry.REGISTRY", ...)
REGISTRY: dict = {}
