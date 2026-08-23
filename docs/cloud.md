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

**`/recent`・`/devices`(生存台帳)・`/events`(detectが確定したイベント。→本節末尾
「detect_gridfreq」)を持つ。rollupがまだ無いので、Namazuの`api`と違って
ロールアップ層の集計エンドポイントは無い。** `/recent`の`latest`(系列末尾点)に
`timebase_source`・`fs_measured_hz`・`tb_residual_ns`等の品質を載せており、
ダッシュボードの「今の状態」表示と生存確認を兼ねる。

**`v_rms_mv`(トランス二次側の実効値[mV])も各点に`t_us`と並行な配列で返す**
(2026-08-15)。`_series_payload()`はどのみち全レコードを舐めているので、
追加のS3アクセスやパース費用は無い。`freq_hz`と違い隣接点間の差分に依存しない
レコード単体の瞬時値なので、`session_id`変化やDISCONTINUITYによる抑制は
適用しない——値が存在する限りそのまま返す。壁側(商用100V系)への換算は
このAPIの責務ではない(→ [wire-format.md](wire-format.md)「`v_rms_mv`の基準点」)。

**`continuous`(bool配列、`t_us`と並行)も同時に返す**(2026-08-15)。
`v_rms_mv`は値自体を抑制しないぶん、グラフ側が「直前の点と線をつないでよいか」を
自前で判定する材料を失う——`freq_hz`のnullをそのまま使うとDISCONTINUITYの
バッチ内まで律儀に線を切ってしまい、`v_rms_mv`を抑制しない設計と矛盾する。
`continuous[i]`は`freq_hz`とは独立に、**実測の時間だけ**を見て決める:
直前のレコードと`session_id`が同じで、かつ実測dtが`record_rate_mhz`から
決まる想定間隔の2倍以内なら`true`。`suspect`(DISCONTINUITY)は見ない——
その窓のタイムスタンプ自体は実測どおりで、資格があるのは時間そのものだけ
だから。系列先頭(直前の点が無い)は`false`。ダッシュボードの電圧グラフは
これで折れ線を切り、「測れなかった区間を測れたように見せない」原則を
値を抑制せずに満たす(→ [dashboard/app.js](../dashboard/app.js)の`drawVrmsChart`)。

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

### TE絶対値表示のアンカー(2026-08-17設計・実装)

**v1は`timebase_source=PPS`限定。** NOMINAL/NTP区間はTEを描かない
(NTPロックでの帯付き表示は`docs/open-questions.md`へ送った——実運用では
PPSロック(30秒)がNTPロック(600秒)より先に来ることが多く、NTP限定の状態が
長く続かない見込みが高いため)。

TEは積分量なので、`freq_hz`のような「隣接点との差分」では出せず、**アンカー
(`t0_us`, `cycles0`)からの累積**が要る(→ [storage.md](storage.md)「セッションの
扱い」)。アンカーは「PPSロック中かつ直前にdiscontinuity/power_fail無し」の
連続区間ごとに作り直すので、1セッション内で複数行になりうる。

新規テーブル`${local.name}-te-anchors`(`terraform/te_anchors.tf`)は、並行して
マージされていた`detect`(下記)の`electabuzz-events`と同じ形にする——
**hash_keyのみ(`anchor_id`, S)、`PAY_PER_REQUEST`、実機1台前提で`scan`+
Pythonの絞り込みで足りる**という判断も揃える。`anchor_id`は`event_id`と同じ
発想の決定的な文字列(`f"{device_id:04d}-{session_id}-{t0_us}"`)。属性は
`device_id`/`session_id`/`t0_us`/`cycles0`(N、`Record.cycles`の値そのもの。
Q16は`wire_gridfreq.Record.cycles`が既に割り戻し済みなのでテーブル側では
生のcyclesを持たない)/`run_open`(BOOL)/`tb_residual_ns`。実装は
`lambda/common/te_anchors.py`。

- **書き込み(ingest)**: バッチに`discontinuity`/`power_fail`が立っていたら、
  該当device×sessionで`run_open=true`の行を`scan`で探し、あれば`run_open=false`
  に更新するだけ(新規行は作らない)。PPS規正済みかつsuspectでないバッチは、
  開いている行が無いときだけ新規行を追加(`t0`=バッチ最初のレコード、
  `cycles0`=そのcycles)。開いている行があれば何もしない
- **読み込み(api)**: `_series_payload()`が扱うセッションごとに、device×session
  で`scan`してアンカー行をまとめて取得・`t0_us`昇順に並べ、既存の時刻順1パス
  走査(`prev_session`/`prev_t`/`prev_cycles`を追跡するループ)に「今どの
  アンカーを使うべきか」を進めるポインタを1本足してマージする。バッチ単位で
  DynamoDBへ都度問い合わせない

詳しい経緯・検討過程は
[log/2026-08-17-te-absolute-display-design.md](log/2026-08-17-te-absolute-display-design.md)。

## watchdog

**実装済み: `lambda/watchdog/handler.py`**（テストは `lambda/tests/test_watchdog.py` 他）。
Namazu(nna774/NamazuHaUrokoGaNai)の
[lambda/watchdog/handler.py](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/lambda/watchdog/handler.py)
を踏襲する。EventBridge(`var.watchdog_schedule`、既定5分おき)で定期起動し、
生存台帳(`electabuzz-devices`)を見て異常をSlackへ通知する。

不在（データが来ないこと）はイベント駆動では検知できないので、外から定期的に見る
必要がある——これがwatchdogの存在理由そのもの。判定はどれも副作用のない純粋関数
(`evaluate()`系)に集約してあり、DynamoDBに触れずテストできる（`batch_uplink.devices`
と同じ設計）。

### 見ている項目

| 項目 | 判定 | 通知 | メンション |
|---|---|---|---|
| 欠測 | `NAMZ_OFFLINE_AFTER_S`(既定300秒)受信が途絶えた | 初回+`NAMZ_OFFLINE_RENOTIFY_S`ごと再送、復帰で1回 | あり |
| データ遅延 | 受信は続くが測定時刻が`NAMZ_LAG_AFTER_S`(既定600秒)以上遅れた | 同上 | あり |
| AC入力断 | バッチ`flags`の`power_fail`ビット(→ [wire-format.md](wire-format.md)) | 同上 | あり |
| 再起動 | 稼働時間ヘッダからの逆算(`boot_epoch_us`)が前回watchdog観測値と変わった | 変化のたび1回のみ(再送なし) | なし |
| pull型OTA停滞 | 許可(`pending_ota_version`)から`NAMZ_OTA_STUCK_AFTER_S`(既定1800秒)解消しない | 初回+再送 | なし |

**欠測・データ遅延・AC入力断にはSlackメンション(`NAMZ_SLACK_MENTION`)を付ける。**
見落とすと実害が大きい（実際に電源が来ていない・データが取れていない）ため
——Namazuと同じ判断。再起動検知・OTA停滞は情報寄りなので付けない。

**AC入力断は「線が抜けたのか停電したのか」を区別しない。** AFE単体の信号では
原理的に区別できないと判明している(→ [open-questions.md](open-questions.md)、
[risks.md](risks.md) リスク13)。「AC入力が見えない」で一本化し、原因の切り分けは
人間が現地で行う。

**欠測中はデータ遅延・AC入力断の評価を黙らせる**
(`batch_uplink.devices.evaluate_lag`・`power_fail_watch.evaluate`とも同じガード)。
データが来ていないのに古い状態だけで通知し続けるのを防ぐためで、欠測自体は別途
「デバイス欠測」で通知される。

**再起動検知だけ再送しない。** OTA・電源瞬断・WDTパニックいずれでも「起動した」
という事実は1回しか起きないので、状態が変わるたびに1回だけ通知すれば足りる
(`lambda/common/reboot_watch.py`)。`tools/request_ota.py`の手動許可を経ない再起動は
異常の可能性がある。

### 生存台帳への状態記録（ingest側）

watchdogが読む状態は`lambda/ingest/handler.py`が毎バッチ書く。いずれも主経路では
ない（失敗してもバッチ保存自体は成功扱い、→ ingest節の`_record_liveness`と同じ方針）:

- `power_fail`(bool): `lambda/common/power_fail_watch.py`。バッチの`flags`を
  そのまま反映するだけで、状態遷移の判定はwatchdog側に持つ
- `boot_epoch_us`: `lambda/common/reboot_watch.py`。`X-Elbz-Uptime-Us`ヘッダから
  `batch_start_us - uptime_us`を逆算し、前回値からTimeSyncのドリフト許容(±2分)を
  超えてズレていたときだけ書く。**`X-Elbz-Reset-Reason`相当のヘッダはfirmware側が
  未対応**なのでNamazuの`device_meta.py`と違い`reset_reason`は持たない
- `watchdog_muted`の解除: バッチを受信するたび無条件で`REMOVE`する
  (`lambda/common/watchdog_mute.py`)。mute中のデバイスから実際に送信が来た瞬間に
  監視が復帰する

### mute（退役・試験機を監視対象外にする）

`lambda/common/watchdog_mute.py` + `tools/mute_device.py`（いずれもNamazuから
移植）。実機は1台構成だが、将来の試験機(ハード試験のたびに繋いでは黙る機体)や
退役に備えて同じ仕組みを持ち込んである。mute中はwatchdogが評価自体をスキップする
——ingestがバッチを受信すれば自動でunmuteされるので、試験を再開するたびに
手動でunmuteし直す必要はない。

### 環境変数

`NAMZ_`接頭辞のものは`batch_uplink`側にも同名の慣習があるものを踏襲(→ ingest節)。
watchdog固有の閾値・Slack設定は`terraform/variables.tf`から
`local.watchdog_env`(`terraform/main.tf`)経由で渡す。

| 名前 | 用途 | 既定値 |
|---|---|---|
| `NAMZ_DEVICES_TABLE` | 生存台帳 | (必須) |
| `NAMZ_OFFLINE_AFTER_S` / `NAMZ_OFFLINE_RENOTIFY_S` | 欠測しきい値/再送間隔 | 300 / 86400 |
| `NAMZ_LAG_AFTER_S` / `NAMZ_LAG_RENOTIFY_S` | 遅延しきい値/再送間隔 | 600 / 86400 |
| `NAMZ_POWER_FAIL_RENOTIFY_S` | AC入力断の再送間隔 | 86400 |
| `NAMZ_OTA_STUCK_AFTER_S` / `NAMZ_OTA_STUCK_RENOTIFY_S` | OTA停滞しきい値/再送間隔 | 1800 / 86400 |
| `NAMZ_SLACK_WEBHOOK_URL` / `NAMZ_SLACK_CHANNEL` | 通知先(`batch_uplink.notify`) | 空なら無通知(NullNotifier) |
| `NAMZ_SLACK_MENTION` | 欠測・遅延・AC入力断に付けるメンション | Namazuと同じユーザーID |
| `NAMZ_DASHBOARD_URL` | Slack通知内のデバイスリンク | CloudFrontドメイン |

## dashboard

**実装済み: `dashboard/`**（v1。→ [log/2026-08-07-dashboard-v1.md](log/2026-08-07-dashboard-v1.md)）。
外部依存なしの単一ページ(vanilla JS + Canvas)。`/recent`だけを叩き、瞬時周波数の
折れ線と時間基準の品質を表示する。S3 + CloudFront(OAC)で配信し、カスタムドメインは
無い(CloudFrontの既定ドメインで足りるうちは持ち込まない)。

## detect

**実装済み(v1): `lambda/detect/handler.py`**（テストは`lambda/tests/test_grid_detect.py`・
`test_grid_events.py`・`test_detect_handler.py`。→ [log/2026-08-17-detect-gridfreq-v1.md](log/2026-08-17-detect-gridfreq-v1.md)）。

Namazuのdetect(地震の震度をFFT窓で再計算する)とは判定の性質が違う。GFRQは
既に1Hzで瞬時周波数の元になる累積位相を運んでいるので、**窓の再解析が要らず、
レコード単位のしきい値判定で足りる。** デバイス側の即時速報という段は無い
(GFRQ自体がストリームなので、クラウド側だけで完結する判定にした)。

- `series/`へのS3 ObjectCreatedで起動。直前バッチの最後の1レコードだけを追加
  取得し、境界をまたぐ周波数計算の連続性を確保する(それより過去には遡らない
  ——遡ると数十秒前に確定済みのrunを毎回再検知してSlackを埋める)。直前バッチの
  S3キーは生存台帳(`NAMZ_DEVICES_TABLE`、必須)の`prev_batch_key`属性を`GetItem`
  一発で読むだけで分かる(`batch_uplink.devices.record_batch`が`track_prev_key=True`
  でバッチ受信のたびにアトミックに更新している)。**以前は`ListObjectsV2`で
  時間窓を探しに行っており、バッチ到着(実測30秒間隔)のたびに無期限でListが
  飛び続けS3コストを底上げしていた**ため置き換えた
  (→ [log/2026-08-23-detect-listobjectsv2-cost-and-prev-batch-key-design.md](log/2026-08-23-detect-listobjectsv2-cost-and-prev-batch-key-design.md))。
  フェッチした直前バッチが実際に「直前」として妥当な間隔(1レコード分＝
  nominal_dtの0.5〜2倍)かを確認してから使う——プレースホルダの安全策では
  なく、レビューで見つかった実際の欠陥(レースで1つ古いバッチが返っても
  「現在より過去」というだけの判定では素通りしてしまい、電圧異常判定には
  周波数側のような時間差ガードが無いため誤検知しうる)を塞ぐためのもの
  (→ [log/2026-08-23-detect-listobjectsv2-cost-and-prev-batch-key-design.md](log/2026-08-23-detect-listobjectsv2-cost-and-prev-batch-key-design.md))
- しきい値判定は`lambda/common/grid_detect.py`の純粋関数(`analyze`)に集約
  (DynamoDB・Slackに触れずテストできる)

| イベント | 判定 |
|---|---|
| 周波数逸脱(`freq_deviation`) | \|f - f_nom\| > 閾値(既定100mHz)が既定3レコード(≒3秒)連続 |
| 急変(`rocof`) | 隣接レコード間の\|df/dt\| > 閾値(既定200mHz/s)。単発で確定(それ自体が変化率の測定のため、継続判定は無い) |
| 電圧異常(`voltage_anomaly`) | \|v_rms - 基準点\| / 基準点 > 閾値(既定10%)が既定3レコード連続。AC入力断(`power_fail`)中は評価しない(→watchdogが別途通知するので二重に騒がない) |

`f_nominal_mhz`が未判別(`0`)のバッチは周波数逸脱の判定をスキップする——
測っていない基準を勝手に補って判定しない(→[wire-format.md](wire-format.md))。
RoCoF・電圧異常はf_nominalに依存しないので影響しない。

**採らなかった判定**（意図的に外した。Namazu由来の設計案には含まれていたが、
理由があって見送っている）:

- **停電・復電時の位相跳躍量の記録** — AC入力断(`kGfrqFlagPowerFail`)の
  通知自体は既にwatchdogが担っている(→上記「watchdog」)。位相跳躍量の
  記録は「復電前後の絶対位相をどう突き合わせるか」の定義が固まっていない
  ので、detectの外に出したまま持ち込んでいない
- **位相不連続・SNR低下を「測定側の異常(artificial)」として記録すること** —
  GFRQの`DISCONTINUITY`フラグは既に`freq_hz`をnull化する形で系列側から
  除外されており(→api節)、detectが別途イベントとして記録する実利が薄い

イベントは`electabuzz-events`(DynamoDB、→[events.tf](../terraform/events.tf))に
セッション方式(同一device×event_typeで、直近の活動から60秒以内のonsetは新規に
せず延長)で記録する(`lambda/common/grid_events.py`。Namazuの`lambda/common/events.py`
と同じセッションマージだが、デバイス速報とクラウド確定報の突合は無い——単一段の
判定なので不要)。**新規セッションを作った時だけSlack通知する。** 継続中の延長を
毎回通知すると同じ逸脱でSlackが埋まる。継続状況は`/events`の`last_us`で追える
(watchdogのような定期再送は持たない)。

Slack通知の「イベント」欄は、そのイベントが収まる範囲でdashboardのグラフを直接開ける
リンクにしている(`_event_link`、`NAMZ_DASHBOARD_URL`未設定時はID文字列のまま)。
dashboardの`#live?m=<分>&auto=<0\|1>&s=<epoch秒>`ハッシュルーティング
(→[log/2026-08-20-dashboard-event-time-hash-routing.md](log/2026-08-20-dashboard-event-time-hash-routing.md))
に合わせ、表示範囲・終端時刻を`dashboard/app.js`の`eventViewWindow()`と同じ式で
計算している(`_event_view_window`)——イベント一覧の行クリックで開く範囲と、
Slack通知のリンク先を一致させるため、計算式をPython側に複製した。

しきい値は`terraform/variables.tf`の各`variable`(既定値は上表の通り)で調整できる。
**いずれも未校正の暫定値**——実際の逸脱事例で妥当性を確認する作業がまだ残っている
(→ [progress.md](progress.md))。

## rollup

未実装(→[roadmap.md](roadmap.md))。

