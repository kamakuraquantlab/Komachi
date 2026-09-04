"""Where Komachi keeps its settings, and how it asks for them.

Two files, deliberately separate.

`.env` in the working directory holds the data root and the API address. It is
plain text, meant to be read and edited, and is the file the help message
points at. Keeping it beside the data means a project directory describes its
own setup.

The purchase token lives in `~/.komachi/config.json` at mode 0600 instead. It
is a credential that unlocks something bought, and putting it in a `.env` next
to the data invites it into a git repository. The split costs one sentence of
explanation and removes a whole category of accident.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = Path(".env")
TOKEN_FILE = Path("~/.komachi/config.json").expanduser()
DEFAULT_ROOT = "~/kql-data"
DEFAULT_API_URL = "https://yukinoshita.kamakuraquantlab.jp"

ROOT_KEY = "KQL_ROOT_PATH"
API_KEY = "KQL_API_URL"


@dataclass
class Settings:
    root: Path
    api_url: str
    token: str | None = None


def load_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """Read a minimal .env. Only `KEY=value` lines, no shell expansion."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env_file(root: Path, api_url: str, path: Path = ENV_FILE) -> None:
    path.write_text(
        "# Kamakura Quant Lab -- Komachi settings.\n"
        "# Edit freely. The purchase token is not kept here; see"
        f" {TOKEN_FILE}.\n\n"
        f"{ROOT_KEY}={root}\n"
        f"{API_KEY}={api_url}\n"
    )


def load_token(path: Path = TOKEN_FILE) -> str | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text()).get("token")
    except (ValueError, OSError):
        return None


def save_token(token: str, path: Path = TOKEN_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": token}, indent=2))
    path.chmod(0o600)


def resolve(root_override: str | None = None, api_override: str | None = None,
            token_override: str | None = None, interactive: bool = True) -> Settings:
    """Settle the root and API address, asking once if they are not known yet.

    Precedence is explicit flag, then environment, then `.env`, then a prompt.
    A flag should win over a file the user forgot they wrote.
    """
    env_file = load_env_file()

    root = root_override or os.environ.get("ROOT_PATH") or os.environ.get(ROOT_KEY) or env_file.get(ROOT_KEY)
    api_url = api_override or os.environ.get(API_KEY) or env_file.get(API_KEY)

    # First use is whenever no root has been settled anywhere. Ask when there is
    # a terminal to ask; otherwise take the default rather than blocking a
    # script, but still record the choice so it stops being implicit.
    first_use = root is None
    if first_use and interactive and sys.stdin.isatty():
        print("Komachi stores downloaded data under a single root directory.")
        print(f"Leave blank for {DEFAULT_ROOT}.")
        root = input("Data root: ").strip() or DEFAULT_ROOT
    elif first_use:
        root = DEFAULT_ROOT

    if api_url is None:
        api_url = DEFAULT_API_URL

    resolved = Path(root).expanduser()
    if first_use:
        resolved.mkdir(parents=True, exist_ok=True)
        write_env_file(resolved, api_url)
        print(f"\nSaved to {ENV_FILE.resolve()}")
        print(f"  {ROOT_KEY}={resolved}")
        print(f"  {API_KEY}={api_url}")
        print("Edit that file to change either. Your token is stored separately in")
        print(f"  {TOKEN_FILE}\n")

    return Settings(root=resolved, api_url=api_url,
                    token=token_override or os.environ.get("KQL_TOKEN") or load_token())
