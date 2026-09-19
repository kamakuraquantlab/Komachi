"""Where Komachi keeps its settings, and how it asks for them.

One file, `~/.kamakuraquantlab.env`, holding everything: the data root, the
token, and the service address. Plain text, meant to be read and edited.

It lives in the home directory rather than beside the data, which is what makes
one file safe to hold all three. A `.env` in a project directory finds its way
into a git repository, and the token is a credential that unlocks something
bought; in `$HOME` it is no more exposed than an SSH key, and the file is 0600
for the same reason.

Home rather than the working directory has a second benefit. A per-directory
file is not found when you run from somewhere else, so the tool would ask
again and quietly write a second configuration. There is one answer here, and
it is the same answer from every directory.

Initial setup writes a file holding only the data root, so what is printed back
at the end of it can be the whole file. Nothing else is in it yet.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = Path("~/.kamakuraquantlab.env").expanduser()
DEFAULT_ROOT = "~/kamakuraquantlab-data"
DEFAULT_YUKINOSHITA_URL = "https://yukinoshita.kamakuraquantlab.jp"

ROOT_KEY = "ROOT_PATH"
URL_KEY = "YUKINOSHITA_URL"
TOKEN_KEY = "TOKEN"

# In the file the keys are short, because the filename says whose they are. In
# the environment they cannot be: a bare `TOKEN` is the kind of name anything
# might set, and a credential picked up from a stray variable is a credential
# used by accident. The root and the service address keep their short names
# there because both are explicit enough to be read at a glance.
ENV_TOKEN_KEY = "KAMAKURAQUANTLAB_TOKEN"


@dataclass
class Settings:
    root: Path
    yukinoshita_url: str
    token: str | None = None


class SetupRequired(SystemExit):
    """Raised, and printed, when the tool has not been set up yet."""


def read_env_file(path: Path | None = None) -> dict[str, str]:
    """Read the settings file. Only `KEY=value` lines, no shell expansion."""
    # Resolved at call time rather than bound as a default: a default freezes
    # the module attribute at import, which makes the path impossible to
    # redirect and lets a test suite write to a real home directory.
    path = path or ENV_FILE
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


def write_env_file(values: dict[str, str], path: Path | None = None) -> None:
    """Replace the settings file, and leave it readable only by its owner."""
    path = path or ENV_FILE
    body = "".join(f"{key}={value}\n" for key, value in values.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Kamakura Quant Lab settings. Read and edit freely.\n"
        "# Komachi and Hase both use this file.\n\n" + body
    )
    path.chmod(0o600)


def update_env_file(key: str, value: str, path: Path | None = None) -> None:
    """Set one key, leaving the rest of the file as it was."""
    path = path or ENV_FILE
    values = read_env_file(path)
    values[key] = value
    write_env_file(values, path)


def save_token(token: str, path: Path | None = None) -> None:
    update_env_file(TOKEN_KEY, token, path)


def run_setup(tool: str, path: Path | None = None) -> None:
    """Ask for a data root, write the file, show it, and stop.

    Stopping is deliberate. Setup is a different act from the command that
    triggered it, and finishing that command straight afterwards would hide
    what just happened behind whatever it printed. The next run starts from a
    settled state.

    The file written here holds the data root and nothing else, which is why
    the whole of it can be shown. A token, if there is ever one, arrives later
    through `token set`.
    """
    path = path or ENV_FILE
    existing = read_env_file(path)
    replacing = bool(existing) and ROOT_KEY not in existing

    print(f"{tool} keeps data under one root directory: Komachi downloads into "
          "it, Hase reads from it.")
    print(f"Leave blank for {DEFAULT_ROOT}.\n")
    root = ""
    if sys.stdin.isatty():
        try:
            root = input("Data root: ").strip()
        except EOFError:
            root = ""
    resolved = Path(root or DEFAULT_ROOT).expanduser()
    resolved.mkdir(parents=True, exist_ok=True)
    write_env_file({ROOT_KEY: str(resolved)}, path)

    print(f"\nWrote {path}\n")
    print(path.read_text().rstrip())
    if replacing:
        print(f"\nThe previous file named no {ROOT_KEY} and has been replaced.")
        print("Run `komachi token set --token <TOKEN>` again if you had one.")
    print(f"\nSetup done. Run {tool} again.")
    raise SetupRequired(0)



def data_root(override: str | None = None, *, env: bool = False,
              setup: bool = False, tool: str = "komachi",
              default: str | None = None) -> Path:
    """Where the data is. The one function to ask, from anywhere.

    `komachi.data_root()` with nothing passed is the whole answer for a script:
    ROOT_PATH from the settings file, which is the answer its reader already
    gave when Komachi set itself up. It deliberately ignores the environment,
    because a script that can be pointed somewhere else by a stray variable is
    a script whose numbers cannot be placed.

    A command line passes `env=True` and its own --root, since a flag and a
    variable are per-run answers somebody typed on purpose, and `setup=True`,
    which turns "nothing has settled this" into the question that settles it.
    A caller that cannot answer a prompt passes a `default` instead and gets
    it; with neither, an unset root raises rather than guessing.
    """
    root = override or (os.environ.get(ROOT_KEY) if env else None) or read_env_file().get(ROOT_KEY)
    if root is None:
        if setup:
            run_setup(tool)     # writes the file and stops the program
        if default is None:
            raise SetupRequired(
                f"No {ROOT_KEY} in {ENV_FILE}. Run komachi once to set it up.")
        root = default
    return Path(root).expanduser()


def resolve(root_override: str | None = None, url_override: str | None = None,
            token_override: str | None = None, tool: str = "komachi",
            setup: bool = True) -> Settings:
    """Settle the root, the service address and the token.

    Precedence is explicit flag, then environment, then the settings file, for
    each of the three: a flag should win over a file the user forgot they
    wrote. The root itself is `data_root`'s business, including what an unset
    one means; anything running unattended passes `setup=False` and gets the
    default instead of a prompt it cannot answer.
    """
    stored = read_env_file()

    url = (url_override or os.environ.get(URL_KEY) or stored.get(URL_KEY)
           or DEFAULT_YUKINOSHITA_URL)
    token = token_override or os.environ.get(ENV_TOKEN_KEY) or stored.get(TOKEN_KEY)
    root = data_root(root_override, env=True, setup=setup, tool=tool,
                     default=DEFAULT_ROOT)

    return Settings(root=root, yukinoshita_url=url, token=token)
