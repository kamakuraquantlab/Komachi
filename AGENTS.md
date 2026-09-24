# Working with a Komachi user

You are helping someone use Komachi, the command-line tool that fetches market
data from Kamakura Quant Lab. They are a customer, not a contributor: they want
the tool working and their data on disk. Assume nothing about their Python
setup and do not assume they will read anything you do not say plainly.

Answer in whatever language they write in. Most of them write Japanese. This
file is in English because you read it, not because they do.

Expect a mismatch: **the tool prints English and nothing else**, while the
README, the website and the terms are Japanese. So a question will usually
arrive in Japanese about an error message in English, and the words they use
will be the site's rather than the tool's. These are the same thing:

| 日本語 | What the tool and this file call it |
|---|---|
| 利用枠 | the allowance — how many market-days are left |
| market-day | market-day. One market, one date. Not translated anywhere |
| 取得する / 取得済み | to take a market-day / already taken. The old word was アンロック; it is gone and should not come back |
| ログイン期間 | the login period — one month from the purchase, to sign in |
| ダウンロード期間 | the download period — fourteen days from the first sign-in |
| 板情報 / 板 | the `OrderBook` dataset |
| 約定 / 約定データ | the `Trade` dataset |
| 欠測 | a gap: a date inside a market's span with no file |
| 収録期間 | the span a market covers, first date to last |
| 注文番号 | the order number from their receipt |
| 保存先 / データレイク | the data root, `ROOT_PATH` in `~/.kamakuraquantlab.env` |

When you link them to documentation, link the Japanese pages —
`kamakuraquantlab.jp/data/`, `/tool/`, `/support/` are Japanese, and the same
paths under `/en/` are English. `README.md` in this repository is Japanese;
this file is not.

## The one rule that matters

**`komachi download` spends market-days, and that cannot be undone.**

A market-day is one market on one date. The allowance is finite and was paid
for. A day already taken costs nothing to fetch again, but a new one is spent
the moment its first file is asked for — there is no confirmation step on the
service side and no refund.

So:

1. Never run `download` on your own initiative.
2. Before running it, say which market, which dates, and how many market-days
   it will cost, and wait for them to agree.
3. `komachi download` prints exactly that and asks before fetching. Let it
   ask. Do not pass `--yes` unless they have just told you the range is right.
4. If they ask for "everything" or "the last year", stop and work out the cost
   with them first. It is usually more than they meant.

Everything else here is free. `markets`, `local`, `stats`, `decode`, `trades`,
`book`, `duckdb`, `sql` and `token status` spend nothing and can be run freely
to answer a question. `import` fetches from the exchange, not from us, and
spends nothing.

## The second rule

**The token is a credential.** It is theirs, it identifies their allowance, and
anyone holding it can spend it.

- Never print it, echo it, or include it in a summary, a commit, an issue, or
  anything you send anywhere.
- It lives in `~/.kamakuraquantlab.env`, mode 0600. Leave it there.
- If they paste it into the chat, do not repeat it back. Tell them they can
  issue a new one from the download page, which invalidates the old one.
- Never commit that file, and never add it to this repository.

## Setting it up

Python 3.13 or newer. Tested on Linux and macOS only; Windows is untried, and
if they are on Windows say so rather than guessing.

```bash
python3 --version                     # must be 3.13+
pip install 'kamakuraquantlab-komachi[duckdb]'
```

The `[duckdb]` extra pulls DuckDB, PyArrow and pandas, which is what makes
`komachi duckdb` and `komachi trades` work. Without it the download still
works and the query commands do not. Install it unless they say otherwise.

If `pip` is not theirs to use — a system Python, an externally-managed
environment, a `PEP 668` error — make a virtual environment rather than
reaching for `--break-system-packages`:

```bash
python3 -m venv ~/.venvs/komachi && ~/.venvs/komachi/bin/pip install 'kamakuraquantlab-komachi[duckdb]'
```

Then either activate it or use `~/.venvs/komachi/bin/komachi` as the command.

### First run

The first `komachi` command writes `~/.kamakuraquantlab.env`, prints it, and
stops without running what was asked. That is deliberate, not a failure: it
asks where to keep the data, defaults to `~/kamakuraquantlab-data`, and exits
0. Run the command again afterwards.

If you are running it non-interactively it takes the default. If they want the
data elsewhere — an external disk, a larger volume — run it where they can
answer, or edit `ROOT_PATH` in that file before continuing.

### The token

They get it from https://kamakuraquantlab.jp/tsurugaoka/ by signing in with
the order number and the email they used. The page mints it; we store only a
hash, so it cannot be looked up later. Issuing a new one stops the old one
working.

```bash
komachi token set --token <the token they were given>
komachi token status
```

`token status` is the fastest way to see whether anything is wrong: it shows
the allowance, what is left, and both deadlines.

## What the commands do

| | Spends |
|---|---|
| `komachi token set --token TOKEN` | no |
| `komachi token status` | no |
| `komachi markets` | no |
| `komachi download --market MARKET --start DATE [--days N]` | **yes** |
| `komachi import --market BINANCE:SYMBOL --start DATE --end DATE` | no |
| `komachi import --market GMO:SYMBOL --start DATE --end DATE` | no |
| `komachi local` | no |
| `komachi duckdb` / `komachi sql` | no |
| `komachi trades` / `book` / `stats` / `decode` | no |

`download` and `import` rebuild the DuckDB views themselves when they write
anything, so what arrives is queryable straight away. `komachi duckdb` is for
rebuilding by hand after something else touched the tree — a deleted file, a
database moved with `--db`. Do not tell them to run it after a download; it
already ran.

`markets` is the right first command for almost any question about what is
available: it lists every market with its datasets, its date span, and the
days missing inside that span.

`import` is for the two venues that publish their own trade history —
Binance and GMO. It downloads from them, not from us, converts to the same
layout, and costs nothing. Only those two; anything else is refused with a
message saying so.

Data lands at
`<root>/bronze/dataset=<Trade|OrderBook>/exchange=<EX>/symbol=<SYM>/date=<JST date>/data.parquet`.
Dates are Asia/Tokyo days; timestamps inside the files are UTC epoch seconds.

## When something is wrong

Read the error. They are written to be read and usually name the cause and the
date it happened.

| What they see | What it is | What to do |
|---|---|---|
| `This purchase was valid until … and has expired` | The login period ran out | Nothing technical will fix it. Send them to support. |
| `The download period ended on …` | The 14 days from their first sign-in are up | Same. Files already downloaded are still theirs. |
| `Grant exhausted` / `0 of 0 remaining` | The allowance is spent | Not a bug. `token status` shows the arithmetic. |
| `No active purchase matches that order ID and email` | Wrong details at sign-in. This is the website, not Komachi — they meet it before they ever get a token | Check against the receipt. Nothing to debug locally, and the message is deliberately the same for a wrong email and a wrong order number. |
| `No <dataset> file for <market> on <date>` | That day is not in the archive | `komachi markets` lists the gaps. Not an error to retry. |
| A download stops partway | Interrupted | Re-run the same command. It resumes and does not re-charge for files already complete. |

Two things are worth knowing before you start debugging:

- **A gap is not a fault.** Some days are genuinely missing, and some markets
  carry only one of the two datasets — a venue that publishes its own trades
  has only its order book here. `komachi markets` is the authority.
- **Re-running `download` is safe.** It checks the disk before the service,
  skips what is already complete, and never spends twice for the same day.

## What not to do

- Do not edit files in this repository to work around a problem. If the tool
  is broken, say so; a local patch makes their install differ from everyone
  else's and hides the bug from us.
- Do not modify or reorganise their data root. Komachi and Hase both expect
  that layout, and DuckDB reads the directory names as columns.
- Do not retry a refusal in a loop. Expired is expired.
- Do not guess at anything involving their allowance or their money. If the
  numbers do not add up, stop and send them to support@kamakuraquantlab.jp
  with their order number.

## Where the real documentation is

- `README.md` in this repository — the full command reference, in Japanese.
- https://kamakuraquantlab.jp/tool/ — setup and usage, both languages.
- https://kamakuraquantlab.jp/data/ — what the archive holds, the schema, the
  quality rules and the known gaps.
- https://kamakuraquantlab.jp/support/ — the questions that come up most, and
  the address to write to.

If this file and the service disagree, the service is right and this file is
out of date. Say so rather than making the service fit the file.
