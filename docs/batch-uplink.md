# batch-uplink: 共通ライブラリの切り出し

> **状態（2026-08-23）**: **切り出しは完了し、以後 Namazu 側で18回タグを切っている。**
> [batch-uplink](https://github.com/nna774/batch-uplink) が public で立ち `v1.0.0` が打たれた
> のが最初。**Electabuzz の現在の pin は `v3.1.0`。** 各プロジェクトはタグさえ固定していれば
> 自分が使いたい機能を含む版を指すだけでよく、**相手が今どのタグを指しているかはそもそも
> 気にする必要が無い**（下記「タグで pin しろ」参照。ブランチ追従さえしていなければ
> 相手の変更が黙って混ざることは無い）。`v3.1.0`は`devices.record_batch()`に
> Electabuzz detect固有のオプトイン引数`track_prev_key`を足した版で、Namazu側は
> 使わない(デフォルトFalseで挙動不変)ため今回タグを追従していないが、それは
> 特筆すべき事態ではない。経緯は
> [log/2026-08-23-detect-listobjectsv2-cost-and-prev-batch-key-design.md](log/2026-08-23-detect-listobjectsv2-cost-and-prev-batch-key-design.md)。
> `v1.1.0`〜`v2.12.0` はいずれも Namazu が OTA・リモート再起動・生存台帳表示・実機で踏んだ
> 障害(WDTパニックでの取りこぼし、ヒープ断片化)の対策のために追加したもので、
> `v1.x` は全て `Uploader` の新規オプトイン引数(既定値で従来どおり)か新規メソッドだった。
> `v2.0.0` だけは例外で、ヘッダ配列を固定長+本数引数からnullptr終端方式へ変える
> **破壊的変更**が入っている(4本上限の撤廃と引き換え)。呼び出し側の書き換えが要るが、
> ロジックは変わらない機械的な変更で済む。
> **`v1.6.0`→`v2.12.0`への追従（2026-08-11）で、Electabuzzも次を取り込んだ**:
> `v2.3.0`のTLSハンドシェイクタイムアウト短縮（既定120秒はtask watchdogより長く、
> ネット瞬断でハンドシェイクが詰まるとWDTパニックで`flushToSpill()`を経由せず
> RAM上のバッチを失う——Namazu実機の事故が動機。Electabuzzは`Uploader::pump()`を
> 専用taskではなく`loop()`から直接呼んでいるため同じ壊れ方をしうる）、
> `v1.8.0`のCA証明書ピン留め（OTA用に埋め込み済みのAmazon Root CA1を`caCert`引数で
> 流用し`setInsecure()`を卒業）、`discardSpillOn400`（電源断で0バイト/途中で切れた
> 退避ファイルを隔離——測定対象の電源そのものに給電されている機体なので実益がある。
> `lambda/ingest/handler.py`は該当ケースを`CrcMismatch`以外の`WireFormatError`として
> 既に400で返しており、ingest側の変更は不要だった）。詳細は
> [log/2026-08-11-batch-uplink-v2.12.0-bump.md](log/2026-08-11-batch-uplink-v2.12.0-bump.md)。
> **焼き直し(実機投入)はまだ**——ホストテスト・`pio run`のビルド確認のみ済み。
> 最初の切り出しの経緯は [log/2026-08-03-batch-uplink-v1.0.0.md](log/2026-08-03-batch-uplink-v1.0.0.md)、
> Electabuzz が pin を v1.6.0 へ上げた経緯は
> [log/2026-08-07-goertzel-cpp-port.md](log/2026-08-07-goertzel-cpp-port.md)。

```ini
lib_deps = https://github.com/nna774/batch-uplink.git#v3.1.0
```
```bash
pip install "git+https://github.com/nna774/batch-uplink@v3.1.0"
```

## 実コードの調査結果: 流用境界

### そのまま使える (改造ゼロ)

| 対象 | 根拠 |
|---|---|
| [firmware/lib/Uploader/Uploader.h](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/lib/Uploader/Uploader.h) | **完全にフォーマット非依存**。`Batch*` を受け取り `bytes()`/`size()` を POST するだけ。キュー・LittleFS退避・指数バックオフ・バックフィルの全機構が無改造で効く |
| [firmware/lib/Uploader/HmacSha256.h](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/lib/Uploader/HmacSha256.h) | 署名はボディのバイト列にしか依存しない |
| [firmware/lib/TimeSync/](https://github.com/nna774/NamazuHaUrokoGaNai/tree/master/firmware/lib/TimeSync/) | `batch_start_us` は UTC で要るので NTP は引き続き必要。PPS 規正とは役割が別 |
| [firmware/lib/Display/](https://github.com/nna774/NamazuHaUrokoGaNai/tree/master/firmware/lib/Display/) | **参考にするが共有しない。** `ClassFont.h` が震度クラス専用の字形テーブル。Electabuzz 側で作り直す |
| [lambda/common/auth.py](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/auth.py) | `verify(device_id, body, sig)` はボディ非依存。`NAMZ_HMAC_SECRET_<id>` で個体別鍵も既に対応済み |
| [lambda/common/devices.py](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/devices.py) + watchdog | `record_batch()` はセンサ種別に依存しない。死活監視が device_id 追加だけで効く |
| [lambda/common/notify.py](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/notify.py) | `Notifier` 抽象と Slack 実装。通知先は全て env 駆動。**`events.py` は切り出さない**(下記) |

**Electabuzzでもspool/retry機構は無改造でそのまま効いている**（`firmware/platformio.ini`で
`batch-uplink.git#v3.1.0`をpinし、`firmware/src/main.cpp`で`Uploader`を生成・`enqueue()`/
`pump()`を呼ぶだけ。独自実装は無い）。**保持できる期間はNamazuより長い**（概算、実機未検証）。
`firmware/platformio.ini`は`board_build.partitions = default_16MB.csv`（Arduino既定の
16MB分割）を使っており、spiffs領域は`0x360000`＝約3.375MB。GFRQは64Bヘッダ+12B×30レコード
＝424バイトを30秒間隔で送る(≈14.1B/s)ので、**3.375MB ÷ 14.1B/s ≈ 69.6時間（約2.9日）**
ぶん退避できる計算になる。Namazuが168.8分（16MBへ拡張後）で済んでいるのは加速度計の
データレートが87倍(≈1229B/s)高いためで、Electabuzzは独自にpartition tableを切らずとも
既定のままで長時間の退避が効く。

**ただし `Uploader` のうち速報経路 `sendAlert()` だけは地震に染まっていた**
(`realtime_intensity` / `peak_gal` / `kind:"device_prompt"` がベタ書き)。v1.0.0 では剥がしてあり、
**本文は呼び出し側が組む**。

```cpp
bool sendAlert(const char* json, size_t len);
```

**Electabuzz は速報の JSON を自由に設計できる。** 系統時刻偏差の飛びを速報するならこちらで組む。
バッチ送信・退避・バックフィルの側は宣言どおり無改造で効いた。

### 一般化が必要 (具体箇所)

**1. `Batch` をレイアウト非依存にする (v1.0.0 で完了)**

切り出し前の `Batch` はワイヤ形式を2箇所で知っていた。

- レコード長が6バイト固定 — [Batch.h:42](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/lib/Batch/Batch.h#L42)
  `kSampleBytes = 3 * sizeof(int16_t)`、[Batch.h:25](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/lib/Batch/Batch.h#L25)
  `addSample(int16_t x, int16_t y, int16_t z)`、
  [Batch.cpp:24](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/lib/Batch/Batch.cpp#L24) `h.axes = 3`
- ヘッダを組み立て、**offset 20 に `sample_count` を書き戻す** —
  [Batch.cpp:45](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/lib/Batch/Batch.cpp#L45)

共有ライブラリに入れるなら、**ワイヤ形式の知識を `Batch` から完全に抜く**のが正しい。
こうすると `Batch` は「ヘッダ領域を予約した固定長レコードのバッファ」になり、
**どんなワイヤ形式でも載る。** 両プロジェクトが同じバージョンを安全に共有できる。

**確定した契約 (v1.0.0)。** 設計時の案から `finalize()` が無くなり、
`records()`/`recordsSize()`/`tailRemaining()` が増えている。**`GFRQ` を載せる相手はこれだ。**

```cpp
Batch(uint32_t capacityRecords, size_t recordBytes, size_t headerBytes,
      size_t tailCapacity = 0);

void   begin(uint64_t startUs);                  // 順序付けの startUs のみ保持
bool   addRecord(const void* rec, size_t len);   // len != recordBytes なら false
bool   appendTail(const void* data, size_t len);
size_t tailRemaining() const;                    // 分割して書く前の総量確認用

uint8_t*       headerPtr();                      // ここへ呼び出し側がヘッダを書く
const uint8_t* records() const;                  // ← CRC 計算に要る
size_t         recordsSize() const;
uint32_t       recordCount() const;
size_t         recordBytes() const;
uint64_t       startUs() const;
bool           isFull() const;

const uint8_t* bytes() const;                    // 純粋な getter
size_t         size() const;
```

**`bytes()` を「書き戻しをしない純粋な getter」にするという設計は実現できた。**
tail を `addRecord()` のたびに1レコード分だけ後ろへ `memmove` で押し出す形にしたので、
バッファはいつ見ても完結したバイト列になり、**確定用の呼び出しを忘れるという失敗の形が
そのものとして消えている**。費用は tail 長ぶんの memmove だけ(Namazu の実測で
6バイト × 1500レコード/バッチ)で無視できる。

**ヘッダを書く時期は「レコードを積み終えた後・`Uploader` へ渡す前」。** その時点で
`recordCount()` も `records()` も確定しているので、`record_count` も `crc32` もここで書ける。
Namazu は `lib/NamzWire` という薄い層でこれをやっており、`lib/GridFreq` も同じ形にする。
**`GFRQ` の寸法(64Bヘッダ + 12Bレコード + tail なし)がそのまま載ることは Namazu 側のテストで
確認済み** — `Batch(3, 12, 64, 0)` でヘッダが書けてレコードが侵されないこと、レコード長違いが
拒否されることまで見てある。

**2. 「先頭32バイトを変えるな」という制約は存在しない**

[Batch::fromBytes](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/lib/Batch/Batch.cpp#L49-L65) は
**呼び出し元がゼロの死んだコード**である(`src`/`lib` 全体を grep して確認)。

LittleFS 退避・復元の実際の経路はこうなっている。

- 退避: [Uploader.cpp:142-147](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/lib/Uploader/Uploader.cpp#L142-L147)
  — `b->bytes(), b->size()` を **`startUs` を20桁ゼロ埋めしたファイル名**で書く
- 復元: [Uploader.cpp:58-64](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/lib/Uploader/Uploader.cpp#L58-L64)
  — ファイルを生バイト列に読んで **`postBatch(body, len)` へ直接渡す。`Batch` を再構築しない**
- 順序: [Uploader.cpp:168](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/lib/Uploader/Uploader.cpp#L168)
  — `startUs` は**ファイル名から `strtoull`** で復元。ヘッダをパースしない

**つまり退避・復元機構は既に完全にフォーマット非依存であり、ヘッダのレイアウトに
一切依存していない。** 上記1で `bytes()` の書き戻しを廃せば、`Batch` からワイヤ形式の
知識が完全に消え、**Electabuzz は自由にヘッダを設計できる。**

`fromBytes` は共有ライブラリに持ち込まず削除する(死んだコードを共有資産にする理由はない)。

**3. `wire.py` は触らない — 別実装にする**

[wire.py:51](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/wire.py#L51) で
`if axes != 3: raise ValueError`、[wire.py:71](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/wire.py#L71)
で `gal = raw * scale * MG_TO_GAL` を無条件に計算している。

当初これを `sensor_type` で分岐させる案にしていたが、**AWSスタックを分ける方針(後述)に伴い、
`wire.py` は一切触らないことにした。** Electabuzz 側に `wire_gridfreq.py` を独立に書く。

- 動いている地震計のパース経路に手を入れないので、**回帰リスクがゼロになる**
- ヘッダのレイアウト(`HEADER_FMT = "<IBBBBQIIfI"`)は仕様として共有するが、
  コードは共有しない。32バイト固定の単純な構造なので二重実装の費用は小さい
- [wire.py:37-40](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/wire.py#L37-L40) の
  `timestamps_us()`(= `batch_start_us + i/sample_rate_hz`)は**式として踏襲する**。
  だから `sample_rate_mhz` には出力レコードレートを入れる(v2 の設計参照)

同じ理由で `store.py`(`b.gal` 前提)・`detect_core.py`・`quicklook.py`・`jismo/` も触らない。

**4. S3キーの命名規約は「仕様として」踏襲する**

[s3util.py:16-20](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/s3util.py#L16-L20) の
`{device:04d}-{batch_start_us:020d}.bin` という命名は、**20桁ゼロ埋めゆえに辞書順
= 時系列順**になっており、[store.py:32](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/store.py#L32)
と [store.py:55](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/store.py#L55) の `keys.sort()`
がそれに依存している。**この規約は Electabuzz 側でも必ず踏襲する**(コードは別実装でよい)。

**5. 環境変数駆動なのでスタック分離が無償で効く (重要な発見)**

[devices.py:30](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/devices.py#L30) はテーブル名を
`os.environ["NAMZ_DEVICES_TABLE"]` から取り、[notify.py:72-79](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/notify.py#L72-L79)
`from_env()` も `NAMZ_NOTIFIER` / `NAMZ_SLACK_WEBHOOK_URL` / `NAMZ_SLACK_CHANNEL` /
`NAMZ_DASHBOARD_URL` を全て env から読む。`auth.py` も `NAMZ_HMAC_SECRET_<id>`。

**つまり別テーブル・別チャンネル・別ダッシュボードを指すだけで、コード無改造のまま
別スタックとして動く。** 分離の代償がほぼゼロというのは、この設計のおかげだ。

### 使わない

`lib/Shindo/`、`lib/Iis3dhhc/`、`lib/Adxl355/`、`lib/AccelSensor/`、`lib/NamzWire/`、`tools/jismo/`。

特に **`AccelSensor` 抽象に周波数センサを載せてはいけない。**
[AccelSensor.h](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/lib/AccelSensor/AccelSensor.h)
は `read(AccelSample&)` で3軸LSBを返す契約で、`scaleMgPerLsb()` を持つ。
周波数測定は「48kHzのDMAストリームから1Hzの累積位相を出す」処理であり、
サンプル1個を返すインターフェイスに収まらない。別系統として作る。

---

### 構成: 共通コードを独立レポジトリに切り出し、AWSスタックも分ける (方針決定)

**3レポジトリ + 2スタック。** 共通部分は NamazuHaUrokoGaNai から切り出して
バージョン付きの独立レポジトリにし、両者が**タグで pin して参照する**。

```
batch-uplink/                        ← 共通ライブラリ。git tag でバージョンを切る (v1.0.0)
├── library.json                 PlatformIO ライブラリ manifest (**依存ゼロ**)
├── src/                         C++: Batch, Uploader/HmacSha256, TimeSync
├── test/                        ホストの g++ で回る単体テスト
├── pyproject.toml               pip インストール可能にする
└── batch_uplink/                Python: auth, devices, notify, s3util (パッケージ名は _ 区切り)
                                 ※ 全て stdlib + boto3 のみ。numpy 不要

NamazuHaUrokoGaNai/              ← 既存。地震計。batch-uplink v1.0.0 に pin
├── firmware/  lib/Display, lib/Shindo, lib/Iis3dhhc, lib/Adxl355,
│              lib/AccelSensor, lib/NamzWire (NAMZ v1 のヘッダ)  ← 地震計専用
├── lambda/    wire, store, detect_core, quicklook, events      ← 地震計専用
├── tools/jismo/
└── terraform/                   ← 既存スタック。触らない

Electabuzz/                        ← 新規。周波数モニタ。batch-uplink v1.0.0 に pin
├── firmware/  lib/GridFreq (Goertzel + PPS規正), src/main.cpp
├── lambda/    wire_gridfreq, ingest, detect, rollup, api
├── tools/gridfreq/              参照実装 + backtest
└── terraform/                   ← 新規スタック。独立 state / bucket / tables
```

**なぜ独立レポが単一レポより良いか。** 単一レポ案には未解決の弱点が残っていた
(下記「ソース互換性」の節)。共通コードを変更すると、AWSスタックを分けていても
**地震計のソースが動く**ので再ビルド・再検証の対象になってしまう。

**タグで pin する独立レポならこれが消える。** 地震計は**自分の都合でしか** pin を動かさず、
Electabuzz のために共通コードを変えてもソースレベルで一切影響しない
（実際に v1.1.0〜v1.6.0 は全て Namazu 側の都合で切られた。**「地震計は v1.0.0 に留まり続ける」
という当初の予想は外れたが、それでよい**——独立レポの価値は「片方の変更がもう片方の
ソースを触らずに済む」ことであって、「バージョンが動かない」ことではない）。

#### 切り出せる面は最初から綺麗に切れている (実測)

`lambda/common/` の相互依存を調べた結果:

| モジュール | 内部import | numpy | 判定 |
|---|---|---|---|
| `auth.py` | なし | 不要 | **切り出す** |
| `devices.py` | なし | 不要 | **切り出す** |
| `notify.py` | なし | 不要 | **切り出す** |
| `s3util.py` | なし | 不要 | **切り出す**(prefix は**あえて**引数化していない。下記) |
| `events.py` | なし | 不要 | **切り出さない。** `max_intensity`/`peak_gal`/`confirmed_intensity` で地震に染まっている |
| `wire.py` / `store.py` / `detect_core.py` / `quicklook.py` | あり | **要** | 切り出さない |

**切り出す4つは相互 import ゼロ・stdlib + boto3 のみ。** numpy に依存しないので
platform wheel の問題が発生せず、pip 配布が極めて単純になる。この実測は正しく、
**4つとも一文字も変えずに移せた**。ただし「純汎用」ではない点が2つ残っている。

**あえて汎用化しなかった点が2つある。**

- **env の接頭辞は `NAMZ_` のまま**(`NAMZ_DEVICES_TABLE` / `NAMZ_HMAC_SECRET_<id>` /
  `NAMZ_SLACK_WEBHOOK_URL` / `NAMZ_DASHBOARD_URL` …)。**改名すると稼働中の地震計が壊れる。**
  Electabuzz は `NAMZ_DEVICES_TABLE=electabuzz-devices` のように**自分のスタックの値を
  同じ名前で渡す**。名前の綺麗さと引き換えに実機を止める価値は無い
- **`s3util` の prefix は引数化しない。Electabuzz は `s3util` を使わない方を選ぶ。**
  `RAW_PREFIX = "raw"` / `EVENTS_PREFIX = "events"` はモジュール定数のままにする。
  当初は「別 prefix が要ると確定したら v1.1.0 で引数化する」と考えていたが、
  **prefix は保存方針そのものであって、共有ライブラリの既定に寄りかかってよい種類の
  値ではない**と分かった。Namazu 側の lifecycle は `raw/` に 90日の expire を掛けており、
  永久保存が前提の累積位相をそこへ置くと**設計上永久のはずのデータが90日で消える**。
  しかも気づくのは3ヶ月後だ。**呼び出し側で prefix を名指しさせる方が安全**なので、
  Electabuzz は `lambda/s3keys.py` に自前で持つ(→ [cloud.md](cloud.md))。
  キーの形は共有ライブラリと同一に揃えてあるので、揃える価値のある部分は失われていない

C++ 側も同様に切り分ける。

| 対象 | 判定 |
|---|---|
`lib/Uploader/`(+`HmacSha256.h`) | **切り出す。** 完全にフォーマット非依存 |
`lib/Batch/`(+`WireFormat.h`) | **`Batch` だけ切り出す。** レコード長可変化はここで行う |
`lib/TimeSync/` | **切り出す。** NTP は汎用 |
`lib/Display/` | **切り出さない。** `ClassFont.h` が580行の震度クラス字形で、TFT_eSPI にも依存する |
`lib/Shindo/` `lib/Iis3dhhc/` `lib/Adxl355/` `lib/AccelSensor/` | 地震計専用 |
`lib/NamzWire/`(+`WireFormat.h`) | **切り出さない。** `NAMZ` v1 のヘッダを組む薄い層。Electabuzz は同じ位置に `lib/GridFreq` の相当物を持つ |

**`WireFormat.h` は `batch-uplink` に入れない。** `Batch` からワイヤ形式の知識を抜いた以上、
ヘッダ定義の行き場は各プロジェクト側だ(Namazu では `lib/NamzWire`)。
**「名前が汎用的」と「中身が汎用的」は別物なので、過剰に切り出すな** —
`lib/Display` を一度は共有対象に数えかけた教訓だ。

#### 参照の機構

**C++ (PlatformIO)** — [platformio.ini:38-40](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/firmware/platformio.ini#L38-L40)
が既に `lib_deps` を使っているので、git URL をタグ付きで足すだけ。

```ini
lib_deps =
    bblanchon/ArduinoJson @ ^7.0.0
    bodmer/TFT_eSPI @ ^2.5.43
    https://github.com/nna774/batch-uplink.git#v1.0.0    ; ← タグで pin
```

共有レポ側に `library.json` を置く。**依存は宣言しない — v1.0.0 は C++ 側も Python 側も
依存ゼロだ**(アラートJSONの生成は `snprintf` で、それも `sendAlert` の一般化で呼び出し側へ移った)。
Python が numpy 非依存であることは、下記の pip 2回分割が成立する前提でもある。

**Python (Lambda)** — [build_lambda.sh:29-33](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/terraform/build_lambda.sh#L29-L33)
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
  [lambda.tf](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/terraform/lambda.tf) の形をそのまま複製する

### 切り出しの順序 (2026-08-03 に完了)

**バイト等価な移動と、意味の変更を、同じ手順で混ぜてはならない。** これが不変条件だ。
実機で異常が出たときに、移動のせいか一般化のせいか切り分けられなくなる。

1. **Namazu の中で先に一般化する。** `Batch` のレコード長可変化・`sendAlert` の地震汚染剥がしを
   **pytest / backtest / 実機2台が揃っている場所で**やり、動くところまで持っていく
2. **出来上がったものを「一文字も変えずに」共有レポへ移す**
3. `pytest` が緑、**かつ実機を焼き直してバッチが従来通り着弾する**ことを確認する
4. **v1.0.0 をタグで固定。** Namazu は `platformio.ini` / `build_lambda.sh` でここに pin する
5. **Electabuzz も同じ v1.0.0 を指す**

**逆順(先に移してから新レポで一般化し v1.1.0 を切る)は採らない。**
一見もっともらしく、「地震計を触りたくない」という動機から自然に出てくる順序だが、劣る。

| | 先に移す | **先に一般化する(採用)** |
|---|---|---|
| 一般化を検証する場所 | 新レポ。**テストも実機も無い** | Namazu。pytest も backtest も実機2台もある |
| 移動を検証する場所 | 動いたことの無いコード | **既に動作確認済み**のコードを動かすだけ |
| バージョン | v1.0.0 と v1.1.0 の2本 | **v1.0.0 の1本** |

**検証は環境が揃っている側でやれ。** 「地震計を触らない」は目的ではなく、
**壊さない**ための手段にすぎない。焼き直して確認できるなら触ってよい。

**切り出し直後は v1.1.0 が存在しなかった。** 両プロジェクトが同じ v1.0.0 を指していた。
**その後 Namazu が OTA・実機障害対策等のために v1.1.0〜v3.0.0 を切っており
（`v2.0.0` だけはヘッダ配列のnullptr終端化という破壊的変更を含む）、
Electabuzz は v3.0.0 まで これに追従して同じタグを指してきた。**
ただし「同じタグを指す」こと自体を目的にしたことは無い。**pin は各プロジェクトが
独立に決めるもので、相手が今どのタグを指しているかはそもそも気にする対象ではない。**
これまで一致していたのは、バージョンアップが常に Namazu 発でElectabuzzがそのまま
追従していた(自分から独自の理由でタグを切ったことが無かった)という結果にすぎず、
「揃える」という規範があったわけではない。

**v3.1.0(2026-08-23)は Electabuzz 発の要件(`track_prev_key`)で切った初めてのタグ。**
`devices.record_batch()`のこのオプトイン引数はElectabuzz detect固有の要件
（S3の`ListObjectsV2`コスト削減、→
[log/2026-08-23-detect-listobjectsv2-cost-and-prev-batch-key-design.md](log/2026-08-23-detect-listobjectsv2-cost-and-prev-batch-key-design.md)）で、
Namazu側に相談の上「Namazuは使わない属性が増えるだけなのでデフォルトFalseのオプトインにし、
Namazu側は今回追従不要」と合意している。Namazu側が`track_prev_key`相当を使いたくなれば
その時にNamazu側もv3.1.0以降へ上げればよいだけで、Electabuzz側から見ても
Namazu側のpinが今どこにあるかを追いかける必要は無い。

### タグで pin しろ。ブランチ追従にするな

**これが独立レポ構成における唯一の落とし穴だ。**

`lib_deps` や `requirements.txt` を `#main` や `@main` のようにブランチ追従にすると、
Electabuzz のために共有レポへ入れた変更が、**地震計の次回ビルドで黙って混入する。**

これは単一レポより悪い。単一レポなら変更が同じ diff に見えるが、ブランチ追従では
**結合が不可視**になる。「動いていたものが、何も変えていないのに再ビルドで壊れる」
という最悪の壊れ方をする。

- `lib_deps = ...git#v3.1.0` — **タグ**を指す
- `requirements.txt` に `git+https://.../batch-uplink@v3.1.0` — **タグ**を指す
- 共有レポ側で **タグを打ち替えない**(打ち替えたら pin の意味が消える)

---

## レポジトリ配置

**3レポジトリ + 2スタック。** 前掲のディレクトリ構成を参照。要点だけ再掲する。

- **`batch-uplink`**: C++ は `Batch`・`Uploader`/`HmacSha256`・`TimeSync`。
  Python は `auth`・`devices`・`notify`・`s3util`。**これ以上は入れるな。**
  ドメインが混ざった瞬間に共有ライブラリとしての価値が消える
  (`WireFormat.h` が入っていないのはこの原則どおりの帰結だ)
- **`NamazuHaUrokoGaNai`**: `batch-uplink` に pin（現在 v3.0.0）。**自分の都合でしか動かさない**
- **`Electabuzz`**: `batch-uplink` に pin（現在 v3.1.0。`track_prev_key`が欲しくて
  自分の都合で上げた——Namazu側のpin状況は気にしていない。上記「バージョン分岐」参照）。
  `lib/GridFreq/`(GFRQワイヤ形式)、`lib/Goertzel/`(単一ビンDFT)、
  `wire_gridfreq`、`tools/gridfreq/`(参照実装 + backtest)、独立 Terraform state
- **ワイヤ形式は `batch-uplink` に入れない。** `Batch` がレイアウト非依存になるので、
  ヘッダ定義・magic・`SensorType` 相当の enum はすべてプロジェクト固有になる。
  地震計は `NAMZ` v1、Electabuzz は `GFRQ` v1 を各々のレポで持つ

**「ナマズ」というドメイン名との齟齬が、この構成では解消する。** 単一レポ案では
地震計のレポに電力の話が同居する不自然さが残ったが、共通部分を `batch-uplink` に抜けば
NamazuHaUrokoGaNai は地震計のままでいられる。**これも独立レポ案の利点だ。**

[design.md](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/docs/design.md) の「デバイスマニフェストを単一の
真実にする」構想(152-167行目)は、**スタックが2つになり HMAC 秘密の登録先も2つになるので
より価値が上がる。** ただしマニフェスト自体は各プロジェクト固有(device_id の払い出しは
プロジェクト単位)なので、**`batch-uplink` には入れない**。生成スクリプトの雛形を共有したく
なった時点で改めて考えればよい。

---

