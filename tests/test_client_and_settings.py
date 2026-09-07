"""The credential boundary, and how the buyer's machine is configured.

`05_komachi-acquisition.md` section 3 confines the purchase token to one
module. These tests hold that line: the token goes out on the wire in one
place, is stored in one place, and never reaches the data directory a buyer
might commit to git.
"""

import json
import os
import stat

import httpx
import pytest

from komachi import settings, weeks
from komachi.client import ApiError, Credentials, KomachiClient


# ---- the client ------------------------------------------------------------

def _client(handler, token="hk_test"):
    c = KomachiClient("https://api.example", token)
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_the_token_is_sent_as_a_bearer_and_nothing_else_is():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    _client(handler).status()
    assert seen["auth"] == "Bearer hk_test"


def test_an_api_error_carries_the_status_and_the_detail():
    def handler(request):
        return httpx.Response(402, json={"detail": "Allowance exhausted."})

    with pytest.raises(ApiError) as exc:
        _client(handler).status()
    assert exc.value.status_code == 402
    assert "Allowance exhausted" in str(exc.value)


def test_a_body_that_is_not_json_still_produces_a_usable_error():
    """A proxy or a gateway can answer with HTML, and the buyer still needs a
    message rather than a traceback about decoding."""
    def handler(request):
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    with pytest.raises(ApiError) as exc:
        _client(handler).status()
    assert exc.value.status_code == 502


def test_the_download_link_is_built_from_the_configured_api():
    c = KomachiClient("https://api.example", "hk_test")
    assert c.download_link("GMO:BTC_JPY", "2026-01-15", "Trade") == (
        "https://api.example/api/download/GMO:BTC_JPY/2026-01-15/Trade")
    assert c.auth_header() == {"Authorization": "Bearer hk_test"}


def test_credentials_are_written_private_to_the_user(tmp_path):
    path = tmp_path / "config.json"
    Credentials("https://api.example", "hk_secret").save(path)
    assert json.loads(path.read_text())["token"] == "hk_secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_loading_credentials_that_are_not_there_is_not_an_error(tmp_path):
    assert Credentials.load(tmp_path / "missing.json") is None


def test_credentials_round_trip(tmp_path):
    path = tmp_path / "config.json"
    Credentials("https://api.example", "hk_secret").save(path)
    loaded = Credentials.load(path)
    assert (loaded.api_url, loaded.token) == ("https://api.example", "hk_secret")


# ---- settings --------------------------------------------------------------

def test_the_env_file_holds_the_root_and_the_api_but_never_the_token(tmp_path):
    """A data directory can be committed to git; a token cannot."""
    env = tmp_path / ".env"
    settings.write_env_file(tmp_path / "data", "https://api.example", env)
    text = env.read_text()
    assert settings.ROOT_KEY in text
    assert "hk_" not in text                       # no token value
    assert str(settings.TOKEN_FILE) in text        # but it says where one lives


def test_reading_an_env_file_ignores_comments_and_blank_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# a comment\n\nKQL_ROOT_PATH=/data\nKQL_API_URL=https://api.example\n")
    values = settings.load_env_file(env)
    assert values["KQL_ROOT_PATH"] == "/data"
    assert values["KQL_API_URL"] == "https://api.example"


def test_a_missing_env_file_is_an_empty_answer_not_a_failure(tmp_path):
    assert settings.load_env_file(tmp_path / "nothing") == {}


# ---- weeks -----------------------------------------------------------------

def test_an_allowance_is_described_the_way_the_storefront_sells_it():
    assert weeks.describe(7) == "1 market-week"
    assert weeks.describe(28) == "4 market-weeks"
    assert weeks.describe(0) == "none"


def test_a_part_week_says_so_rather_than_rounding():
    """A buyer with 30 days has four weeks and two days, not four weeks."""
    assert weeks.describe(30) == "4 market-weeks and 2 days"
    assert weeks.describe(1) == "1 market-day"
    assert weeks.describe(5) == "5 market-days"


def test_the_shapes_offered_divide_evenly():
    """Every shape suggested must be spendable exactly, or the copy is a lie."""
    for allowance in (28, 84, 364):
        for shape in weeks.shapes(allowance):
            assert "week" in shape
        assert weeks.shapes(allowance)[0].startswith(str(allowance // 7))
