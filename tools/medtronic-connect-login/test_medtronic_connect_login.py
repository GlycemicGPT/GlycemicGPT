"""Unit tests for the pure helpers of the Medtronic Connect login CLI.

The browser + network steps are exercised manually / in the live E2E gate;
here we cover the redirect-capture predicate, URL building, and arg parsing.

Run standalone (the tool is outside the apps/api test suite):
    uv run --with pytest pytest tools/medtronic-connect-login/test_medtronic_connect_login.py
"""

import importlib.util
import pathlib

import pytest

_MOD_PATH = pathlib.Path(__file__).with_name("medtronic_connect_login.py")
_spec = importlib.util.spec_from_file_location("mcl", _MOD_PATH)
mcl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcl)


def test_build_url_strips_trailing_slash():
    assert mcl.build_url("https://x.test/", "/a/b") == "https://x.test/a/b"
    assert mcl.build_url("https://x.test", "/a/b") == "https://x.test/a/b"


def test_is_capture_redirect_matches_carepartner_code():
    assert mcl.is_capture_redirect(
        302, "com.medtronic.carepartner:/sso?code=abc&state=xyz"
    )


def test_is_capture_redirect_rejects_non_redirect_status():
    assert not mcl.is_capture_redirect(200, "com.medtronic.carepartner:/sso?code=abc")


def test_is_capture_redirect_rejects_other_schemes_and_missing_code():
    assert not mcl.is_capture_redirect(
        302, "https://carelink-login.minimed.com/u/login"
    )
    assert not mcl.is_capture_redirect(
        302, "com.medtronic.carepartner:/sso?error=denied"
    )
    assert not mcl.is_capture_redirect(302, None)


def test_parse_args_requires_core_flags():
    args = mcl.parse_args(
        ["--api", "https://x.test", "--pair", "tok", "--username", "u"]
    )
    assert args.api == "https://x.test"
    assert args.pair == "tok"
    assert args.username == "u"
    assert args.region == "US"
    assert args.timeout == 300
    assert args.headless is False


def test_parse_args_missing_required_exits():
    with pytest.raises(SystemExit):
        mcl.parse_args(["--api", "https://x.test"])  # no --pair/--username
