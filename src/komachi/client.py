"""HTTP client for the Kamakura Quant Lab API.

cli.py goes through the same endpoints the React UI uses, so anything the
website can do is scriptable and vice versa.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_API_URL = "http://127.0.0.1:9740"
CONFIG_PATH = Path("~/.komachi/config.json").expanduser()


class ApiError(RuntimeError):
    """An error the API reported, carrying its message through to the user."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class Credentials:
    api_url: str
    token: str

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"api_url": self.api_url, "token": self.token}, indent=2))
        # The token is a bearer credential: keep it out of other users' reach.
        path.chmod(0o600)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Credentials | None":
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return cls(api_url=data.get("api_url", DEFAULT_API_URL), token=data["token"])


class KomachiClient:
    def __init__(self, api_url: str, token: str, timeout: float = 30.0):
        self.api_url = api_url.rstrip("/")
        self.token = token
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "KomachiClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self._client.request(
            method,
            f"{self.api_url}{path}",
            headers={"Authorization": f"Bearer {self.token}"},
            **kwargs,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ApiError(response.status_code, detail)
        return response.json()

    def status(self) -> dict:
        return self._request("GET", "/api/me")

    def markets(self) -> dict:
        """Deliverable markets plus the external sources Kamakura Quant Lab refers to."""
        return self._request("GET", "/api/datasets/markets")

    def calendar(self, market: str) -> list[dict]:
        return self._request("GET", "/api/datasets/calendar", params={"market": market})["days"]

    def stats(self, market: str, start: str | None = None, end: str | None = None,
              days: int | None = None) -> list[dict]:
        """Per-file quality from the catalogue: rows, size, missing minutes."""
        params: dict = {"market": market}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if days:
            params["days"] = days
        return self._request("GET", "/api/datasets/stats", params=params)["files"]

    def estimate(self, market: str, start_date: str, end_date: str) -> dict:
        """What a range would cost, without spending any of it.

        The endpoint can also mint URLs for a whole range, and Komachi never
        asks it to. A signature lives an hour and a large download does not
        finish in one, so URLs are signed per file at the moment each is
        fetched; see `cmd_download`.
        """
        return self._request(
            "POST",
            "/api/datasets/manifest",
            json={
                "market": market,
                "start_date": start_date,
                "end_date": end_date,
                "dry_run": True,
            },
        )

    def download_link(self, market: str, file_date: str, data_type: str) -> str:
        """A stable address for one file.

        Fetching it redirects to object storage. Renewal is the service's
        business: an expired signature is replaced on the way through, so a
        client never has to ask for one.
        """
        return f"{self.api_url}/api/download/{market}/{file_date}/{data_type}"

    def auth_header(self) -> dict:
        """For fetching a download link on a client this class does not own."""
        return {"Authorization": f"Bearer {self.token}"}
