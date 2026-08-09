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

## api

**実装済み: `lambda/api/handler.py`**（テストは `lambda/tests/test_api.py`）。
ダッシュボード向けの読み取り専用API（Function URL、認証なし・CORS許可）。

    GET /recent?minutes=5&start=<us>

直近`minutes`分（既定5、上限`MAX_RECENT_MINUTES`=30。認証なし公開なので
S3スキャン量に上限を付けている）の瞬時周波数の時系列を返す。`start`指定時は
`[start-minutes, start]`。

**Lambda Function URLの手前にCloudFront(`terraform/api_cache.tf`)を挟み、
`minutes`/`start`をキーに30秒固定TTLでキャッシュしている**(2026-08-09、
→ [log/2026-08-09-api-cloudfront-cache.md](log/2026-08-09-api-cloudfront-cache.md))。
GFRQのバッチは30秒に1本しか増えないので、これは鮮度を犠牲にしていない——
「同時に何人見ていようとオリジン(Lambda→S3)へのアクセス頻度をほぼ一定に保つ」
ためのキャッシュで、認証なし公開のエンドポイントを閲覧人数の増加に対して
安全にする設計上の要石。`dashboard/config.js`の`window.ELBZ_API_URL`は
`terraform output api_url`(CloudFront経由)を使う。生のFunction URLは
`api_url_direct`として切り分け用に残っている。

**detect/rollup/生存台帳がまだ無いので、Namazuの`api`と違って`/events`・
`/devices`は無い。** `/recent`の`latest`(系列末尾点)に`timebase_source`・
`fs_measured_hz`・`tb_residual_ns`等の品質を載せており、ダッシュボードの
「今の状態」表示と生存確認を兼ねる。

瞬時周波数は`Record.cycles`(絶対累積位相)の隣接差分から`lambda/api/handler.py`の
`_series_payload()`が計算する(バッチの読み込み自体は`lambda/store_gridfreq.py`)。
**以下のいずれかに該当する隣接点はfreqを計算しない(null=系列の
途切れ)**——測れなかった区間を測れたように見せないため:

- `session_id`が変わる(デバイス再起動)
- 実際の間隔が`record_rate_mhz`から大きく外れる(欠測・送信遅延)
- バッチに`GfrqFlagDiscontinuity`が立っている(DMA溢れ等。ファーム側の
  `GoertzelEstimator::resetWindow()`がこの窓を無出力にするため、ワイヤ上の
  レコード列は詰まって見えるが実際の間隔は`record_rate_mhz`どおりではない)

### NOMINAL区間の事後補正 (2026-08-08〜)

`env:record`はNTPロックを待たずに起動直後から`timebase_source=NOMINAL`で
記録・送信する(→ [timebase.md](timebase.md)「NOMINAL区間の扱い」)。api側は
`_session_fs_corrections()`で、同一`session_id`内のNOMINALタグ付きバッチの
`fs_measured_uhz`(=公称fs定数)と、その後最初に規正済み(`is_disciplined`)に
なったバッチの`fs_measured_uhz`(=ロック値)を突き合わせ、
`correction = locked_fs / nominal_fs` を求める。この式は近似ではなく、
Goertzelの窓がサンプル数(=「公称fsでの1秒ぶん」)で切られることから
代数的に成り立つ関係——線形性は`tools/check_fs_linearity.py`で検証済み。

NOMINAL区間かつ補正係数が求まっているレコードには
`freq_hz_corrected = freq_hz * correction` を追加で返す。ロックがまだ来て
いない(現在進行形の)NOMINAL区間は`null`のまま——**測れなかった精度のものを
測れたように見せない**という一線は、値を出さないのではなく「補正できるまでは
補正値を出さない」形で守る。レスポンスには各点の`timebase_source`(文字列配列)
も追加し、ダッシュボードが区間ごとに線種を変えられるようにしてある。

## dashboard

**実装済み: `dashboard/`**（v1。→ [log/2026-08-07-dashboard-v1.md](log/2026-08-07-dashboard-v1.md)）。
外部依存なしの単一ページ(vanilla JS + Canvas)。`/recent`だけを叩き、瞬時周波数の
折れ線と時間基準の品質を表示する。S3 + CloudFront(OAC)で配信し、カスタムドメインは
無い(CloudFrontの既定ドメインで足りるうちは持ち込まない)。

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

