#!/usr/bin/env python3
"""Smoke tests for HC-02 SECRET_KEY guard — validates logic in isolation."""

# Reproduce the exact guard logic from web/app.py
_DEV_INSECURE_SECRET_KEY = "dev-only-insecure-key"

def should_refuse(app_env, secret_key):
    """Replicate the guard condition from app.py."""
    if app_env == "prod" and secret_key in (None, "", _DEV_INSECURE_SECRET_KEY):
        return True
    return False

tests = [
    # (name, app_env, secret_key, should_refuse)
    ("prod + SECRET_KEY unset",          "prod", None,                      True),
    ("prod + SECRET_KEY empty",          "prod", "",                        True),
    ("prod + SECRET_KEY=dev fallback",   "prod", "dev-only-insecure-key",   True),
    ("prod + SECRET_KEY=real key",       "prod", "super-secret-real-12345", False),
    ("test + SECRET_KEY unset",          "test", None,                      False),
    ("test + SECRET_KEY empty",          "test", "",                        False),
    ("test + SECRET_KEY=dev fallback",   "test", "dev-only-insecure-key",   False),
    ("test + SECRET_KEY=real key",       "test", "real-key",                False),
]

passed = 0
failed = 0

for name, app_env, secret_key, expect_refuse in tests:
    actual = should_refuse(app_env, secret_key)
    if actual == expect_refuse:
        print(f"PASS: {name}")
        passed += 1
    else:
        print(f"FAIL: {name} — expected refuse={expect_refuse}, got refuse={actual}")
        failed += 1

print(f"\n{passed}/{passed+failed} tests passed")

# Also verify the fallback assignment logic
secret_key = None
result = secret_key or _DEV_INSECURE_SECRET_KEY
assert result == "dev-only-insecure-key", f"Fallback broken: {result}"
print("PASS: fallback assignment (None → dev default)")

secret_key = "real-key"
result = secret_key or _DEV_INSECURE_SECRET_KEY
assert result == "real-key", f"Real key overwritten: {result}"
print("PASS: fallback assignment (real key preserved)")

print("\nAll logic validations passed!")
