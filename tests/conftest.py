import pytest


@pytest.fixture(autouse=True)
def _never_touch_the_real_home(tmp_path, monkeypatch):
    """Point the settings file at a temporary directory for every test.

    Without this a test that resolves settings with nothing configured runs
    first-time setup against the developer's own home, writing a file and
    creating a data directory there. It happened.
    """
    import komachi.settings as settings

    monkeypatch.setattr(settings, "ENV_FILE", tmp_path / "settings.env")
    # A root, so an ordinary test does not trip first-time setup on its way to
    # whatever it was actually checking. A test about setup clears it again.
    monkeypatch.setenv(settings.ROOT_KEY, str(tmp_path / "data"))
    # Setup creates the directory it settles on. Left at its real default that
    # is the developer's home, which a test run has no business creating.
    monkeypatch.setattr(settings, "DEFAULT_ROOT", str(tmp_path / "default-data"))
    monkeypatch.delenv(settings.URL_KEY, raising=False)
    monkeypatch.delenv(settings.ENV_TOKEN_KEY, raising=False)
