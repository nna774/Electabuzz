# 進捗

新しいものが上。各行の詳細は `log/` の該当ファイルにある。
**このファイルは索引だ。判断の理由は各ログに、現在の結論は各設計ドキュメントにある。**

| 日付 | 何が決まったか | 詳細 |
|---|---|---|
| 2026-08-03 | **`wire_gridfreq.py`（パーサ）を書いた。形式の契約が書き手と読み手の往復で閉じた。** `lambda/wire_gridfreq.py` + テスト20件が緑で、**ゴールデンフィクスチャを firmware と Lambda の両側から主張している**。**「読めない」(`WireFormatError`)と「壊れている」(`CrcMismatch`)を別の型にした**（後者だけ隔離して次へ進むのが正しい）。**`NAMZ` の magic は名指しで弾く**（設定ミスとして報告できて初めて fail-fast の値打ちが出る）。**未知の `timebase_source` を「規正済み」と名乗らせない**（保守的に外す）。依存は stdlib のみ。repo 直下に `.venv` を作った | [log/2026-08-03-wire-gridfreq-parser.md](log/2026-08-03-wire-gridfreq-parser.md) |
| 2026-08-03 | **`GFRQ` ヘッダの組み立てを実装した。このレポ最初のコード。** `firmware/lib/GridFreq/`（`WireFormat.h` + `GridFreqWire.h/.cpp`）で、ホストの g++ で走るテストが緑。**`crc32` は `zlib.crc32` と同じ版に確定**（版の食い違いは目視で守れないので既知ベクタをテストに置いた）。**`fillHeader()` の引数から「`Batch` や形式から出る値」を全部外した**（二重に持てるものを持たせなければ食い違いようがない）。**既定値は何も主張しない側に倒す**（`f_nominal_mhz` の既定は 50000 ではなく 0 = 未判別）。Python の `struct` 書式でも読めることを確認済み。**穴が1つ出た: `v_rms_mv` は 100V を mV で持てない**（u16 は最大 65.5V） | [log/2026-08-03-gfrq-wire-layer.md](log/2026-08-03-gfrq-wire-layer.md) |
| 2026-08-03 | **書きぶりの規約を変えた。`docs/*.md` に `> **訂正**:` を積み上げない。** 判断が覆ったら本体は新しい結論に書き換え、**経緯はログに書く**（本体に履歴が混ざると「どちらが今の話か」の判定を毎回強いる）。**例外は「意図的に採らなかった選択肢」で、これは本体に残す**。ただし履歴としてではなく**「なぜ採らないか」の肯定文**として書く。既存の訂正枠は全ドキュメントから外し、**ログに無かった5件は先にログへ回収してから消した** | [log/2026-08-03-design-doc-corrections.md](log/2026-08-03-design-doc-corrections.md) |
| 2026-08-03 | **`batch-uplink` v1.0.0 が出た。切り出し完了、`v1.1.0` は要らなくなった。** 一般化を Namazu 側で先に済ませてから移す順序に反転したため、**両プロジェクトが同じ v1.0.0 を指す**。**`Batch` の契約が確定**し、`GFRQ` の寸法(64Bヘッダ + 12Bレコード + tail無し)がそのまま載ることを確認済み。`finalize()` は不要になり `bytes()` は純粋な getter。**`sendAlert` が一般化された**ので速報本文を自由に設計できる。**設計書の「ArduinoJson が要る」は誤りで C++/Python とも依存ゼロ**。同日中に [batch-uplink.md](batch-uplink.md) と [wire-format.md](wire-format.md)（tail を持たない・`Batch` への載せかた）へ反映済み | [log/2026-08-03-batch-uplink-v1.0.0.md](log/2026-08-03-batch-uplink-v1.0.0.md) |
| 2026-08-03 | **母艦は ESP32-S3。ただし S3 必須ではないと確定した**（無印 ESP32 でも全要件を満たす）。S3 を採る理由は **MCLK 出力ピンの自由度だけ**（無印は GPIO 0/1/3 に限られ、ブートストラップピンかシリアルコンソールを諦めることになる）。**設計書の S3 に関する記述が2つ誤りだった: ETM は S3 に無い**（方式B は MCPWM capture のみ）、**APLL は S3 に無く無印 ESP32 にある**。どちらも結論を覆さない | [log/2026-08-03-mcu-selection.md](log/2026-08-03-mcu-selection.md) |
| 2026-08-03 | **GNSS を待たずに走らせる方針。時間基準を `NOMINAL`/`NTP`/`PPS` のプラグインにする。** wire format を源非依存に変更（`timebase_source` 等を予約領域から出したので PPS 到着時にヘッダは変わらない）。共有レポ名を `batch-uplink` に決定。**新発見: `fs` を決めているのが ESP32 の水晶か PCM1808 の缶発振器か未確定だった**（リスク10）。レポジトリを立てて設計書を13ドキュメントへ分割 | [log/2026-08-03-timebase-plugin.md](log/2026-08-03-timebase-plugin.md) |
| 2026-08-03 | **フェーズ0（紙の調査）が決着。** 東電PG/OCCTO は系統周波数を公開しておらず、当初の照合先は存在しなかった。代わりに [powerk95](https://powerk95.net/50Hz/) を発見し**外部照合先を確保**。**PCM1808 の HPF はデジタル**と確認しリスク2が消滅。先行実装（W53SA 氏）の構成が判明し、**方式B の動く先行例があると分かった** | [log/2026-08-03-phase0-external-reference.md](log/2026-08-03-phase0-external-reference.md) |
| 2026-08-03 | **AC入力部が確定。** Ideal Power DA-12-09 を 100V/50Hz・周囲30℃・無負荷で1時間通電し、温度・唸り・波形すべて合格。**無負荷出力は想定より高い 29.6 Vpp / 約 10.5 VAC** で分圧比を引き直す。副産物として手持ち測定器の信頼度の運用方針が確定（**オシロの周波数表示は使わない**） | [log/2026-08-03-ac-adapter.md](log/2026-08-03-ac-adapter.md) |

## 現在の状態

| | |
|---|---|
| 確定済み | AC入力部（実測済み）、wire format `GFRQ` v1、**[batch-uplink](https://github.com/nna774/batch-uplink) v1.0.0**（public・切り出し済み。`Batch` の契約が確定） |
| 手持ちハードウェア | **ESP32-S3**（本番用に採用）、**無印 ESP32**（Namazu と同型の余り。予備機・差し替え先） |
| 未入手 | PCM1808、GNSS 受信機 ×2、アクティブアンテナ、DMM（HIOKI 3244-60） |
| コード | **`GFRQ` の書き手と読み手が揃った。** `firmware/lib/GridFreq/`（ヘッダの組み立て。ホストの g++ でテストが緑）と `lambda/wire_gridfreq.py`（パーサ。pytest 20件が緑）。契約は `testdata/gfrq_v1_golden.hex` で両側から固定してある。`platformio.ini` はまだ無い（基板の型番が未定で、両者とも Arduino に依存しないため。最初のファームウェアコードと同時に置く） |
| 開発環境 | repo 直下の `.venv`（Namazu と同じ形）。今は pytest だけ。`NtpTimebase` に入るとき platformio もここへ入れる。テストは `.venv/bin/python -m pytest lambda/tests` と `firmware/lib/GridFreq/test/run.sh` |

### 着手可能なタスク

- ~~**`batch-uplink` の切り出し → v1.0.0**~~ **済み**（2026-08-03。Namazu 側で完結した）
- ~~**[batch-uplink.md](batch-uplink.md) を現物に合わせて直す**~~ **済み**（2026-08-03。
  `Batch` の確定契約・`sendAlert` の一般化・依存ゼロ・切り出し順序を反映。
  `wire-format.md` にも tail の扱いを明記した）
- ~~**`GFRQ` ヘッダの組み立てを書く**~~ **済み**（2026-08-03。`firmware/lib/GridFreq/`。
  テストは `firmware/lib/GridFreq/test/run.sh`）
- **`NtpTimebase` を ESP32-S3 単体で書く** — PCM1808 を待たない。**最優先。**
  数日の実測待ちが入るので**先に仕掛けて走らせる**のが最も詰まらない。
  出力先（`fs_measured_uhz`/`tb_obs_count`/`tb_residual_ns`/`timebase_source`）は
  もう在る。数日走らせれば手元の水晶の実 ppm が取れ、リスク10 の片方が埋まる。
  → [timebase.md](timebase.md)
- ~~**`wire_gridfreq.py`（パーサ）を書く**~~ **済み**（2026-08-03。`lambda/wire_gridfreq.py`）
- **`ingest` Lambda を書く** — ハードウェア不要。パースと検証は在るので、あとは
  HMAC 検証（`batch-uplink` の `auth`）と S3 へ置く経路だけ。**キー命名
  `{device:04d}-{batch_start_us:020d}.bin` は必ず踏襲する**（20桁ゼロ埋めゆえに
  辞書順 = 時系列順）。→ [batch-uplink.md](batch-uplink.md) / [storage.md](storage.md)

### まだ触っていない領域

`tools/gridfreq/` の Python 参照実装、`lib/GridFreq/` の**位相推定側**（単一ビンDFT +
PPS規正。ワイヤ層だけが在る）、`terraform/`。**すべてフェーズ2（PPS同時サンプリング）が
通ってからでよい。** そこが成否の分岐点なので、先に作り込んでも無駄になりうる。

未決の問いは [open-questions.md](open-questions.md) にある。
