# 進捗

新しいものが上。各行の詳細は `log/` の該当ファイルにある。
**このファイルは索引だ。判断の理由は各ログに、現在の結論は各設計ドキュメントにある。**

| 日付 | 何が決まったか | 詳細 |
|---|---|---|
| 2026-08-03 | **GNSS を待たずに走らせる方針。時間基準を `NOMINAL`/`NTP`/`PPS` のプラグインにする。** wire format を源非依存に変更（`timebase_source` 等を予約領域から出したので PPS 到着時にヘッダは変わらない）。共有レポ名を `batch-uplink` に決定。**新発見: `fs` を決めているのが ESP32 の水晶か PCM1808 の缶発振器か未確定だった**（リスク10）。レポジトリを立てて設計書を13ドキュメントへ分割 | [log/2026-08-03-timebase-plugin.md](log/2026-08-03-timebase-plugin.md) |
| 2026-08-03 | **フェーズ0（紙の調査）が決着。** 東電PG/OCCTO は系統周波数を公開しておらず、当初の照合先は存在しなかった。代わりに [powerk95](https://powerk95.net/50Hz/) を発見し**外部照合先を確保**。**PCM1808 の HPF はデジタル**と確認しリスク2が消滅。先行実装（W53SA 氏）の構成が判明し、**方式B の動く先行例があると分かった** | [log/2026-08-03-phase0-external-reference.md](log/2026-08-03-phase0-external-reference.md) |
| 2026-08-03 | **AC入力部が確定。** Ideal Power DA-12-09 を 100V/50Hz・周囲30℃・無負荷で1時間通電し、温度・唸り・波形すべて合格。**無負荷出力は想定より高い 29.6 Vpp / 約 10.5 VAC** で分圧比を引き直す。副産物として手持ち測定器の信頼度の運用方針が確定（**オシロの周波数表示は使わない**） | [log/2026-08-03-ac-adapter.md](log/2026-08-03-ac-adapter.md) |

## 現在の状態

| | |
|---|---|
| 確定済み | AC入力部（実測済み）、共有レポ名 `batch-uplink`、wire format `GFRQ` v1 |
| 手持ちハードウェア | **ESP32-S3 のみ** |
| 未入手 | PCM1808、GNSS 受信機 ×2、アクティブアンテナ、DMM（HIOKI 3244-60） |
| コード | 未着手 |

### 着手可能なタスク

- **`batch-uplink` の切り出し → v1.0.0** — ハードウェア不要。優先度が高い
  （稼働中の地震計を巻き込むリスクを消す作業）。→ [batch-uplink.md](batch-uplink.md)
- **`NtpTimebase` を ESP32-S3 単体で書く** — PCM1808 を待たない。
  数日走らせれば手元の水晶の実 ppm が取れ、リスク10 の片方が埋まる。→ [timebase.md](timebase.md)

### まだ触っていない領域

`tools/gridfreq/` の Python 参照実装、`lib/GridFreq/`（Goertzel + PPS規正）、
`wire_gridfreq.py`、`terraform/`。**すべてフェーズ2（PPS同時サンプリング）が通ってからでよい。**
そこが成否の分岐点なので、先に作り込んでも無駄になりうる。

未決の問いは [open-questions.md](open-questions.md) にある。
