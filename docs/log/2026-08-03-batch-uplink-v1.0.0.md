# 2026-08-03: batch-uplink v1.0.0 が出た — v1.1.0 は要らなくなった

Namazu 側での作業の記録。**Electabuzz に関係する結論だけを書く。**
向こうの作業そのものは [NamazuHaUrokoGaNai](https://github.com/nna774/NamazuHaUrokoGaNai)
の `dcd40bb` / `98c62c4` にある。

## 決まったこと

**[batch-uplink](https://github.com/nna774/batch-uplink) が public で立ち、`v1.0.0` が
打たれた。Electabuzz はこれを pin する。**

```ini
lib_deps = https://github.com/nna774/batch-uplink.git#v1.0.0
```
```bash
pip install "git+https://github.com/nna774/batch-uplink@v1.0.0"
```

## 覆ったこと1: 切り出しの順序を反転した

[batch-uplink.md](../batch-uplink.md) は「①一文字も変えずに移す → ④v1.0.0 で固定 →
⑤その後で一般化して v1.1.0」という順序を「絶対に守ること」としていた。**逆にした。**

**この順序は「地震計を触れない」という制約から逆算されたものだった**が、その制約が
消えた（触れないのではなく、急いで動かす理由が無いだけだった）。触れるなら、
**一般化を Namazu の中で先に済ませ、出来上がったものを移す**方が全面的に良い。

| | 元の順序 | 反転後 |
|---|---|---|
| 一般化を検証する場所 | 新レポ。**テストも実機も無い** | Namazu。pytest も backtest も実機2台もある |
| 移動を検証する場所 | 動いたことの無いコード | **既に動作確認済み**のコードを動かすだけ |
| バージョン | v1.0.0 と v1.1.0 の2本 | **v1.0.0 の1本** |

**「移動と一般化を分ける」という不変条件は守られている。**分ける軸を入れ替えただけだ。

### だから v1.1.0 は要らない

**Electabuzz も Namazu も同じ v1.0.0 を指す。** 別バージョンを指す構図は
「一般化を切り出しの後にやる」ことの副産物でしかなかった。
「タグで pin しろ・ブランチ追従にするな」は**そのまま生きる**（将来の変更に対する話だから）。

## 覆ったこと2: `finalize()` は要らない — `bytes()` は純粋な getter

設計書は `bytes()` を「純粋な getter。書き戻しをしない」と書いていた。一度は
**「それは実現できない」と判断した**が、それも誤りだった。両方の記録を残す。

なぜ一度は不可能に見えたか。**Namazu は TLV トレイラーの連結位置がレコード数の確定後に
しか決まらず、Electabuzz は `crc32`(offset 60) がレコード列の確定後にしか計算できない。**
どちらも「積み終えてから書く」を要求する。

解けた形は単純だった。**tail を `addRecord()` のたびに1レコード分だけ後ろへ `memmove` で
押し出す。** こうするとバッファはいつ見ても完結したバイト列になり、確定用の呼び出しを
忘れるという**失敗の形そのものが消える**。費用は tail 長ぶんの memmove（Namazu の実測で
6バイト × 1500レコード/バッチ）で、無視できる。

## 確定した `Batch` の契約

`GFRQ` を載せる相手はこれ。**設計書の API 案から変わっている**（`finalize()` が無く、
`records()`/`recordsSize()`/`tailRemaining()` が増えた）。

```cpp
Batch(uint32_t capacityRecords, size_t recordBytes, size_t headerBytes,
      size_t tailCapacity = 0);

void begin(uint64_t startUs);              // 順序付けの startUs のみ保持
bool addRecord(const void* rec, size_t len);   // len != recordBytes なら false
bool appendTail(const void* data, size_t len);
size_t tailRemaining() const;              // 複数回に分けて書く前の総量確認用

uint8_t*       headerPtr();                // ここへ呼び出し側がヘッダを書く
const uint8_t* records() const;            // ← CRC 計算に要る
size_t         recordsSize() const;
uint32_t       recordCount() const;
size_t         recordBytes() const;
uint64_t       startUs() const;
bool           isFull() const;

const uint8_t* bytes() const;              // 純粋な getter
size_t         size() const;
```

**ヘッダを書く時期は「レコードを積み終えた後・`Uploader` へ渡す前」。**
その時点で `recordCount()` も `records()` も確定しているので、`record_count` も
`crc32` もここで書ける。Namazu は `lib/NamzWire` という薄い層でこれをやっている
（`GridFreq` 側も同じ形にすればよい）。

**`GFRQ` の寸法（64バイトヘッダ + 12バイトレコード + tail なし）がそのまま載ることは
Namazu 側のテストで確認済み。** `Batch(3, 12, 64, 0)` でヘッダが書けてレコードが
侵されないこと、レコード長違いが拒否されることまで見てある。

## `sendAlert` が一般化された

設計書は `Uploader` を「そのまま使える（改造ゼロ）」としていたが、**速報経路は
地震に染まっていた**（`realtime_intensity` / `peak_gal` / `kind:"device_prompt"` が
ベタ書き）。v1.0.0 では剥がしてある。

```cpp
bool sendAlert(const char* json, size_t len);   // 本文は呼び出し側が組む
```

**Electabuzz は速報の本文を自由に設計できる。** 系統時刻偏差の飛びを速報するなら
そのための JSON をこちらで組む。

## 依存はゼロだった（設計書の誤り）

設計書は `library.json` について「`ArduinoJson` への依存を宣言する
（`Uploader` がアラートJSONの生成に使っている）」と書いていたが、**Namazu の firmware 全体に
`ArduinoJson` の参照は1つも無かった**（`snprintf` だった。そしてそれも今は呼び出し側へ移った）。

**C++ 側も Python 側も依存ゼロで切り出せた。** pip を2回に分ける必要（`--platform` が
`--only-binary=:all:` を要求し `git+` と両立しない）は変わらないが、**numpy 非依存という
前提はより強固**になった。

## 引き継ぐ制約

- **env の接頭辞は `NAMZ_` のまま。** `NAMZ_DEVICES_TABLE=electabuzz-devices` のように
  自分のスタックの値を渡す。改名すると稼働中の地震計が壊れるので据え置いた。
  設計書が既に採っていた割り切りと同じ。
- **`s3util` の prefix は引数化していない。** `raw/` と `events/` は Electabuzz でも
  そのまま使える名前で、こちらの仕様が未凍結の今に knob を足すのは「存在しない要件への
  一般化」だと判断した。**別 prefix（`series/` 等）が要ると分かった時点で v1.1.0 で足す。**
  → [open-questions.md](../open-questions.md)
- **`auth`/`devices`/`notify`/`s3util` は一般化不要だった。** 相互 import ゼロ・
  stdlib + boto3 のみという設計書の実測は正しく、**一文字も変えずに移せた**。
- **`events.py` は入っていない**（`max_intensity`/`peak_gal` で地震に染まっている）。
  Electabuzz のイベント管理は自前で書く。設計書の判断どおり。

## 次に何が可能になったか

**`lib/GridFreq` と `wire_gridfreq` を、`Batch` の契約に沿って書き始められる。**
ハードウェア（PCM1808 / GNSS）を待たずに、`GFRQ` ヘッダの組み立てと
`Batch` への載せかたは今すぐ書けて、ホストの g++ でテストできる
（batch-uplink の `test/run.sh` と同じ形）。

`NtpTimebase`（着手可能タスクB）とは独立に進む。

## 未了 → **同日中に解消した**

以下は本ログを書いた時点での未了。**同日、設計書側に反映して閉じた**
（[batch-uplink.md](../batch-uplink.md) に訂正5件、[wire-format.md](../wire-format.md) に
tail と `Batch` への載せかたを追記）。**以後は設計書本体が正**であり、ここは経緯として残す。

- **[batch-uplink.md](../batch-uplink.md) 本体がまだ古い。** このログと食い違っている。
  規約では「両者が食い違ったら `docs/*.md` を正とする」ので、**直すまでは本体を信じるな**。
  必要な訂正は5件（`Batch` の v2 化に伴う記述と行番号、`sendAlert` の地震汚染、
  `ArduinoJson` 依存、`lib/Adxl355` の追加、`s3util`/`notify` が「純汎用」ではないこと）。
- [wire-format.md](../wire-format.md) に **tail を持たない**ことを明記する
  （`tailCapacity = 0`。`header_len` の自己記述で拡張路は確保済みなので、
  使う当てのない尻尾を今から予約する理由が無い）。
