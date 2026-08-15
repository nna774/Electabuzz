# 2026-08-15 AC入力断検知を実装し、LED通知まで配線した

## 背景

2026-08-12にAC入力線が実機で物理的に抜ける事故があり(→
[log/2026-08-12-afe-input-disconnect-detection.md](2026-08-12-afe-input-disconnect-detection.md))、
「Goertzelビンのエネルギー(=`v_rms_mv`の元になっている量)がしきい値未満で継続することを
検知に使える見込み」という方針だけが決まっていた。検知ロジック・`flags`ビットの実配線・
通知はすべて未実装のまま`docs/open-questions.md`に積み残されていた。

今回、ダッシュボードの実効値グラフ(`v_rms_mv`)で実際に急落する区間が見えたことを
きっかけに、検知ロジックの実装とLED通知まで着手した。

## 実装したこと

1. **`firmware/lib/AcInputMonitor/`（新規lib）**: `v_rms_mv`をwindow単位(≈1秒)で
   受け取り、しきい値未満が`sustainWindows`回連続したら「AC入力が見えない」に確定する
   ステートマシン。復帰判定にも同じ回数のヒステリシスを対称にかけ、単発の谷でのチャタリング
   を防ぐ。Arduinoに依存せず、`test/run.sh`でホストのg++からテストできる(他のlibと同じ形)。
2. **`firmware/lib/FaultNotify/`（新規lib）**: `FaultNotifier`という1メソッドの純粋仮想
   インターフェースだけを置いた。実装(GPIO制御等)はハードウェア依存なので`main.cpp`側に
   置く——ロジックを持たないインターフェースなのでtestは無い。
3. **`main.cpp`への配線**:
   - `LedFaultNotifier`(`FaultNotifier`の具象実装、`digitalWrite()`するだけ)を
     新規GPIO(**GPIO9**、`kLedAcFaultPin`)へ割り当てた。既存の外付けLED(GPIO4〜8)の
     続きの列にあり配線しやすいと判断した(ユーザー確認済み)。
   - window-drainループ(`loop()`、既存のWS2812/fast-slow LED更新と同じ場所)で
     `gAcInputMonitor.update(rec.vRmsMv)`を呼び、状態が変化した瞬間だけ
     `gFaultNotifiers`内の全notifierへ`notify()`する。
   - バッチ単位で一度でもfaultedだったかを`gBatchPowerFail`にラッチし(`gBatchDiscontinuity`
     と同じパターン)、バッチ確定時に**`kGfrqFlagPowerFail`(bit 3、2026-08-12から予約
     されていたが未配線だった)**へ変換して送信する。これで初めてこのビットが実際に
     立つようになった。
4. **`config.h`**: `kLedAcFaultPin=9`・`kAcFaultVRmsThresholdMv=1000`・
   `kAcFaultSustainWindows=3`を追加。**しきい値・継続window数は実機の断線イベントで
   検証していない未校正のプレースホルダ**(`kPpsEdgeThreshold`と同じ立て付け)。
   正常時の`v_rms_mv`は実測で8000〜10000mV程度なので、1000mVは十分低い側に取った初期値。

## 通知の拡張性について(ユーザーからの要望)

「LED以外の通知(Slack等)も後から足せるように」という要望があった。設計を詰める過程で、
地震計(NamazuHaUrokoGaNai)の欠測監視の構成——デバイスはテレメトリを送るだけで、
`namazu-devices`(DynamoDB生存台帳)+`lambda/watchdog/`(EventBridge定期起動)が
欠測・遅延・OTA停滞を判定してSlack通知する——を確認した。

**Electabuzzもこれに倣う。** `FaultNotifier`はローカル通知(LED、将来ブザー等)専用の
拡張点とし、**Slack等の外部通知はfirmwareから直接HTTP POSTしない**。`kGfrqFlagPowerFail`
でクラウドへ正直に申告する経路は今回のバッチflags配線で既に繋がっているので、
将来クラウド側にwatchdog Lambda(フェーズ9、まだ存在しない。Electabuzzには
`electabuzz-devices`という生存台帳自体はOTA用に既にある)を作れば、ingest済みの
`power_fail`フラグや生存台帳を見て同じパターンでSlack通知できる。firmware側が
外部サービスへの認証情報やエンドポイントを持たずに済む利点もある。

`Uploader::sendAlert()`(batch-uplinkにある速報POST用API、Electabuzzでは
`alertUrl=""`で無効化されたまま)は、今回はあえて使わなかった。地震計の`namzwire`の
アラート専用エンドポイントを前提にした認証ヘッダを持っており、Slack webhookとは
性質が違う。firmware発の速報が要ると分かったら改めて検討する。

## 検証したこと

- `firmware/lib/AcInputMonitor/test/run.sh`: 新規。状態確定・ヒステリシス・境界値・
  reset()の8ケース、全部PASS。
- `.venv/bin/pio run -d firmware -e record -e s3 -e gridfreqtest`: 全部SUCCESS。
  `provision`は既知の理由(secrets.h不在、gitignore対象)で元々失敗するので対象外。
- 既存の全libの`test/run.sh`(Goertzel/GridFreq/Timebase/LedStatus/PpsEdge/GnssNmea)、
  `.venv/bin/python -m pytest lambda/tests`: 変更前と変わらず全部緑。`GridFreq`の
  ゴールデンフィクスチャ突き合わせも変化なし(ワイヤ形式自体は変えていないので当然)。

## 実機確認 (2026-08-15、同日中に追記)

GPIO9へLEDを物理配線した後、`env:record`を実機(`/dev/cu.usbmodem5CCD0331811`)へ
書き込み、AC入力線を実際に抜き差しして動作を確認した。

```
# batch enqueue: records=30 flags=0x0001 ram=0 spill=0
# ac input fault (v_rms_mv=8)
# batch enqueue: records=30 flags=0x0009 ram=0 spill=0     ← 抜線: power_fail(bit3)が立った
...
# batch enqueue: records=30 flags=0x0001 ram=0 spill=0     ← 挿し直し: power_failが消えた
```

**GPIO9のLEDも、抜線で点灯・挿し直しで消灯を目視で確認済み(ユーザー確認)。**
検知(`v_rms_mv=8`、しきい値1000mVを大きく下回る完全な抜線ケース)→LED通知→
バッチflagsへの反映→復帰の一連の経路が実機で動作することが確認できた。

**ただし今回検証できたのは「完全に抜けた」極端なケースだけ。** しきい値(1000mV)・
継続window数(3)が、より緩やかな電圧低下(部分的な接触不良等)に対しても妥当かは
未検証のまま残る。

## 未着手のまま残すもの

- **しきい値・継続window数の精密な校正。** 完全な抜線(v_rms_mv=8)では現在値で
  正しく動作したが、境界付近の挙動(閾値をどこまで下げても安全か、継続window数を
  下げても誤検知しないか)は未検証。
- **物理固定(半田固定・端子台等)。** 検知とは独立の課題として`open-questions.md`に
  残ったまま。
- **クラウド側watchdog Lambda。** `power_fail`フラグは送られるようになったが、
  それを見て実際にSlack通知する仕組み(フェーズ9)はまだ無い。
- **レコード単位の`flags`。** 今回はバッチ単位(`kGfrqFlagPowerFail`)で足りると判断し、
  レコード単位のビット割り当てには踏み込んでいない(既存方針通り、実装が具体化してから
  決める)。
