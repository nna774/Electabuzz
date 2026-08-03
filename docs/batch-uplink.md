# batch-uplink: 共通ライブラリの切り出し

## 実コードの調査結果: 流用境界

### そのまま使える (改造ゼロ)

| 対象 | 根拠 |
|---|---|
| [firmware/lib/Uploader/Uploader.h](../../NamazuHaUrokoGaNai/firmware/lib/Uploader/Uploader.h) | **完全にフォーマット非依存**。`Batch*` を受け取り `bytes()`/`size()` を POST するだけ。キュー・LittleFS退避・指数バックオフ・バックフィルの全機構が無改造で効く |
| [firmware/lib/Uploader/HmacSha256.h](../../NamazuHaUrokoGaNai/firmware/lib/Uploader/HmacSha256.h) | 署名はボディのバイト列にしか依存しない |
| [firmware/lib/TimeSync/](../../NamazuHaUrokoGaNai/firmware/lib/TimeSync/) | `batch_start_us` は UTC で要るので NTP は引き続き必要。PPS 規正とは役割が別 |
| [firmware/lib/Display/](../../NamazuHaUrokoGaNai/firmware/lib/Display/) | **参考にするが共有しない。** `ClassFont.h` が震度クラス専用の字形テーブル。Electabuzz 側で作り直す |
| [lambda/common/auth.py](../../NamazuHaUrokoGaNai/lambda/common/auth.py) | `verify(device_id, body, sig)` はボディ非依存。`NAMZ_HMAC_SECRET_<id>` で個体別鍵も既に対応済み |
| [lambda/common/devices.py](../../NamazuHaUrokoGaNai/lambda/common/devices.py) + watchdog | `record_batch()` はセンサ種別に依存しない。死活監視が device_id 追加だけで効く |
| [lambda/common/events.py](../../NamazuHaUrokoGaNai/lambda/common/events.py) / notify.py | `device_prompt`/`cloud_confirmed`/`checked`/`artificial` の状態機械をそのまま使う |

### 一般化が必要 (具体箇所)

**1. `Batch` をレイアウト非依存にする (v1.1.0 で行う)**

現状の `Batch` はワイヤ形式を2箇所で知っている。

- レコード長が6バイト固定 — [Batch.h:42](../../NamazuHaUrokoGaNai/firmware/lib/Batch/Batch.h#L42)
  `kSampleBytes = 3 * sizeof(int16_t)`、[Batch.h:25](../../NamazuHaUrokoGaNai/firmware/lib/Batch/Batch.h#L25)
  `addSample(int16_t x, int16_t y, int16_t z)`、
  [Batch.cpp:24](../../NamazuHaUrokoGaNai/firmware/lib/Batch/Batch.cpp#L24) `h.axes = 3`
- ヘッダを組み立て、**offset 20 に `sample_count` を書き戻す** —
  [Batch.cpp:45](../../NamazuHaUrokoGaNai/firmware/lib/Batch/Batch.cpp#L45)

共有ライブラリに入れるなら、**ワイヤ形式の知識を `Batch` から完全に抜く**のが正しい。

```
Batch(capacityRecords, recordBytes, headerBytes)   ← 先頭に headerBytes を予約するだけ
begin(startUs)                                      ← 順序付けに使う startUs のみ保持
addRecord(const void* rec, size_t len)              ← 固定長レコードを追記
headerPtr()                                         ← 送信直前に呼び出し側がヘッダを書く
bytes() / size()                                    ← 純粋な getter。書き戻しをしない
```

こうすると `Batch` は「ヘッダ領域を予約した固定長レコードのバッファ」になり、
**どんなワイヤ形式でも載る。** 両プロジェクトが同じバージョンを安全に共有できる。

**2. 「先頭32バイトを変えるな」という制約は存在しない (初期版の誤り)**

> **訂正**: 本設計書の初期版は「`fromBytes()` が offset 8/20 を直読みするので v1 の32バイト
> ヘッダを維持し後ろに拡張ヘッダを追記せよ」と書いていた。**これは誤りだった。**

[Batch::fromBytes](../../NamazuHaUrokoGaNai/firmware/lib/Batch/Batch.cpp#L49-L65) は
**呼び出し元がゼロの死んだコード**である(`src`/`lib` 全体を grep して確認)。

LittleFS 退避・復元の実際の経路はこうなっている。

- 退避: [Uploader.cpp:142-147](../../NamazuHaUrokoGaNai/firmware/lib/Uploader/Uploader.cpp#L142-L147)
  — `b->bytes(), b->size()` を **`startUs` を20桁ゼロ埋めしたファイル名**で書く
- 復元: [Uploader.cpp:58-64](../../NamazuHaUrokoGaNai/firmware/lib/Uploader/Uploader.cpp#L58-L64)
  — ファイルを生バイト列に読んで **`postBatch(body, len)` へ直接渡す。`Batch` を再構築しない**
- 順序: [Uploader.cpp:168](../../NamazuHaUrokoGaNai/firmware/lib/Uploader/Uploader.cpp#L168)
  — `startUs` は**ファイル名から `strtoull`** で復元。ヘッダをパースしない

**つまり退避・復元機構は既に完全にフォーマット非依存であり、ヘッダのレイアウトに
一切依存していない。** 上記1で `bytes()` の書き戻しを廃せば、`Batch` からワイヤ形式の
知識が完全に消え、**Electabuzz は自由にヘッダを設計できる。**

`fromBytes` は共有ライブラリに持ち込まず削除する(死んだコードを共有資産にする理由はない)。

**3. `wire.py` は触らない — 別実装にする**

[wire.py:51](../../NamazuHaUrokoGaNai/lambda/common/wire.py#L51) で
`if axes != 3: raise ValueError`、[wire.py:71](../../NamazuHaUrokoGaNai/lambda/common/wire.py#L71)
で `gal = raw * scale * MG_TO_GAL` を無条件に計算している。

当初これを `sensor_type` で分岐させる案にしていたが、**AWSスタックを分ける方針(後述)に伴い、
`wire.py` は一切触らないことにした。** Electabuzz 側に `wire_gridfreq.py` を独立に書く。

- 動いている地震計のパース経路に手を入れないので、**回帰リスクがゼロになる**
- ヘッダのレイアウト(`HEADER_FMT = "<IBBBBQIIfI"`)は仕様として共有するが、
  コードは共有しない。32バイト固定の単純な構造なので二重実装の費用は小さい
- [wire.py:37-40](../../NamazuHaUrokoGaNai/lambda/common/wire.py#L37-L40) の
  `timestamps_us()`(= `batch_start_us + i/sample_rate_hz`)は**式として踏襲する**。
  だから `sample_rate_mhz` には出力レコードレートを入れる(v2 の設計参照)

同じ理由で `store.py`(`b.gal` 前提)・`detect_core.py`・`quicklook.py`・`jismo/` も触らない。

**4. S3キーの命名規約は「仕様として」踏襲する**

[s3util.py:16-20](../../NamazuHaUrokoGaNai/lambda/common/s3util.py#L16-L20) の
`{device:04d}-{batch_start_us:020d}.bin` という命名は、**20桁ゼロ埋めゆえに辞書順
= 時系列順**になっており、[store.py:32](../../NamazuHaUrokoGaNai/lambda/common/store.py#L32)
と [store.py:55](../../NamazuHaUrokoGaNai/lambda/common/store.py#L55) の `keys.sort()`
がそれに依存している。**この規約は Electabuzz 側でも必ず踏襲する**(コードは別実装でよい)。

**5. 環境変数駆動なのでスタック分離が無償で効く (重要な発見)**

[devices.py:30](../../NamazuHaUrokoGaNai/lambda/common/devices.py#L30) はテーブル名を
`os.environ["NAMZ_DEVICES_TABLE"]` から取り、[notify.py:72-79](../../NamazuHaUrokoGaNai/lambda/common/notify.py#L72-L79)
`from_env()` も `NAMZ_NOTIFIER` / `NAMZ_SLACK_WEBHOOK_URL` / `NAMZ_SLACK_CHANNEL` /
`NAMZ_DASHBOARD_URL` を全て env から読む。`auth.py` も `NAMZ_HMAC_SECRET_<id>`。

**つまり別テーブル・別チャンネル・別ダッシュボードを指すだけで、コード無改造のまま
別スタックとして動く。** 分離の代償がほぼゼロというのは、この設計のおかげだ。

### 使わない

`lib/Shindo/`、`lib/Iis3dhhc/`、`lib/AccelSensor/`、`tools/jismo/`。

特に **`AccelSensor` 抽象に周波数センサを載せてはいけない。**
[AccelSensor.h](../../NamazuHaUrokoGaNai/firmware/lib/AccelSensor/AccelSensor.h)
は `read(AccelSample&)` で3軸LSBを返す契約で、`scaleMgPerLsb()` を持つ。
周波数測定は「48kHzのDMAストリームから1Hzの累積位相を出す」処理であり、
サンプル1個を返すインターフェイスに収まらない。別系統として作る。

---

### 構成: 共通コードを独立レポジトリに切り出し、AWSスタックも分ける (方針決定)

**3レポジトリ + 2スタック。** 共通部分は NamazuHaUrokoGaNai から切り出して
バージョン付きの独立レポジトリにし、両者が**タグで pin して参照する**。

```
batch-uplink/                        ← 新規。共通ライブラリ。git tag でバージョンを切る
├── library.json                 PlatformIO ライブラリ manifest (deps: ArduinoJson)
├── src/                         C++: Batch/WireFormat, Uploader/HmacSha256, TimeSync
├── pyproject.toml               pip インストール可能にする
└── batch_uplink/                Python: auth, devices, notify, s3util (パッケージ名は _ 区切り)
                                 ※ 全て stdlib + boto3 のみ。numpy 不要

NamazuHaUrokoGaNai/              ← 既存。地震計。batch-uplink v1.0.0 に pin
├── firmware/  lib/Display, lib/Shindo, lib/Iis3dhhc, lib/AccelSensor  ← 地震計専用
├── lambda/    wire, store, detect_core, quicklook, events            ← 地震計専用
├── tools/jismo/
└── terraform/                   ← 既存スタック。触らない

Electabuzz/                        ← 新規。周波数モニタ。batch-uplink v1.1.0 に pin
├── firmware/  lib/GridFreq (Goertzel + PPS規正), src/main.cpp
├── lambda/    wire_gridfreq, ingest, detect, rollup, api
├── tools/gridfreq/              参照実装 + backtest
└── terraform/                   ← 新規スタック。独立 state / bucket / tables
```

**なぜ独立レポが単一レポより良いか。** 単一レポ案には未解決の弱点が残っていた
(下記「ソース互換性」の節)。共通コードを変更すると、AWSスタックを分けていても
**地震計のソースが動く**ので再ビルド・再検証の対象になってしまう。

**タグで pin する独立レポならこれが消える。** 地震計は v1.0.0 に留まり続け、
Electabuzz のために共通コードを変えてもソースレベルで一切影響しない。
特に **`Batch` の一般化リスクが丸ごと消滅する**(v1.1.0 でやればよく、地震計を
焼き直す必要すらない)。

#### 切り出せる面は最初から綺麗に切れている (実測)

`lambda/common/` の相互依存を調べた結果:

| モジュール | 内部import | numpy | 判定 |
|---|---|---|---|
| `auth.py` | なし | 不要 | **切り出す** |
| `devices.py` | なし | 不要 | **切り出す** |
| `notify.py` | なし | 不要 | **切り出す** |
| `s3util.py` | なし | 不要 | **切り出す**(prefix を引数化) |
| `events.py` | なし | 不要 | **切り出さない。** `max_intensity`/`peak_gal`/`confirmed_intensity` で地震に染まっている |
| `wire.py` / `store.py` / `detect_core.py` / `quicklook.py` | あり | **要** | 切り出さない |

**切り出す4つは相互 import ゼロ・stdlib + boto3 のみ。** numpy に依存しないので
platform wheel の問題が発生せず、pip 配布が極めて単純になる。

C++ 側も同様に切り分ける。

| 対象 | 判定 |
|---|---|
`lib/Uploader/`(+`HmacSha256.h`) | **切り出す。** 完全にフォーマット非依存 |
`lib/Batch/`(+`WireFormat.h`) | **切り出す。** レコード長可変化はここで行う |
`lib/TimeSync/` | **切り出す。** NTP は汎用 |
`lib/Display/` | **切り出さない。** `ClassFont.h` が580行の震度クラス字形で、TFT_eSPI にも依存する |
`lib/Shindo/` `lib/Iis3dhhc/` `lib/AccelSensor/` | 地震計専用 |

> **訂正**: 本設計書の初期版は `lib/Display` を共有対象に挙げていたが、実物を見たら
> 震度クラス専用の字形テーブルだった。**過剰に切り出すな**というのが教訓だ。

#### 参照の機構

**C++ (PlatformIO)** — [platformio.ini:38-40](../../NamazuHaUrokoGaNai/firmware/platformio.ini#L38-L40)
が既に `lib_deps` を使っているので、git URL をタグ付きで足すだけ。

```ini
lib_deps =
    bblanchon/ArduinoJson @ ^7.0.0
    bodmer/TFT_eSPI @ ^2.5.43
    https://github.com/nna774/batch-uplink.git#v1.0.0    ; ← タグで pin
```

共有レポ側に `library.json` を置き、`ArduinoJson` への依存を宣言する
(`Uploader` がアラートJSONの生成に使っている)。

**Python (Lambda)** — [build_lambda.sh:29-33](../../NamazuHaUrokoGaNai/terraform/build_lambda.sh#L29-L33)
が既に `pip install --target "$stage"` でzipへ同梱している。ここに1行足すだけ。

```bash
# 既存: numpy/Pillow を manylinux wheel 指定で取る
"$PY" -m pip install --target "$stage" \
  --platform manylinux2014_x86_64 --only-binary=:all: \
  --implementation cp --python-version 3.12 --abi cp312 numpy $extra_pkgs

# 追加: 共通ライブラリは pure Python なので別呼び出しにする
"$PY" -m pip install --target "$stage" --no-deps \
  "git+https://github.com/nna774/batch-uplink@v1.0.0"
```

> **必ず pip を2回に分けること。** `--platform` は `--only-binary=:all:` を要求するが、
> `git+` はソースツリーなので binary only と両立しない。同一呼び出しに混ぜると失敗する。
> 共通ライブラリが numpy に依存しない(前述)おかげで、この分離が成立している。

代替として git submodule + `cp -r`(現行の `cp -r "$LAMBDA/common"` と同形)でも動くが、
**タグの方が「今どの版か」が `requirements.txt` 上で読めるので pip を推す。**
submodule の SHA は版として読めない。

#### AWSスタック分離で得られるもの

| 論点 | 分離した場合 |
|---|---|
| **`aws_s3_bucket_notification` の上書き事故** | **問題自体が消滅する。** バケットが別なので単一リソース制約に当たらない |
| blast radius | `terraform apply` が地震計を壊しえない。**稼働中の24/7システムを触らずに済む** |
| lifecycle | 新バケットでは `series/` を無期限のデフォルトにし、`raw/` にだけ expire を掛ける。既存ルールを迂回する必要がない |
| env / IAM | `local.common_env`(Slack, Gyazo token, detect閾値)を汚さない |
| watchdog 閾値 | 周波数モニタは停電で落ちる。**地震計より速く鳴らしたい**ので独立に調整できるのが正しい |
| Slack | 別チャンネルに出せる。地震と電力は緊急度のプロファイルが違う |
| 追加コスト | **実質ゼロ。** S3 はバケット単位の課金がなく、Lambda はアイドル課金がない |

分離しても失わないもの:

- **`devices.py` / `notify.py` / `auth.py` は env 駆動なので無改造で再利用できる**
  (前述の発見)。`NAMZ_DEVICES_TABLE=electabuzz-devices` を渡すだけ
- watchdog Lambda・EventBridge ルール・Function URL・ダッシュボードは
  [lambda.tf](../../NamazuHaUrokoGaNai/terraform/lambda.tf) の形をそのまま複製する

### 切り出しの順序 (絶対に守ること)

**バイト等価な移動と、意味の変更を、同じ手順で混ぜてはならない。**

1. **共有レポを作り、対象を「一文字も変えずに」移す。** `Batch` の一般化はまだしない
2. NamazuHaUrokoGaNai を `lib_deps` / `requirements.txt` で **v1.0.0 に pin** する
3. `pytest lambda/tests` `pytest tools/tests` が緑、**かつ実機を焼き直してバッチが
   従来通り着弾する**ことを確認する。ここが切り出しの唯一の検証点
4. 動いたら **v1.0.0 をタグで固定。地震計はもうここから動かさない**
5. **その後で**共有レポ側に `Batch` のレコード長可変化を入れ、**v1.1.0** を切る
6. Electabuzz は v1.1.0 を参照する。地震計は v1.0.0 のまま**一切触らない**

この順序を守れば、`Batch` 一般化が地震計を壊す可能性は**存在しなくなる**。
逆に順序を崩して「移動と一般化を同時にやる」と、実機で異常が出たときに
移動のせいか一般化のせいか切り分けられなくなる。

### タグで pin しろ。ブランチ追従にするな

**これが独立レポ構成における唯一の落とし穴だ。**

`lib_deps` や `requirements.txt` を `#main` や `@main` のようにブランチ追従にすると、
Electabuzz のために共有レポへ入れた変更が、**地震計の次回ビルドで黙って混入する。**

これは単一レポより悪い。単一レポなら変更が同じ diff に見えるが、ブランチ追従では
**結合が不可視**になる。「動いていたものが、何も変えていないのに再ビルドで壊れる」
という最悪の壊れ方をする。

- `lib_deps = ...git#v1.0.0` — **タグ**を指す
- `requirements.txt` に `git+https://.../batch-uplink@v1.0.0` — **タグ**を指す
- 共有レポ側で **タグを打ち替えない**(打ち替えたら pin の意味が消える)

---

## レポジトリ配置

**3レポジトリ + 2スタック。** 前掲のディレクトリ構成を参照。要点だけ再掲する。

- **`batch-uplink`**: C++ は `Batch`/`WireFormat`・`Uploader`/`HmacSha256`・`TimeSync`。
  Python は `auth`・`devices`・`notify`・`s3util`。**これ以上は入れるな。**
  ドメインが混ざった瞬間に共有ライブラリとしての価値が消える
- **`NamazuHaUrokoGaNai`**: `batch-uplink` v1.0.0 に pin。以後この pin を動かさない
- **`Electabuzz`**: `batch-uplink` v1.1.0 に pin。`lib/GridFreq/`(Goertzel + PPS規正)、
  `wire_gridfreq`、`tools/gridfreq/`(参照実装 + backtest)、独立 Terraform state
- **ワイヤ形式は `batch-uplink` に入れない。** `Batch` がレイアウト非依存になるので、
  ヘッダ定義・magic・`SensorType` 相当の enum はすべてプロジェクト固有になる。
  地震計は `NAMZ` v1、Electabuzz は `GFRQ` v1 を各々のレポで持つ

**「ナマズ」というドメイン名との齟齬が、この構成では解消する。** 単一レポ案では
地震計のレポに電力の話が同居する不自然さが残ったが、共通部分を `batch-uplink` に抜けば
NamazuHaUrokoGaNai は地震計のままでいられる。**これも独立レポ案の利点だ。**

[design.md](../../NamazuHaUrokoGaNai/docs/design.md) の「デバイスマニフェストを単一の
真実にする」構想(152-167行目)は、**スタックが2つになり HMAC 秘密の登録先も2つになるので
より価値が上がる。** ただしマニフェスト自体は各プロジェクト固有(device_id の払い出しは
プロジェクト単位)なので、**`batch-uplink` には入れない**。生成スクリプトの雛形を共有したく
なった時点で改めて考えればよい。

---

