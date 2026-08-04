# クラウド側: ingest / detect / rollup

## ingest

**実装済み: `lambda/ingest/handler.py`**（テストは `lambda/tests/test_ingest.py`）。

既存 ingest を分岐させるのではなく、**Electabuzz 専用の ingest を別に置く**(スタック分離のため)。
構造は [ingest/handler.py](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/ingest/handler.py) をそのまま踏襲する。

- `auth.verify()` → `wire_gridfreq.parse()` → device_id 一致チェック → `s3.put_object()` →
  `devices.record_batch()` の流れは同一
- device_id 一致チェック([handler.py:56-57](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/ingest/handler.py#L56-L57))の
  「別デバイスの騙り防止」は必ず踏襲する
- `devices.record_batch()` の失敗を握りつぶして 200 を返す判断
  ([handler.py:67-68](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/ingest/handler.py#L67-L68)、
  「デバイスに無駄な再送をさせない」)も踏襲する。**これは正しい判断だ**

### 地震計と違えた3点

**1. 置き先は `series/` であって `raw/` ではない。**
`batch_uplink.s3util.raw_key()` を使わず `lambda/s3keys.py` に自前で持つ。
Namazu 側の lifecycle は `raw/` に 90日の expire を掛けており、累積位相を
そこへ置くと**永久保存のはずのデータが90日で消える**。しかも気づくのは3ヶ月後だ。
**prefix は保存方針そのものなので、共有ライブラリの既定に寄りかからない。**
キーの形(`{device:04d}-{batch_start_us:020d}.bin`)は共有ライブラリと同一に揃える。

**2. CRC 不一致は隔離して 200 を返す。**
`wire_gridfreq` が `WireFormatError`(読めない)と `CrcMismatch`(壊れている)を
別の型にしてある意味がこの呼び出し側で出る。

| 事象 | 応答 | 置き先 | 理由 |
|---|---|---|---|
| 署名不一致 | 401 | — | |
| 本文の device_id が名乗りと違う | 403 | — | 別デバイスの騙り |
| **読めない**（magic 違い等） | **400** | — | **設定ミスは fail-fast で報告する**。地震計のバッチは名指しで落ちる |
| **CRC 不一致** | **200** | **`bad/`** | 400 だとデバイスが同じ壊れたバッチを送り続けて uplink が詰まる。捨てると証拠が消える |

隔離キーは `bad/YYYY/MM/DD/<device>-<受信時刻>-<本文ハッシュ>.bin`。
**`batch_start_us` を使わない** — CRC が合わないバッチのヘッダを信じるとキーが飛ぶ。
device も**署名検証に通った名乗り**を使い、本文の値は信用しない。

**3. 生存台帳はテーブル未設定なら書かない。**
`ELBZ_DEVICES_TABLE` が無ければ `record_batch()` を呼ばない。watchdog を立てるまで
台帳の置き場が無く、毎バッチ例外を吐かせても雑音にしかならない。

### 環境変数

**`batch_uplink` が読む変数は `NAMZ_` のまま、こちらの独自変数だけ `ELBZ_`。**
共有ライブラリ側の名前を改名すると稼働中の地震計が壊れるので、
**名前は地震計由来のまま、値だけ Electabuzz のスタックのものを渡す**
（→ [batch-uplink.md](batch-uplink.md)）。この線引きなら「どちらが読む変数か」が
名前から一意に決まり、shim を書かずに済む。

| 名前 | 読む主体 | 用途 |
|---|---|---|
| `ELBZ_BUCKET` | ingest | 保存先バケット（必須） |
| `NAMZ_HMAC_SECRET`, `NAMZ_HMAC_SECRET_<id>` | `batch_uplink.auth` | デバイス共有鍵 |
| `NAMZ_DEVICES_TABLE` | `batch_uplink.devices` | 生存台帳。未設定なら台帳を書かない |

### `/alert` は意図的に書いていない

周波数側のイベント定義(逸脱・RoCoF・停電)も通知先も未確定で、**今書くと確定した頃に
作り直しになる**。JSON なのでフィールドを差し替えるだけであり、後から足す費用は小さい。

## 新規 detect_gridfreq / rollup

既存の状態機械を流用して判定だけ差し替える。

| イベント | デバイス側即時 | cloud 確定 |
|---|---|---|
| 周波数逸脱 | \|f - f_nom\| > 100mHz が継続 | 前後波形と PPS 品質で確認 |
| 急変(RoCoF) | \|df/dt\| > 200mHz/s | 同上 |
| 電圧異常 | v_rms が公称 ±10% 外 | 同上 |
| 停電・復電 | v_rms 急落/復帰 | 復電時の位相跳躍量を記録 |
| 位相不連続 | unwrap 失敗・SNR低下 | 測定側異常として `artificial` |

`artificial` フラグが既存にあるのが効く。自宅のエアコン起動によるローカルな電圧変動と
系統側事象を人が区別して記録できる。`tools/flag_event.py` もそのまま使える。

