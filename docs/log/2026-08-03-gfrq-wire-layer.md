# 2026-08-03 `GFRQ` ヘッダの組み立てを書いた — このレポ最初のコード

`Batch(30, 12, 64, 0)` に64バイトヘッダを載せる薄い層を実装した。
`firmware/lib/GridFreq/` に置き、**ホストの g++ で走る単体テストが緑**。
ハードウェアは一切要らず、`batch-uplink` v1.0.0 の契約だけに依存している。

```
firmware/lib/GridFreq/
├── src/WireFormat.h        GFRQ v1 のレイアウト（構造体・magic・enum・offset の static_assert）
├── src/GridFreqWire.h/.cpp Batch への載せかた（newBatch / addRecord / fillHeader / crc32）
└── test/run.sh             ホストの g++ で走る（test_gfrq_wire.cpp）
```

## 決めたこと

### `crc32` は `zlib.crc32` と同じ版にする

CRC-32/ISO-HDLC(多項式 `0xEDB88320` 反転表現、初期値・最終 XOR とも `0xFFFFFFFF`)。
仕様は「ペイロードのCRC」としか書いていなかったが、**版が食い違うと Lambda 側が
全バッチを壊れていると判定する**ので、Python 標準の `zlib.crc32` に合わせて確定させた。
テーブルは持たない — 1バッチ360バイトに対して 8シフト/バイトは無視でき、
**1KBのテーブルをフラッシュに置く理由が無い**。

既知ベクタ(`crc32("123456789") == 0xCBF43926` 等)をテストに置いた。
**版の一致は目視で確かめられない種類の合意なので、テストでしか守れない。**

### `fillHeader()` に渡す構造体から「二重に持てるもの」を全部外した

`batch_start_us`/`record_count`/`crc32` は `Batch` から出る。
`magic`/`version`/`record_format`/`header_len`/`record_rate_mhz` は形式が決めている。
**呼び出し側が渡せるようにすると、食い違った値を渡す道ができるだけで、得るものが無い。**
残ったのは `device_id`・`session_id`・`f_nominal_mhz`・`fs_measured_uhz`・
`tb_obs_count`・`tb_residual_ns`・`flags`・`timebase_source`・`soc_temp_c` の9つ。

### 既定値は「何も主張しない」側に倒す

- `f_nominal_mhz` の既定は **`0`(未判別)**。設置先が 50Hz 地域でも `50000` にしない。
  **測っていない値がもっともらしく記録されるのが最悪で、`0` なら後段が弾ける**
- `timebase_source` の既定は `NOMINAL`。規正済みだと誤って主張しない側だ

これは設計書の一線(「測れなかった区間を測れたように見せるな」)を、
**代入を忘れたときの倒れ方**にまで及ぼしたということだ。

### テストはバイト列を offset で読む

構造体を経由して読み返すと、**構造体と同じ間違いをしたときに気づけない**。
仕様書が offset で書かれている以上、検証も offset で書く。
リトルエンディアンの読み出しヘルパを test 側に持ち、`rd32(p, 20) == 2` の形で確かめている。

副産物として、Python 側でも同じバイト列が読めることを確認した
(`struct.unpack("<IBBHQIIIIIQIIHBbII", ...)` が `calcsize == 64` でパディング無しに嵌まり、
`zlib.crc32` が一致する)。**`wire_gridfreq.py` を書く前に形式の合意が取れている。**

### テストは兄弟ディレクトリの `batch-uplink` を見に行かない

`test/run.sh` が `Batch` の在処を探す順序は
`$BATCH_UPLINK_SRC` → `.pio/libdeps/*/` → タグからの clone(`.cache/` にキャッシュ)。
**手元の `../batch-uplink` 作業ツリーは候補に入れない。** それがタグと一致している保証が無く、
**pin を迂回して「通ったつもり」になるのが一番まずい壊れ方**だからだ
(→ [batch-uplink.md](../batch-uplink.md) の「タグで pin しろ」)。

## 覆ったこと

無い。`Batch` の契約(v1.0.0)にそのまま載り、`GFRQ` v1 の定義も変えていない。
**設計どおりに嵌まった。**

## 決めなかったこと(意図的)

- **レコードの `flags` はまだ1ビットも割り当てていない。** 何を品質として立てるかは
  位相推定の実装が決めることで、それが無い今に決めるのは「存在しない要件への一般化」だ
- **`platformio.ini` を置いていない。** 母艦は ESP32-S3 と決まったが**基板の型番までは
  決まっていない**し、この層は Arduino に依存しないのでホストのテストだけで足りる。
  最初のファームウェアコードと同時に置く。**それまでタグの pin は `test/run.sh` にある**

## 見つかった穴

**`v_rms_mv` は商用の 100V を mV で持てない**(u16 の最大は 65.535V)。
トランス二次側の実効値[mV]なら 10.5V ≒ `10500` で収まる。基準点が未確定なので
[open-questions.md](../open-questions.md) に上げた。**レコードを1バイトも記録していない
今なら単位の変更が無料**であり、記録を始めてからでは高くつく。

## 次に何が可能になったか

- **`wire_gridfreq.py`(パーサ)** — 形式が実装で固まり、Python 側の `struct` 書式も
  検証済みなので、そのまま書ける。ハードウェア不要
- **`NtpTimebase`** — こちらもハードウェア不要で、`fs_measured_uhz`/`tb_obs_count`/
  `tb_residual_ns`/`timebase_source` という**出力先が既に在る**状態になった
