# detect(周波数逸脱・RoCoF・電圧異常の確定判定)v1を実装

## 経緯

フェーズ2(PPS)のsoak確認クローズ([log/2026-08-17-phase2-soak-confirmation.md](2026-08-17-phase2-soak-confirmation.md))
に続く「次の一手」として、フェーズ9の残りである detect に着手した。

## Namazuのdetectとは判定の性質が違う

Namazu(地震計)のdetectは`raw/`の生加速度波形を窓ごとにFFTし直して震度を
再計算する重い処理。Electabuzzは既にGFRQが1Hzで瞬時周波数の元になる累積位相を
運んでいるので、**窓の再解析が要らず、レコード単位のしきい値判定で足りる。**
デバイス側の即時速報(Namazuでいう「震度計算による速報」)という段も無い——
GFRQ自体がストリームなので、クラウド側だけで完結する判定にした。この違いにより
Namazuの`lambda/detect/handler.py`(quicklook画像生成・imagehost連携・
device_prompt/cloud_confirmedの2段突合を含む187行)をそのまま踏襲せず、
判定ロジックを新規に設計した。

## 実装

- `lambda/common/grid_detect.py` — 副作用の無い純粋関数(`samples_from_batches`・
  `analyze`)。`samples_from_batches`は`lambda/api/handler.py`の`_series_payload`と
  同じ周波数計算規則(理論値`nominal_dt`を分母に使う・DISCONTINUITYを立てた
  バッチ内では計算しない・session_id変化で連続性を切る)を複製している——
  api側の実装済み・実機確認済みロジックには手を入れず、判定ロジックだけ別に
  持つ判断(→CLAUDE.md「切り出しと一般化を同時にやるな」と同じ理由)
- `lambda/common/grid_events.py` — DynamoDB(`electabuzz-events`)のセッション管理。
  Namazuの`lambda/common/events.py`と同じセッションマージ(直近の活動から60秒以内の
  onsetは新規にせず延長)だが、デバイス速報とクラウド確定報の突合は無い(単一段の
  判定なので不要)
- `lambda/detect/handler.py` — `series/`へのS3 ObjectCreatedで起動。直前バッチの
  最後の1レコードだけを追加取得し、境界をまたぐ周波数計算の連続性を確保する。
  **それより過去には遡らない**——遡ると、数十秒前に確定済みのrunを毎回このバッチの
  到着のたびに再評価してしまい、`grid_events.record`が(セッションマージの時間窓を
  過ぎていれば)「新規」と誤判定してSlackを埋める
- `lambda/api/handler.py`に`/events`を追加(`NAMZ_EVENTS_TABLE`未設定なら空配列、
  `/devices`と同じ割り切り)

## 設計判断: 採らなかった選択肢

- **`f_nominal_mhz`が未判別(`0`)のバッチは周波数逸脱の判定をスキップする。**
  ELBZ_F_NOMINAL_HZのような環境変数フォールバックは持たせなかった——
  「測っていない値がもっともらしく記録されるのが最悪」(→docs/wire-format.md)と
  同じ理由で、基準が無いのに逸脱を判定してはいけない。RoCoF・電圧異常は
  f_nominalに依存しないので、この場合も判定を継続する
- **電圧異常はAC入力断(`power_fail`)中は評価しない。** 入力が無い時の電圧は
  ほぼ0Vで、「異常な低電圧」として二重に騒ぐ理由が無い(watchdogが既に
  AC入力断そのものを通知している)
- **通知は新規セッション作成時のみ。** watchdogのような定期再送は持たない——
  detectはイベント駆動であり、継続中の逸脱を再送する専用の仕組みを別に持つ
  理由が薄い(継続状況は`/events`の`last_us`で追える)
- **停電・復電時の位相跳躍量の記録・位相不連続のartificialフラグ付けは
  持ち込んでいない。** docs/cloud.mdの旧設計案(Namazu由来のスケッチ)には
  含まれていたが、前者はwatchdogが既に担っているAC入力断通知と重複が濃い、
  後者はGFRQのDISCONTINUITYフラグが既に`freq_hz`をnull化する形で系列側から
  除外されており別イベントとして記録する実利が薄いと判断し、v1では見送った

## テスト

`lambda/tests/test_grid_detect.py`(13件、しきい値判定の純粋関数)・
`test_grid_events.py`(4件、`event_id`のバケット化)・`test_detect_handler.py`
(4件、配線レベル。S3・DynamoDBには触れない)・`test_api.py`に`/events`のケースを
追加。lambda全体122件全パス。`terraform validate`・`build_lambda.sh`(ingest/api/
watchdog/detect の4本)とも緑。

## 残作業

**`terraform apply`はまだ実行していない**（費用が生じる操作なので明示の許可が要る、
→watchdog実装時と同じ判断）。しきい値(周波数逸脱100mHz・RoCoF 200mHz/s・電圧異常
±10%)はいずれも`docs/cloud.md`の目安をそのまま既定にした未校正値——実際の逸脱
事例で妥当性を確認する作業が残っている。rollupは引き続き未着手。
