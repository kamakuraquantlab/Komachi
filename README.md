# Komachi

**鎌倉クオンツラボ**のコマンドラインクライアントです。
ヒストリカル市場データを取得し、DuckDB からそのまま参照できる構成で保存します。

*[English README](README-en.md)*

[Kamakura Quant Lab](https://kamakuraquantlab.jp) のデータは、2 つの方法で取得できます。
収録範囲、スキーマ、品質基準は[データのページ](https://kamakuraquantlab.jp/data/)に記載しています。

**ブラウザ** — [tsurugaoka](https://kamakuraquantlab.jp/tsurugaoka/)

数日分を確認する用途に適しています。1 ファイルずつ、ブラウザの保存先に保存されます。

**コマンドライン** — Komachi（本リポジトリ）

Yukinoshita API（`yukinoshita.kamakuraquantlab.jp`）を呼び出すクライアントです。
まとまった量を扱う場合はこちらを使用します。

| 機能 | 内容 |
|---|---|
| 残高と配信状況の確認 | 利用できるマーケット、日付ごとの収録状況と品質を、取得前に確認できます |
| 一括取得 | 範囲を指定してまとめて取得します。中断後は同じコマンドで再開し、チェックサムで検証します |
| Hive 形式での保存 | 収集時と同じディレクトリ構成で保存するため、DuckDB から取り込み処理なしに参照できます |
| 無償公開データの取り込み | Binance Vision と GMO コインの公開データを、日本時間の日付へ再分割して取り込みます。配信データと同一の条件で比較できます |
| ローカル参照 | 手元のファイルの一覧、約定と気配の表示、DuckDB ビューの作成 |

権限の判断と URL の署名は Yukinoshita が行います。
ファイルの実体はオブジェクトストレージから直接取得するため、
API がデータ本体を中継することはありません。

## 1 クイックスタート

28 market-day を使う場合の例

### 1.1 サインイン

トークンは
[kamakuraquantlab.jp/tsurugaoka/](https://kamakuraquantlab.jp/tsurugaoka/)
で発行します。
手元にある注文番号とメールアドレスでサインインし、「トークンを表示」を押してください。
表示はその 1 回だけですが、必要になればいつでも発行し直せます。
発行し直すと、それまでのトークンは使えなくなります。

```bash
pip install 'kamakuraquantlab-komachi[duckdb]'
komachi token set --token hk_...
```

最小構成は `pip install kamakuraquantlab-komachi`（`httpx` のみ）です。
取り込み、DuckDB 連携、ファイル検査を使う場合は上記の `duckdb` エクストラを指定します。

初回はデータの保存先を尋ねられ、設定ファイル `~/.kamakuraquantlab.env`
（パーミッション 0600）に `ROOT_PATH` として記録されます。トークンも同じファイルです。
ホームディレクトリに置くため、データディレクトリをそのままバージョン管理下に置いても
資格情報が混入せず、どのディレクトリから実行しても答えは 1 つです。

### 1.2 残高と期限の確認

```bash
komachi token status
```

```text
Product        starter-4w
Token status   active
Access         active
First used     2026-09-11T05:54:23+00:00
Access until   2026-09-25T05:54:23+00:00
Allowance      28 market-days  (4 market-weeks)
Remaining      28 market-days  (4 market-weeks)

Markets        BITBANK:BTC_SPOT, BITBANK:ETH_SPOT, ... COINCHECK:XRP_SPOT

Active until 2026-09-25. Until then you can unlock market-days and re-download
anything already unlocked as often as you like, at no further cost.
```

期間は 2 つあり、順番に効きます。

| | 期間 | 起点 | 過ぎると |
|---|---|---|---|
| ログイン期間 | 1 か月 | ご購入時 | サインインできず、以後は使えません |
| ダウンロード期間 | 14 日 | **最初にサインインした時** | 新たなアンロックも配信も行われません |

**ログイン期間**の間に、一度 tsurugaoka にサインインしてください。
この最初のサインインでトークンが発行され、同時にダウンロード期間が始まります。

**ダウンロード期間**はその最初の 1 回から数えます。
受け取ってすぐに作業を始められなくても不利にならないよう、
ご購入時ではなく初回サインイン時を起点にしています。

利用期間の中では、アンロックした market-day を何度でも取得できます。
ファイルを削除しても、ダウンロードに失敗しても、取り直しに残高は消費しません。
回数の上限はありません。
ダウンロードのたびに新しい URL を発行し、その URL は 1 時間で失効します。
`komachi download` は未アンロックの日付をその場でアンロックしてから取得するため、
アンロックのための操作は必要ありません。

利用期間を過ぎると、新しい market-day のアンロックも、ダウンロード用 URL の発行も停止します。
残高が残っていても使えません。
`komachi download` は取得を始める前に、その旨を表示して終了します。
tsurugaoka にはサインインでき、利用状況と終了日を確認できます。
消費済みの market-day は消費済みのまま残り、返還はありません。
期間内に必要なファイルを保存してください。

実際には、ここに来た時点ですでに利用期間が始まっています。
`komachi token set` がトークンを確認するために行う通信も「使った」1 回に数えるためです。
そのため `komachi token status` には、期限の日付と残り日数が表示されます。

日付も残り日数もサーバーが計算して返したものをそのまま表示しています。
残り日数の計算には時計が必要ですが、その時計は手元のものではないからです。
このツールが独自に期限を判断することはありません。

### 1.3 収録状況の確認

どのマーケットが使えるかを確認します。

```bash
komachi markets
komachi catalog --market COINCHECK:BTC_SPOT --days 3
```

```text
date         datasets                     rows      size    gap  note
2026-09-01   OrderBook,Trade           264,447    24.8MB     8m
2026-09-02   OrderBook,Trade           274,792    26.7MB     1m
2026-09-03   OrderBook,Trade           280,067    27.9MB     9m

3 market-day(s). 'gap' is minutes with no record in the JST day.
```

`gap` は、その日のうち記録のない分数です。取得前に品質を確認できます。

### 1.4 取得

```bash
komachi download --market COINCHECK:BTC_SPOT --start 2025-07-01 --days 28
```

実行前に、対象期間・ファイル数・容量・消費する market-day 数を表示して確認を求めます。
中断した場合は同じコマンドを再実行すれば、取得済みのファイルは飛ばして続きから再開します。
すでに手元にあるファイルに対して残高を再消費することはありません。

### 1.5 無償公開データの取り込み

同じ期間の Binance と GMO コインの約定データを、無償公開元から取り込みます。
残高は消費しません。

```bash
komachi binance-import --symbol BTC_USDT --start 2025-07-01 --end 2025-07-28
komachi gmo-import     --symbol BTC_JPY  --start 2025-07-01 --end 2025-07-28
```

取り込み時に日本時間の日付へ再分割するため、配信データと同じ基準で比較できます。

### 1.6 保存先の確認

```bash
komachi local
```

```text
market                   dataset     days  range
COINCHECK:BTC_SPOT       OrderBook     28  2025-07-01 .. 2025-07-28
COINCHECK:BTC_SPOT       Trade         28  2025-07-01 .. 2025-07-28
BINANCE:BTC_USDT         Trade         28  2025-07-01 .. 2025-07-28
GMO:BTC_JPY              Trade         28  2025-07-01 .. 2025-07-28
```

### 1.7 中身の確認

```bash
komachi trades --market COINCHECK:BTC_SPOT --date 2025-07-01 --rows 3
komachi book   --market COINCHECK:BTC_SPOT --date 2025-07-01 --rows 3
```

```text
time (JST)    side             price            size
00:00:00.000  buy    15,456,978.0000      0.03000000
00:00:01.000  buy    15,458,282.0000      0.03102218

time (JST)            best bid        best ask      spread
00:00:00.000   15,456,905.0000 15,456,978.0000     73.0000
00:00:00.000   15,453,307.0000 15,458,283.0000  4,976.0000
```

### 1.8 分析へ

```bash
komachi duckdb
duckdb ~/kamakuraquantlab-data/kamakuraquantlab.duckdb
```

```sql
SELECT date, count(*) AS trades, avg(price) AS vwap
FROM trade
WHERE exchange = 'COINCHECK' AND symbol = 'BTC_SPOT'
GROUP BY date ORDER BY date;
```

作図と派生データの作成は Komachi の範囲外です。
分析ツールキットの Hase が担当します（公開準備中）。

## 2 コマンド一覧

### 2.1 リモート操作

Yukinoshita API または無償公開元との通信を伴うコマンドです。

| コマンド | 内容 | 残高の消費 |
|---|---|---|
| `komachi token set --token TOKEN` | トークンを検証して保存 | なし |
| `komachi token status` | 付与数、使用済み、残高、2 つの期限 | なし |
| `komachi markets` | 利用できるマーケットと、無償公開元の案内 | なし |
| `komachi calendar --market MARKET` | 公開済みの日付と、取得済みの日付 | なし |
| `komachi catalog --market MARKET` | 日ごとの収録状況と品質 | なし |
| `komachi download --market MARKET --start DATE [--days N]` | 範囲を指定して取得（中断後は再開） | **あり** |
| `komachi binance-import --symbol SYMBOL --start DATE --end DATE` | Binance Vision から取り込み | なし |
| `komachi gmo-import --symbol SYMBOL --start DATE --end DATE` | GMO コインの公開データから取り込み | なし |

残高を消費するのは `download` のみです。
取得前に、対象期間・ファイル数・容量・消費数を表示して確認を求めます。
market-day は 1 マーケットの 1 日分で、同じ日の板と約定を合わせて 1 と数えます。

### 2.2 ローカル操作

手元のファイルだけを参照します。通信も残高の消費もありません。

| コマンド | 内容 |
|---|---|
| `komachi local` | 保存済みファイルの一覧 |
| `komachi trades --market MARKET --date DATE` | 約定データの表示 |
| `komachi book --market MARKET --date DATE` | 最良気配とスプレッドの表示 |
| `komachi stats --path PATH` | 行数と時間範囲 |
| `komachi decode --path PATH` | スキーマと先頭数行 |
| `komachi duckdb` | DuckDB のビューを作成・更新 |
| `komachi sql` | ビュー定義の SQL を出力 |

## 3 保存先の構成

データは、収集時と同じ Hive 形式のディレクトリに保存されます。

```text
$ROOT_PATH/bronze/dataset=Trade/exchange=GMO/symbol=BTC_JPY/date=2026-01-15/data.parquet
```

自分のスクリプトから保存先を知るには `komachi.data_root()` を呼びます。
初期設定で答えた `ROOT_PATH` だけを読み、環境変数も既定値も見ません。
未設定なら、その場で設定を促して停止します。

```python
import komachi

root = komachi.data_root()      # ~/.kamakuraquantlab.env の ROOT_PATH
```

Hase も同じ関数を呼んでいます。保存先の答えは 1 か所にしかありません。

DuckDB、PyArrow、Spark、Athena のいずれも `dataset`・`exchange`・`symbol`・`date` を
パスから列として認識します。1 年分でも次の 1 行で読み込めます。

```sql
SELECT * FROM read_parquet('~/kamakuraquantlab-data/bronze/dataset=Trade/**/*.parquet', hive_partitioning = 1);
```

## 4 日付の扱い

`date=` は**日本時間の 1 日**です。`date=2026-01-15` は 2026-01-15 00:00〜23:59 JST、
UTC では 2026-01-14 15:00〜2026-01-15 14:59 にあたります。
ファイル内のタイムスタンプは UTC エポック秒のため、実行環境のタイムゾーンに依存しません。

取り込み元の日付区切りは取引所ごとに異なります。
Binance Vision は 00:00 UTC、GMO コインは取引日の切り替えである 21:00 UTC を基準としています。
Komachi は取り込み時に日本時間の日付へ再分割するため、
配信データと無償公開データを同じ基準で比較できます。

このため、ある 1 日を取り込むには前日分の元ファイルも必要です。
どちらか一方しか取得できない日は、不完全なまま書き出さずに保留します。

## 5 Komachi が行わないこと

1. 取引所 API への直接接続。接続先は Yukinoshita API、Binance Vision、GMO コインの公開データのみです。
2. データの加工・導出。silver 以降は [Hase](https://github.com/kamakuraquantlab) が担当します。
3. Kamakura Quant Lab の API 以外に対する資格情報の保持。

## 6 ライセンス

Apache License 2.0。[LICENSE.md](LICENSE.md)
