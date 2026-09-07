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

## できること

| コマンド | 内容 |
|---|---|
| `komachi auth login --token TOKEN` | トークンを検証して保存 |
| `komachi status` | 残数、使用済み数、有効期限 |
| `komachi markets` | 利用できるマーケットと、無償公開元の案内 |
| `komachi calendar --market MARKET` | 公開済みの日付と、取得済みの日付 |
| `komachi catalog --market MARKET` | 日ごとの収録状況と品質 |
| `komachi download --market MARKET --start DATE [--days N]` | 範囲を指定して取得（中断後は再開） |
| `komachi trades --market MARKET --date DATE` | 約定データの表示 |
| `komachi book --market MARKET --date DATE` | 最良気配とスプレッドの表示 |
| `komachi binance-import --symbol SYMBOL --start DATE --end DATE` | Binance Vision から取り込み |
| `komachi gmo-import --symbol SYMBOL --start DATE --end DATE` | GMO コインの公開データから取り込み |
| `komachi local` | 手元にあるファイルの一覧 |
| `komachi duckdb` | DuckDB のビューを作成・更新 |
| `komachi sql` | ビュー定義の SQL を出力 |
| `komachi stats --path PATH` | 行数と時間範囲 |
| `komachi decode --path PATH` | スキーマと先頭数行 |

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
