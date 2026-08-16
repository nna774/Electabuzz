# TE絶対値表示・欠測区間可視化の仕様を決め、TE絶対値表示を実装した

## 経緯

`CLAUDE.md`の「着手可能なタスク」に挙がっていた**TE(時刻偏差)絶対値表示・欠測区間の
可視化**について、PPSが安定して出ている今dashboard側だけで着手できるか検討した。

最初の見立て（他セッションから持ち込んだメモ）は「dashboard/app.js・index.htmlが主で、
backendは`lambda/api/handler.py`を少し触る程度」だった。調べた結果、**欠測区間の可視化は
その見立て通りdashboard単独で着手可能**だが、**TE絶対値表示は見立てより重い**ことが
分かった——backendに新しい永続化層が要る。

## 分かったこと

### 1. 欠測区間の可視化はdashboard単独で足りる

`/recent`は既に`continuous`(bool配列、`lambda/api/handler.py:98-108`)を返しており、
電圧グラフ(`dashboard/app.js`の`drawVrmsChart`)は既にそれで線を切っている。周波数
グラフもnullで線を切る仕組みは既にある。残っているのは「線が途切れている」を「意図的な
欠測区間だ」と視覚的に主張する仕上げ（空白域のハッチング等）だけで、これはdashboardの
改修のみで完結する。

### 2. `te_seconds()`はバッチ内相対値限定で、絶対値には別の設計が要る

`lambda/wire_gridfreq.py`の`te_seconds()`(139-165行)は意図的に**バッチ内(30秒)の
相対変化**しか返さない。絶対TEには`docs/storage.md`が元々描いていた「セッションごとの
アンカー(`t0_us`, `cycles_q16=0`の時刻)をDynamoDBに記録する」という設計が要るが、
**まだ実装されていない**。`lambda/api/handler.py`の`_series_payload()`も`freq_hz`系
しか計算しておらず、TE系列自体をレスポンスに出していない。

### 3. 元の「セッション開始をアンカーにする」設計には穴が2つあった

- **NOMINAL区間の`cycles`は信用できない。** `fs`未規正のGoertzelはNOMINAL区間で
  周波数に系統誤差を持つ(`docs/timebase.md`)のと同じ理由で、`cycles`もNOMINAL区間は
  実経過時間と1:1でズレる。セッション開始(=多くの場合NOMINAL区間)をアンカーにすると、
  そのぶんTEが最初から嘘をつく
- **power_fail(AC入力断)は`discontinuity`と独立したフラグで、`resetWindow()`を
  呼ばない**(`firmware/src/main.cpp:826-834`で確認)。断線中もGoertzelは(無信号/異常
  信号を食わされたまま)`cycles`を数え続ける。断線を跨いだcycles差分はグリッドの実周期を
  表さないので、アンカーをそのまま跨がせるとTEが嘘をつく。`docs/storage.md`の
  「停電中のTEは原理的に測れない、測れたように見せるな」という一線と整合しない状態
  だった。なお`_series_payload()`の既存の`suspect`判定(`discontinuity`のみを見る)にも
  同じ見落としが波及している可能性があるが、これは既存のfreq_hz計算の話であり今回は
  手を付けない

### 4. PPSの方がNTPより先にロックすることの方が多い

ロック条件を比較すると:

| | `kMinObs` | `kMinSpanSeconds` |
|---|---|---|
| `NtpTimebase`(`firmware/lib/Timebase/src/NtpTimebase.h:32-33`) | 8 | 600秒 |
| `PpsTimebase`(`firmware/lib/Timebase/src/PpsTimebase.h:30-31`) | 10エッジ | 30秒 |

GNSS fix自体は段階1の実測(`docs/gnss.md`、約44時間+αのログ)で「numSVは常に4機以上、
無fixは実質1件のみ」と裏が取れている。GNSS fix後わずか30秒でPPSはロックするのに対し、
NTP回帰は600秒かかる——実運用ではPPSの方が先に来ることの方が多い。

`docs/timebase.md:210-216`は元々「NTPロックでも帯(`tb_residual_ns`×経過時間)つきで
描いてよい」という方針を持っていたが、上記の理由でその状態が実運用では短い過渡状態にしか
ならない見込みが高く、実装コストに見合わない。**v1はPPS限定**とし、NTP帯表示は
`docs/open-questions.md`へ送る。

### 5. アンカーは「セッション」ではなく「連続区間(run)」単位

3の穴を踏まえ、アンカーは**「PPSロック中、かつ直前にdiscontinuity/power_failが
起きていない連続区間」ごとに作り直す**設計にした。session_idは変更しない
（firmwareの`session_id`はNVS保持・起動ごとの単調増加という既存の意味を持ち、
reboot_watch・OTA・生存台帳が依存しているため、そこに手を入れない）。

断線中も記録は止めない。しきい値校正(`kAcFaultVRmsThresholdMv`が緩やかな電圧低下でも
妥当かの校正、`docs/open-questions.md`の未決項目)には断線中の`v_rms_mv`こそ材料に
なるため。

結果として「断線復帰は新セッション相当」という直感は、firmwareのセッション概念を
変えずにcloud側のアンカー粒度だけで実現する形になった。

### 6. 読み出しは「窓全体で複数アンカー」を前提にする

30分の表示窓の中で断線が複数回起きれば、その窓の中に複数のアンカーが刻まれていて
当然——「1時刻に対して直近1件」をバッチ単位で毎回DynamoDBに問い合わせるのは無駄が
多い。実装は**セッションごとにその窓に関係するアンカー行をまとめて取得し**、
`_series_payload()`が元々やっている時刻順の1パス走査(`prev_session`/`prev_t`/
`prev_cycles`を追跡するループ、`lambda/api/handler.py:177-243`)に「今どのアンカーを
使うべきか」を進めるポインタを1本足すだけにする。DynamoDBへの追加往復はバッチ単位
ではなくセッション単位で済む。

### 7. 新しいDynamoDBテーブルの形は`grid_events.py`の前例に合わせる

設計の途中で、並行していた別セッションの作業(`detect`実装、フェーズ9)が
`main`へマージされているのに気づいた(`lambda/common/grid_events.py`・
`terraform/events.tf`)。**同じ「セッション単位で行が増えるDynamoDBテーブル」を
既にこのリポジトリが持っており、流儀が確立していた**:

- hash_keyだけの単純なテーブル(`event_id`一本、range keyは持たない)
- 「最新の行」の検索は`Query`(range keyでのソート)ではなく**`scan(Limit=1000)`+
  Pythonでの絞り込み**——理由は「実機1台・イベント数が少ない前提」(`grid_events.py`の
  `_latest_event`のコメントそのもの)
- `terraform/events.tf`も`devices.tf`と同じ`PAY_PER_REQUEST`

当初案(`device_session`をhash key、`anchor_t0_us`をrange keyにした`Query`)は
間違いではないが、**この流儀と噛み合わない**。台数が増えたら見直す前提の割り切りを
先に決めているリポジトリで、TEアンカーだけQueryベースの設計にする理由が無い。
`events`テーブルと同じ形に合わせる方が一貫性が高い——6.の結論(「窓全体で複数アンカー
がありうる」)自体は変わらないが、取得手段が「Query」から「scan+Pythonでの絞り込み・
`t0_us`昇順ソート」に変わる。

## 決定した仕様

- **欠測区間の可視化**: dashboard単独。次のタスクとして着手可能（TEと依存関係なし）
- **TE絶対値表示**:
  - v1は`timebase_source=PPS`限定で描く。NOMINAL/NTPは描かない
  - アンカーは「PPSロック中かつ直前にdiscontinuity/power_fail無し」の連続区間ごとに
    作る。1セッションに複数行になりうる
  - 新規DynamoDBテーブル `${local.name}-te-anchors`（`events`/`devices`テーブルと
    同じ`PAY_PER_REQUEST`、hash_keyのみの単純な形）。hash_key `anchor_id`(S、
    `event_id`と同じ発想の決定的な文字列、例`f"{device_id:04d}-{session_id}-{t0_us}"`)。
    属性: `device_id`(N)、`session_id`(N)、`t0_us`(N)、`cycles0_q16`(N)、
    `run_open`(BOOL)、`tb_residual_ns`(N、参考表示用)
  - **書き込み(ingest Lambda)**: バッチに`discontinuity`/`power_fail`が立っていたら、
    `scan`+Pythonの絞り込みで該当device×sessionの`run_open=true`な最新行を探し、
    あれば`run_open=false`に更新する(新規行は作らない)。PPS規正済みかつsuspectで
    ないバッチは、開いている行が無いときだけ新規行を追加(`t0`=バッチ最初の
    レコード、`cycles0`=そのcycles)。開いている行があれば何もしない
    (`grid_events.py`の`_latest_event`と同じ「実機1台なのでscanで足りる」割り切り)
  - **読み込み(api Lambda)**: `_series_payload()`が扱うセッションごとに、
    device×sessionでscanしてアンカー行をまとめて取得・`t0_us`昇順に並べ、時刻順
    1パス走査でマージしてTEを計算する
  - NTPロック時点での帯付きTE表示は`docs/open-questions.md`へ送り、v1では実装しない

## 実装した

上記の仕様どおりに実装した。**`terraform apply`はまだ実行していない**(課金が
生じるリソース作成のため別途許可が要る)。

- `lambda/wire_gridfreq.py`: `Header.is_pps_disciplined`プロパティを追加
  (`timebase_source`がPPS/PPS_NTPかどうか)
- `lambda/common/te_anchors.py`: 新規。`open_run_if_needed`/`close_open_run`
  (書き込み、ingestが呼ぶ)・`anchors_for_session`(読み込み、apiが呼ぶ)。
  `grid_events.py`と同じ「hash_keyのみ・scanで足りる」流儀
- `lambda/ingest/handler.py`: `_record_te_anchor()`を追加。discontinuity/
  power_failが立っていたら開いているrunを閉じる、PPS規正済みかつsuspectで
  なければ(開いているrunが無い時だけ)新規に開く
- `lambda/api/handler.py`: `_series_payload()`にTE計算を追加。device×session
  ごとにアンカーをまとめて取得し(`_load_te_anchors`)、時刻順1パス走査に
  アンカーへのポインタを1本足してマージする。discontinuityに加えて
  **power_failもTE計算のsuspect判定に含める**(freq_hzの既存suspect判定は
  discontinuityのみで変更していない——今回の変更はTE計算に閉じる)。
  レスポンスへ`te_seconds`配列・`latest.te_seconds`を追加
- `terraform/te_anchors.tf`: 新規DynamoDBテーブル`${local.name}-te-anchors`
  (`events`テーブルと同じ形)。`terraform/iam.tf`・`terraform/main.tf`に
  IAM権限・環境変数(`ELBZ_TE_ANCHORS_TABLE`)を配線
- `dashboard/`: `drawTeChart()`を追加、`te-canvas`を新設。0秒の破線・
  PPS区間のみ描画・アンカー境界でのライン分断を実装。品質テーブルに
  「系統時刻偏差(TE、直近アンカーから)」行を追加
- テスト: `lambda/tests/test_te_anchors.py`(新規、`anchor_id`の純粋関数のみ。
  DynamoDBに触る関数はgrid_events.pyと同じ方針でテスト対象から外した)、
  `test_ingest.py`・`test_api.py`にそれぞれケースを追加。lambda全体で
  141件パス、`terraform validate`・`build_lambda.sh`とも緑
- 欠測区間の可視化(dashboard単独、TEと依存無し)は今回のスコープに含めず、
  次のタスクとして残した
