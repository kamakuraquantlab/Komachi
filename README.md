# Komachi

**鎌倉クオンツラボ**のコマンドラインクライアントです。
購入したヒストリカル市場データを取得し、DuckDB からそのまま参照できる構成で保存します。

*[English README](README-en.md)*

```bash
pip install 'komachi[duckdb]'
komachi auth login --token hk_...
komachi download --market GMO:BTC_JPY --start 2026-01-01
komachi duckdb
duckdb ~/kql-data/kql.duckdb
```

## 接続先

Komachi は単体では動作しません。次の 2 つに接続します。

| 接続先 | 役割 |
|---|---|
| [kamakuraquantlab.jp](https://kamakuraquantlab.jp) | データの内容、収録範囲、購入したデータのダウンロード |
| `yukinoshita.kamakuraquantlab.jp` | API。残数の確認、market-day のアンロック、署名付き URL の発行 |

Yukinoshita が権限を判断し、S3 への署名付き URL を発行します。
ファイルの実体は S3 から直接取得するため、API がデータ本体を中継することはありません。

ブラウザからのダウンロードは [kamakuraquantlab.jp/tsurugaoka/](https://kamakuraquantlab.jp/tsurugaoka/)
でも行えますが、数ファイルを確認する用途向けです。
まとまった量を扱う場合、再開・チェックサム検証・分析向けのレイアウト保存に対応した
Komachi をご利用ください。

## クイックスタート

### どちらを使うか

| 購入した日数 | 推奨 |
|---|---|
| 1〜7 market-day | [ブラウザ](https://kamakuraquantlab.jp/tsurugaoka/)で十分です |
| それ以上 | Komachi。中断後の再開、チェックサム検証に対応し、分析にそのまま使える構成で保存します |

ブラウザは 1 ファイルずつ、ブラウザの保存先に置きます。
Komachi は範囲を指定して一括で取得し、Hive 形式のディレクトリに保存するため、
DuckDB から追加の取り込み処理なしに参照できます。

### 28 market-day を使う場合の例

**1. サインイン**

```bash
pip install 'komachi[duckdb]'
komachi auth login --token hk_...
```

初回はデータの保存先を尋ねられ、実行ディレクトリの `.env` に記録されます。
トークンは `~/.komachi/config.json`（パーミッション 0600）に保存されます。

**2. 残数の確認**

```bash
komachi status
```

```text
Product        starter-4w
Token status   active
Valid until    2026-10-05T14:54:23+00:00
Allowance      28 market-days  (4 market-weeks)
Remaining      28 market-days  (4 market-weeks)

Markets        BITBANK:BTC_SPOT, BITBANK:ETH_SPOT, ... COINCHECK:XRP_SPOT
```

**3. 収録状況の確認**

どのマーケットが使えるかを確認します。残数は消費しません。

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

**4. 取得**

```bash
komachi download --market COINCHECK:BTC_SPOT --start 2025-07-01 --days 28
```

実行前に、対象期間・ファイル数・容量・消費する market-day 数を表示して確認を求めます。
中断した場合は同じコマンドを再実行すれば、取得済みのファイルは飛ばして続きから再開します。
すでに手元にあるファイルに対して残数を再消費することはありません。

**5. 無償公開データの取り込み**

同じ期間の Binance と GMO コインの約定データを、無償公開元から取り込みます。
残数は消費しません。

```bash
komachi binance-import --symbol BTC_USDT --start 2025-07-01 --end 2025-07-28
komachi gmo-import     --symbol BTC_JPY  --start 2025-07-01 --end 2025-07-28
```

取り込み時に日本時間の日付へ再分割するため、購入データと同じ基準で比較できます。

**6. 保存先の確認**

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

**7. 中身の確認**

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

**8. 分析へ**

```bash
komachi duckdb
duckdb ~/kql-data/kql.duckdb
```

```sql
SELECT date, count(*) AS trades, avg(price) AS vwap
FROM trade
WHERE exchange = 'COINCHECK' AND symbol = 'BTC_SPOT'
GROUP BY date ORDER BY date;
```

作図と派生データの作成は Komachi の範囲外です。
分析ツールキットの Hase が担当します（公開準備中）。

## コマンド一覧

### リモート操作

Yukinoshita API または無償公開元との通信を伴うコマンドです。

| コマンド | 内容 | 残数の消費 |
|---|---|---|
| `komachi auth login --token TOKEN` | トークンを検証して保存 | なし |
| `komachi status` | 残数、使用済み数、有効期限 | なし |
| `komachi markets` | 利用できるマーケットと、無償公開元の案内 | なし |
| `komachi calendar --market MARKET` | 公開済みの日付と、取得済みの日付 | なし |
| `komachi catalog --market MARKET` | 日ごとの収録状況と品質 | なし |
| `komachi download --market MARKET --start DATE [--days N]` | 範囲を指定して取得（中断後は再開） | **あり** |
| `komachi manifest --market MARKET --start DATE [--dry-run]` | 署名付き URL の発行、または費用の確認 | `--dry-run` 以外は**あり** |
| `komachi binance-import --symbol SYMBOL --start DATE --end DATE` | Binance Vision から取り込み | なし |
| `komachi gmo-import --symbol SYMBOL --start DATE --end DATE` | GMO コインの公開データから取り込み | なし |

残数を消費するのは `download` と `manifest` のみです。
market-day は 1 マーケットの 1 日分で、同じ日の板と約定を合わせて 1 と数えます。

### ローカル操作

手元のファイルだけを参照します。通信も残数の消費もありません。

| コマンド | 内容 |
|---|---|
| `komachi local` | 保存済みファイルの一覧 |
| `komachi trades --market MARKET --date DATE` | 約定データの表示 |
| `komachi book --market MARKET --date DATE` | 最良気配とスプレッドの表示 |
| `komachi stats --path PATH` | 行数と時間範囲 |
| `komachi decode --path PATH` | スキーマと先頭数行 |
| `komachi duckdb` | DuckDB のビューを作成・更新 |
| `komachi sql` | ビュー定義の SQL を出力 |

## 保存先の構成

データは、収集時と同じ Hive 形式のディレクトリに保存されます。

```text
$KQL_ROOT_PATH/bronze/dataset=Trade/exchange=GMO/symbol=BTC_JPY/date=2026-01-15/data.parquet
```

DuckDB、PyArrow、Spark、Athena のいずれも `dataset`・`exchange`・`symbol`・`date` を
パスから列として認識します。1 年分でも次の 1 行で読み込めます。

```sql
SELECT * FROM read_parquet('~/kql-data/bronze/dataset=Trade/**/*.parquet', hive_partitioning = 1);
```

## 日付の扱い

`date=` は**日本時間の 1 日**です。`date=2026-01-15` は 2026-01-15 00:00〜23:59 JST、
UTC では 2026-01-14 15:00〜2026-01-15 14:59 にあたります。
ファイル内のタイムスタンプは UTC エポック秒のため、実行環境のタイムゾーンに依存しません。

取り込み元の日付区切りは取引所ごとに異なります。
Binance Vision は 00:00 UTC、GMO コインは取引日の切り替えである 21:00 UTC を基準としています。
Komachi は取り込み時に日本時間の日付へ再分割するため、
有償データと無償データを同じ基準で比較できます。

このため、ある 1 日を取り込むには前日分の元ファイルも必要です。
どちらか一方しか取得できない日は、不完全なまま書き出さずに保留します。

## 設定

| 項目 | 保存場所 |
|---|---|
| データの保存先、API の URL | 実行ディレクトリの `.env` |
| 購入トークン | `~/.komachi/config.json`（パーミッション 0600） |

トークンを `.env` に置かないのは、データディレクトリをそのまま
バージョン管理下に置いても資格情報が混入しないようにするためです。

## 依存関係

最小構成では `httpx` のみです。
Parquet を扱う機能（取り込み、DuckDB 連携、ファイル検査）は `duckdb` エクストラに含まれます。

```bash
pip install komachi              # 取得のみ
pip install 'komachi[duckdb]'    # 取得、取り込み、分析
```

## Komachi が行わないこと

1. 取引所 API への直接接続。接続先はオブジェクトストレージ、Binance Vision、GMO コインの公開データのみです。
2. データの加工・導出。silver 以降は [Hase](https://github.com/kamakuraquantlab) が担当します。
3. Kamakura Quant Lab の API 以外に対する資格情報の保持。

## ライセンス

Apache License 2.0。[LICENSE.md](LICENSE.md) をご覧ください。
