# バッチ起点を timesync から gFs(NtpTimebase) の回帰に一本化した

## 決めたこと

[前回のログ](2026-08-08-batch-boundary-timestamp-jump.md)で特定した「バッチ境界の
単発スパイク」を、対症療法(API側のdt許容を締める)ではなく**根本修正**で対応した。

`firmware/lib/Timebase/`の`NtpTimebase`に`unixUsAt(uint64_t ticks) const`を追加した。
`fsMicroHz()`と同じ回帰式(`ticks0_`・`unixUs0_`・傾き`cxy_/cxx_`)の逆関数で、
「このティックは絶対時刻で何時か」を答える。`firmware/src/main.cpp`のバッチ開始箇所
(`gCurrentBatch->begin(...)`)を、`timesync::nowUs()`(粗いSMOOTH SNTP壁時計を
都度読み直す)から、`gFs.unixUsAt(currentFramesEstimate())`(バッチ内のレコード間隔
を決めているのと**同じ回帰**)に差し替えた。

## なぜこれで直るか

前回のログで特定した根本原因は「バッチ**内**は精密な`gFs`ベースで滑らかなのに、
バッチ**境界**だけ粗い`timesync`に乗り換わる」という構造的な不整合だった。
`unixUsAt()`はバッチ内のレコード間隔を決めているのと同一の回帰(同じ`ticks0_`・
`unixUs0_`・傾き)から絶対時刻を逆算するので、**バッチ内と境界がそもそも同じ
時刻源**になり、乗り換えという概念自体が無くなる。

`gFs`が(DMAオーバーフロー直後などで)一時的に未規正(`kNominal`)に戻っていた場合は
`timesync::nowUs()`にフォールバックする。この場合はGoertzelの`resetWindow()`も
同時に走っている(`pumpI2s()`のオーバーフロー処理)ので、その前後は元々
`DISCONTINUITY`フラグで区別される区間であり、今回の対策の対象外(=直す理由もない)。

`currentFramesEstimate()`は`framesAt()`(既存の30ms級外挿、公称fsを使っても誤差が
経路ノイズよりはるかに小さいと分かっている用途)を再利用し、`takeI2sSnapshot()`とは
別に振幅ピークをリセットしない読み取り専用の`gFrames`スナップショットを新設した
(NTP問い合わせ間隔の外から呼ぶため、あちらの副作用に巻き込みたくない)。

## 何を確認したか

`firmware/lib/Timebase/test/test_ntp_timebase.cpp`に節8を追加(ホストのg++で実行、
実機不要)。①既知の起点(ticks0, unixUs0)をそのまま復元する ②既知ppmで100秒進めた
ticksから対応する絶対時刻(+100秒)を復元する ③未規正(usable=false)では0を返す、
の3点。既存27件と合わせて全30件緑。`s3`/`gridfreqtest`/`record`の3 envとも
ビルド成功を確認した。

## 何が可能になったか

実機への投入と、境界dtが1.0秒に揃うことの実測確認が残っている。確認できたら
[risks.md](../risks.md)のリスク12・[open-questions.md](../open-questions.md)の該当行を
解消済みに更新する。
