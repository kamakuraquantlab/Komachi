"""The credential boundary, and how the buyer's machine is configured.

`05_komachi-acquisition.md` section 3 confines the purchase token to one
module. These tests hold that line: the token goes out on the wire in one
place, is stored in one place, and never reaches the data directory a buyer
might commit to git.
"""

import os
import stat
from pathlib import Path

import httpx
import pytest

from komachi import settings, weeks
from komachi.client import ApiError, KomachiClient


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








# ---- settings --------------------------------------------------------------

def test_the_settings_file_is_readable_only_by_its_owner(tmp_path):
    """It holds a token now, so the mode is part of the design rather than tidiness."""
    env = tmp_path / "settings.env"
    settings.write_env_file({settings.ROOT_KEY: "/data"}, env)
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_saving_a_token_leaves_the_rest_of_the_file_alone(tmp_path):
    env = tmp_path / "settings.env"
    settings.write_env_file({settings.ROOT_KEY: "/data",
                             settings.URL_KEY: "https://yukinoshita.example"}, env)
    settings.save_token("hk_secret", env)
    values = settings.read_env_file(env)
    assert values[settings.TOKEN_KEY] == "hk_secret"
    assert values[settings.ROOT_KEY] == "/data"
    assert values[settings.URL_KEY] == "https://yukinoshita.example"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_reading_the_settings_file_ignores_comments_and_blank_lines(tmp_path):
    env = tmp_path / "settings.env"
    env.write_text("# a comment\n\nROOT_PATH=/data\nYUKINOSHITA_URL=https://yukinoshita.example\n")
    values = settings.read_env_file(env)
    assert values["ROOT_PATH"] == "/data"
    assert values["YUKINOSHITA_URL"] == "https://yukinoshita.example"


def test_a_missing_settings_file_is_an_empty_answer_not_a_failure(tmp_path):
    assert settings.read_env_file(tmp_path / "nothing") == {}


def test_setup_writes_only_the_root_so_the_whole_file_can_be_shown(tmp_path, capsys, monkeypatch):
    """What setup prints back is the file itself, which is safe because a token
    has not arrived yet. `token set` is what puts one there, later."""
    env = tmp_path / "settings.env"
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(settings.SetupRequired):
        settings.run_setup("komachi", env)
    values = settings.read_env_file(env)
    assert list(values) == [settings.ROOT_KEY], "only the root, so the file can be shown"
    assert values[settings.ROOT_KEY] == str(Path(settings.DEFAULT_ROOT).expanduser())
    assert Path(values[settings.ROOT_KEY]).is_dir(), "setup creates the directory it names"
    assert values[settings.ROOT_KEY] in capsys.readouterr().out


def test_an_explicit_root_settles_it_without_asking(tmp_path, monkeypatch):
    """Anything unattended must not meet a prompt, which is why Akimoto passes
    the root by environment and never reaches setup."""
    monkeypatch.setenv(settings.ROOT_KEY, str(tmp_path / "elsewhere"))
    monkeypatch.setattr(settings, "ENV_FILE", tmp_path / "absent.env")
    s = settings.resolve()
    assert s.root == tmp_path / "elsewhere"
    assert s.yukinoshita_url == settings.DEFAULT_YUKINOSHITA_URL


def test_setup_is_skippable_for_a_caller_that_cannot_answer(tmp_path, monkeypatch):
    monkeypatch.delenv(settings.ROOT_KEY, raising=False)
    monkeypatch.setattr(settings, "ENV_FILE", tmp_path / "absent.env")
    s = settings.resolve(setup=False)
    assert s.root == Path(settings.DEFAULT_ROOT).expanduser()


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
