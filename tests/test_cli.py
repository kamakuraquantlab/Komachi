"""The argument parser, and what the tool prints about policy it was given."""

import argparse

def test_every_subcommand_resolves_to_a_handler():
    """Guards against a handler being renamed or removed out from under the parser.

    Nothing else in the suite builds the parser, so a subcommand pointing at a
    function that no longer exists stayed invisible until the CLI was run.
    """
    import cli

    parser = cli.build_parser()
    actions = [a for a in parser._subparsers._group_actions if hasattr(a, "choices")]
    seen = 0
    for action in actions:
        for name, sub in action.choices.items():
            func = sub.get_default("func")
            if func is None:      # a group like `auth`, whose children carry the handlers
                continue
            assert callable(func), f"{name} resolves to {func!r}"
            seen += 1
    assert seen >= 10


# ---- the tool displays policy, it does not hold it ---------------------------
#
# `05_komachi-acquisition.md` section 1.1. Komachi is installed on buyers'
# machines and cannot be recalled, so every deadline and every policy sentence
# has to come down the wire. These tests hold that line from the client side:
# what the API says is what is printed, and nothing is worked out locally.


def _status_cli(monkeypatch, state):
    """Run a command against a canned /api/me, with no network and no config."""
    import cli
    from komachi.client import KomachiClient

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def status(self):
            return state

    monkeypatch.setattr(cli, "KomachiClient", FakeClient)
    monkeypatch.setattr(cli, "_client", lambda args: FakeClient())
    return cli


BASE = {
    "product_id": "starter-4w",
    "token_status": "active",
    "granted_market_days": 28,
    "remaining_market_days": 28,
    "markets": ["COINCHECK:BTC_SPOT"],
    "start_date": None,
    "end_date": None,
}


def test_status_prints_the_policy_sentence_it_was_given(monkeypatch, capsys):
    """Verbatim. A rephrasing shipped to a buyer cannot be corrected later."""
    sentence = "Active until 2026-09-25. Nothing to renew."
    cli = _status_cli(monkeypatch, {**BASE, "timing": {
        "access_state": "active",
        "activated_at": "2026-09-11T10:00:00+00:00",
        "active_until": "2026-09-25T10:00:00+00:00",
        "redeem_by": "2026-12-10T10:00:00+00:00",
        "policy": sentence,
    }})

    cli.cmd_token_status(argparse.Namespace())
    out = capsys.readouterr().out

    assert sentence in out
    assert "Access until   2026-09-25T10:00:00+00:00" in out
    assert "access" in out.lower()


def test_status_shows_the_purchase_deadline_before_first_use(monkeypatch, capsys):
    """The two deadlines answer different questions, and only one applies."""
    cli = _status_cli(monkeypatch, {**BASE, "timing": {
        "access_state": "redeemable",
        "activated_at": None,
        "active_until": None,
        "login_until": "2026-12-10T10:00:00+00:00",
        "policy": "Not used yet.",
    }})

    cli.cmd_token_status(argparse.Namespace())
    out = capsys.readouterr().out

    assert "Usable until   2026-12-10T10:00:00+00:00" in out
    assert "Access until" not in out, "there is no download period yet to report"


def test_status_survives_a_server_that_sends_no_timing(monkeypatch, capsys):
    """Failing to print a date must not stop a buyer fetching their data."""
    cli = _status_cli(monkeypatch, dict(BASE))

    assert cli.cmd_token_status(argparse.Namespace()) == 0
    assert "starter-4w" in capsys.readouterr().out


def test_status_shows_the_time_left_the_server_counted(monkeypatch, capsys):
    """Not computed here: the buyer's clock is not the one the deadline is on."""
    cli = _status_cli(monkeypatch, {**BASE, "timing": {
        "access_state": "active",
        "activated_at": "2026-09-11T05:54:23+00:00",
        "active_until": "2026-09-25T05:54:23+00:00",
        "redeem_by": "2026-12-10T05:54:23+00:00",
        "deadline": "2026-09-25T05:54:23+00:00",
        "expires_in_seconds": 1123200,
        "days_remaining": 13,
        "policy": "Active until 2026-09-25, 13 days from now.",
    }})

    cli.cmd_token_status(argparse.Namespace())
    out = capsys.readouterr().out

    assert "(13 days left)" in out


def test_status_says_hours_on_the_last_day_rather_than_zero_days(monkeypatch, capsys):
    cli = _status_cli(monkeypatch, {**BASE, "timing": {
        "access_state": "active",
        "activated_at": "2026-09-11T05:54:23+00:00",
        "active_until": "2026-09-25T05:54:23+00:00",
        "deadline": "2026-09-25T05:54:23+00:00",
        "expires_in_seconds": 14400,
        "days_remaining": 0,
        "policy": "Active until 2026-09-25, 4 hours from now.",
    }})

    cli.cmd_token_status(argparse.Namespace())
    out = capsys.readouterr().out

    assert "0 days left" not in out
    assert "hour(s) left" in out


def test_download_stops_before_planning_once_access_has_ended(monkeypatch, capsys):
    """Otherwise: a plan, a size, a confirm prompt, then a wall of 403s."""
    import pytest

    cli = _status_cli(monkeypatch, {**BASE, "timing": {
        "access_state": "lapsed",
        "activated_at": "2026-08-01T00:00:00+00:00",
        "active_until": "2026-08-15T00:00:00+00:00",
        "deadline": "2026-08-15T00:00:00+00:00",
        "expires_in_seconds": 0,
        "days_remaining": 0,
        "policy": "Access ended on 2026-08-15. Nothing already spent is refunded.",
    }})

    with pytest.raises(SystemExit) as exit_info:
        cli.cmd_download(argparse.Namespace(
            market="COINCHECK:BTC_SPOT", start="2026-01-01", days=1,
            root=None, api_url=None, token=None, force=False, yes=True))

    assert "Access ended on 2026-08-15" in str(exit_info.value)


def test_download_proceeds_while_access_is_live(monkeypatch):
    """The guard reads a server flag; it must not refuse an active token."""
    from komachi import client as client_module

    cli = _status_cli(monkeypatch, {**BASE, "timing": {
        "access_state": "active", "policy": "Active until 2026-09-25.",
    }})

    cli._refuse_if_closed({"timing": {"access_state": "active"}})
    # A server that sends no timing block at all must not be treated as closed.
    cli._refuse_if_closed({})


def test_download_stops_when_the_allowance_cannot_cover_the_range(monkeypatch, capsys):
    """The server refuses per file, so this changes what the buyer is asked, not
    what they may have: without it they confirm a plan and watch it fail once
    per file."""
    import pytest

    cli = _status_cli(monkeypatch, {**BASE, "remaining_market_days": 1,
                                    "timing": {"access_state": "active"}})
    monkeypatch.setattr(cli, "_plan", lambda client, args, remaining: (
        [{"file_date": "2026-01-0%d" % n, "data_type": "Trade", "size_bytes": 10}
         for n in (1, 2, 3)], "2026-01-01", "2026-01-03"))
    monkeypatch.setattr(cli, "already_have", lambda entry, dest: False)

    class Estimating(cli.KomachiClient):
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

        def status(self):
            return {**BASE, "remaining_market_days": 1, "timing": {"access_state": "active"}}

        def estimate(self, *a, **k):
            return {"new_market_days": 3, "remaining_market_days": 1, "sufficient": False}

    monkeypatch.setattr(cli, "_client", lambda args: Estimating())

    code = cli.cmd_download(argparse.Namespace(
        market="COINCHECK:BTC_SPOT", start="2026-01-01", days=3,
        root=None, api_url=None, token=None, force=False, yes=True))
    out = capsys.readouterr().out

    assert code == 1
    assert "Not enough allowance" in out
    assert "3 market-day(s) and 1 remain" in out
