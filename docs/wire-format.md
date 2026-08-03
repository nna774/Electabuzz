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

## ペイロード: 12バイト固定長レコード × N

| Type | Field |
|---|---|
| u64 | `cycles_q16` — セッション開始からの**絶対**累積位相。2^-16 サイクル固定小数点 |
| u16 | `v_rms_mv` — 電圧異常・停電判定用 |
| u16 | `flags` — レコード単位の品質フラグ |

レンジ確認: 50Hz × 86400s × 65536 = 2.8e14/日 → u64 で約6万年(60Hz なら 3.4e14/日)。
分解能 2^-16 サイクル = 50Hz で 0.31µs、60Hz で 0.25µs 相当。

1バッチ = 64 + 30×12 = **424 バイト**(当初案と同サイズだが、無駄なフィールドがない)。
既存の 100Hz×3軸バッチ(18KB)の 1/43。`kMaxRamBatches = 6` でも RAM 消費は無視できる。

認証ヘッダ名は `X-Namz-*` のままでよい(HMAC の仕組みは共有ライブラリ側で、
ヘッダ名は既存と同一。無理に改名する利得がない)。

---

