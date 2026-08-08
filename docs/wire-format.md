# wire format (GFRQ v1)

`Batch` をレイアウト非依存にする(前述)ので、**v1 を引き継ぐ制約は無い。Electabuzz に必要な
フィールドだけを持つ単一の64バイトヘッダを新規に設計する。**

「v1 の32バイト + 拡張32バイト」という当初案は、`scale_mg_per_lsb` を `0.0` で埋め、
`axes = 1` と書き、`sensor_type` に空き番を割り当てる、といった無意味な辻褄合わせを
必要としていた。**存在しない制約に合わせて形を歪めていた。** それを捨てる。

## ヘッダ (64 bytes, little-endian, packed)

| Offset | Type | Field | 値 |
|---|---|---|---|
| 0 | u32 | `magic` | **`0x47465251` (`"GFRQ"`)** — NAMZ とは別にする |
| 4 | u8 | `version` | `1` |
| 5 | u8 | `record_format` | `0` = `cycles_q16` レコード(12B) |
| 6 | u16 | `header_len` | `64`。**自己記述にして将来の拡張を可能にする** |
| 8 | u64 | `batch_start_us` | 先頭レコードの UNIX時刻 µs（UTC、NTP由来） |
| 16 | u32 | `device_id` | |
| 20 | u32 | `record_count` | 30秒バッチで `30` |
| 24 | u32 | `record_rate_mhz` | **出力レコードレート** 1Hz = `1000` |
| 28 | u32 | `session_id` | 起動ごとに単調増加(NVS保持)。不連続の識別子 |
| 32 | u32 | `f_nominal_mhz` | 判別結果(`50000` / `60000`) |
| 36 | u64 | `fs_measured_uhz` | **実効ADCサンプルレートの推定値** [µHz]。源は `timebase_source` が示す |
| 44 | u32 | `tb_obs_count` | 時間基準の観測数。**PPS エッジ数 または 採用した NTP 標本数** |
| 48 | u32 | `tb_residual_ns` | 時間基準推定の 1σ [ns/s]。**源に依らない確度の自己申告値** |
| 52 | u16 | `flags` | `pps_locked`/`gnss_fix`/`discontinuity`/`power_fail`/**`tb_extrapolated`** |
| 54 | u8 | **`timebase_source`** | **`0`=NOMINAL / `1`=NTP / `2`=PPS / `3`=PPS+NTP** |
| 55 | i8 | **`soc_temp_c`** | SoC 温度。**事後の `fs(T)` 補正の材料** |
| 56 | u32 | reserved | |
| 60 | u32 | `crc32` | ペイロードのCRC |

設計上の判断を4点。

- **`timebase_source`は実際にNOMINALで送られる(2026-08-08〜)。** `env:record`は
  NTPロックを待たずに起動直後から記録・送信するようになったため、`NOMINAL`は
  単なる「後方互換のための予約値」ではなく実際に送信される値になった。cloud側
  (`lambda/api/handler.py`)はNOMINAL区間をそのセッションのロック後に事後補正
  できる——詳細は [cloud.md](cloud.md)、決定の経緯は
  [log/2026-08-08-nominal-window-open-question.md](log/2026-08-08-nominal-window-open-question.md)。
- **時間基準のフィールドを源に依存しない名前で持つ。** `pps_count` / `pps_residual_ns` と
  していた当初案は PPS を前提に固まっていた。**PPS が無い期間(GNSS 到着前)と holdover 期間を
  同じ形で表現できないと、後段が二重実装になる。** 一般化して `timebase_source` で源を明示する。
  **`timebase_source` は絶対に省くな。** これが無いと「このデータは規正済みか」が
  永久に判別不能になり、設計書の一線が破れる(→ [timebase.md](timebase.md))

- **独自 magic にする。** `kIngestUrl` を誤設定して Electabuzz のデバイスが地震計の ingest に
  POST してしまった場合、magic が違えば**即座に弾かれる**。同じ magic だと誤パースして
  意味不明なデータが `raw/` に混入する。**fail-fast のための独自 magic だ**
- **`header_len` を固定位置に置く。** v1 はヘッダ長が32バイト固定の暗黙知だった。
  明示すればパーサが「知らないフィールドは飛ばす」を実装でき、拡張が非破壊になる
- **`record_rate_mhz` は出力レコードの周期であり、ADCのサンプルレートではない。**
  時刻導出は v1 と同じ式 `batch_start_us + i × 1e6/rate`
  ([wire.py:37-40](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/common/wire.py#L37-L40) の式を踏襲)。
  ADC レートは `fs_measured_uhz` に別途持つ

### `magic` のバイト順

**`0x47465251` は「バイト列 `"GFRQ"` を大端読みした値」であり、線上のバイト順は `Q R F G`
になる。** Namazu の `kWireMagic`(`0x4E414D5A`、線上は `Z M A N`)と同じ流儀だ。
目的は誤送信の fail-fast であって、**両実装が同じ値を使うことだけが要件**なので、
線上で読める向きに並べ直す利得は無い(直すと Namazu と流儀が食い違うぶん損)。

### `flags` のビット割り当て (バッチ単位)

| bit | 名前 | 意味 |
|---|---|---|
| 0 | `pps_locked` | この区間で PPS を捕捉できていた |
| 1 | `gnss_fix` | GNSS が測位できていた(PPS の質の傍証) |
| 2 | `discontinuity` | 直前のバッチと累積位相が繋がっていない |
| 3 | `power_fail` | 商用電源の断を検出した区間を含む |
| 4 | `tb_extrapolated` | 時間基準が外挿(holdover)だった |

### `crc32` の版

**CRC-32/ISO-HDLC** (多項式 `0xEDB88320` 反転表現、初期値・最終 XOR とも `0xFFFFFFFF`)。
**Python の `zlib.crc32` とバイト等価**になる版を選んである。ここが食い違うと
Lambda 側が全バッチを壊れていると判定するので、**実装には既知ベクタのテストを置く**
(`crc32("123456789") == 0xCBF43926`)。

対象は `records()` から `recordsSize()` バイトだけで、ヘッダも tail も含めない。
**将来 tail を使うことにしても、この範囲を広げてはいけない**(既存データの検証が壊れる)。
そのときは別フィールドを足す。

## ペイロード: 12バイト固定長レコード × N

| Type | Field |
|---|---|
| u64 | `cycles_q16` — セッション開始からの**絶対**累積位相。2^-16 サイクル固定小数点 |
| u16 | `v_rms_mv` — 電圧異常・停電判定用 |
| u16 | `flags` — レコード単位の品質フラグ |

レンジ確認: 50Hz × 86400s × 65536 = 2.8e14/日 → u64 で約6万年(60Hz なら 3.4e14/日)。
分解能 2^-16 サイクル = 50Hz で 0.31µs、60Hz で 0.25µs 相当。

**レコードの `flags` はまだ1ビットも割り当てていない。** 何を品質として立てるかは
位相推定の実装が決めることで、**それが無い今に決めると「存在しない要件への一般化」になる。**
フィールドは確保してあるので、DSP 側が立てたいものを持ち込んだ時点で定義を足せばよい。

**`v_rms_mv` の基準点は未確定だ。** 商用の 100V を mV で持つと u16(最大 65.535V)に
収まらないので、**トランス二次側の実効値[mV]** か、**壁側に換算した別単位**かを決める必要がある。
→ [open-questions.md](open-questions.md)

1バッチ = 64 + 30×12 = **424 バイト**(当初案と同サイズだが、無駄なフィールドがない)。
既存の 100Hz×3軸バッチ(18KB)の 1/43。`kMaxRamBatches = 6` でも RAM 消費は無視できる。

## tail は持たない

`batch-uplink` の `Batch` はレコード列の後ろに**可変長の tail** を置ける
(Namazu は TLV トレイラーをそこに載せている)。**`GFRQ` v1 は使わない。**

```cpp
Batch(/*capacityRecords=*/30, /*recordBytes=*/12, /*headerBytes=*/64, /*tailCapacity=*/0);
```

`header_len`(offset 6)の自己記述で**拡張路は既に確保してある**ので、使う当てのない尻尾を
今から予約する理由が無い。要ると分かった時点で `tailCapacity` を増やせばよく、
**`Batch` 側の変更は要らない**(v1.0.0 の契約のままで足りる)。

## `Batch` への載せかた

**ヘッダを書く時期は「30レコード積み終えた後・`Uploader` へ渡す前」。** その時点で
`recordCount()` も `records()` も確定しているので、`record_count`(offset 20)も
`crc32`(offset 60)もここで書ける。**`crc32` の対象は `records()` から `recordsSize()` バイト**。

`Batch` は最後まで中身を知らない。書くのは `lib/GridFreq` 側の薄い層で、
Namazu の `lib/NamzWire` と同じ役回りだ。→ [batch-uplink.md](batch-uplink.md)

**実装は `firmware/lib/GridFreq/`(`WireFormat.h` = レイアウト、`GridFreqWire.h/.cpp` =
`Batch` への載せかた)。** ホストの g++ で `firmware/lib/GridFreq/test/run.sh` が走る。

**`fillHeader()` に渡す構造体には、`Batch` から出る値も形式が決めている定数も入れていない。**
`batch_start_us`/`record_count`/`crc32` は `Batch` から、`magic`/`version`/`record_format`/
`header_len`/`record_rate_mhz` は形式から出る。**二重に持てるものを持たせなければ食い違いようがない。**

`f_nominal_mhz` の既定値は **`0`(未判別)** にしてある。設置先が 50Hz 地域でも `50000` を
既定にはしない。**測っていない値がもっともらしく記録されるのが最悪だからだ**
(同じ理由で `timebase_source` の既定は `NOMINAL` = 何も主張しない側)。

## ゴールデンフィクスチャ

**`testdata/gfrq_v1_golden.hex` に 424 バイトのバッチを1本、生成パラメータ付きで固定してある。**

版・CRC の範囲・オフセット・エンディアン・構造体のパディングの有無が、**全部まとめて**
ここに固定される。**仕様書の文章は読まないと効かないが、バイト列は読まなくても壊れたら落ちる。**
これが「明記する」より強い理由だ。

- firmware 側 (`test_gfrq_wire.cpp`) は「このパラメータからこのバイト列が出る」ことを主張する
- `wire_gridfreq.py` は「このバイト列を仕様どおりに読める」ことを主張する
  (ファイル冒頭のコメントに期待値が全部書いてある)
- **`*.bin` ではなくテキストで持つ**。diff が読め、行にコメントを付けられる
  (`.gitignore` が `*.bin` を無視する事情もある)

> **書き換えてよいのは形式を変えたとき(= `version` を上げるとき)だけだ。**
> **テストを通すために書き換えるな。** それをやった瞬間、このファイルは何も守らなくなる。
> 落ちたときはまず実装を疑え。

なお **このフィクスチャは「実装が仕様に合っている」ことの証明ではない**(実装から生成した
以上、循環している)。仕様との一致は offset ごとの検証と Python 側との突き合わせが担い、
**フィクスチャが担うのは「以後それが黙って変わらないこと」だ。** 役割を混同するな。

## パーサ側 (`lambda/wire_gridfreq.py`)

ヘッダは Python の `struct` で1行になる(**パディングが入らないことを確認済み**)。

```python
HEADER_FMT = "<IBBHQIIIIIQIIHBbII"   # calcsize == 64
RECORD_FMT = "<QHH"                  # calcsize == 12
```

**依存は stdlib だけ。** 1バッチ30レコードに numpy を持ち出す理由が無く、持ち込まなければ
ingest Lambda の zip に platform wheel の面倒が入らない
(Namazu 側は波形処理があるので numpy が要る。ここは事情が違う)。

弾きかたの方針。**「読めない」と「壊れている」を別の型にする** — `WireFormatError` と
`CrcMismatch`。形式違いは設定の事故、CRC 不一致は中身の事故で、後者だけ
「隔離して次へ進む」が正しい対処になるからだ。

- **`NAMZ` の magic を名指しで弾く。** 独自 magic にした目的そのもので、
  `kIngestUrl` の誤設定を「意味不明なデータ」ではなく**設定ミスとして**報告する
- **末尾に余りがあれば弾く。** v1 に tail は無いので、余りは連結・切り詰めの事故だ。
  tail を使う版を作るなら `version` を上げる
- **`header_len` を信じてレコード列の頭を決める。** ヘッダ末尾にフィールドが増えた版でも
  このパーサは壊れない(自己記述にしてある意味がこれだ)
- **未知の `timebase_source` を「規正済み」と名乗らせない。** 古いパーサが新しい源の
  データを読んだとき True に倒れると、**設計の一線がパーサ側から破れる**

`te_seconds()` が返すのは**バッチ内の相対 TE** だけにしてある。絶対 TE はセッションを
跨いだ基準が要るし、バッチ内に閉じていれば**うるう秒の1秒ジャンプを踏まない**
(時刻を `batch_start_us` からの式で作り、区間の途中で UTC を読み直さないため)。

認証ヘッダ名は `X-Namz-*` のままでよい(HMAC の仕組みは共有ライブラリ側で、
ヘッダ名は既存と同一。無理に改名する利得がない)。

---

