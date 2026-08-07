# Goertzelをfirmwareへ移植し、PPSを待たずにGFRQの記録・送信を始める

## やったこと

`docs/roadmap.md`フェーズ3が「C++移植・firmware組み込みはフェーズ2(PPS)待ち」と
していた方針を覆し、以下を実装した。

1. **`firmware/lib/Goertzel/`（新規）**: `tools/gridfreq/goertzel.py`の
   リアルタイム・逐次版。標準的な2次IIR再帰(状態2個)で単一ビンDFTを計算し、
   窓(既定1秒)が確定するたびに絶対累積位相(`cyclesQ16`, Q16固定小数点)と
   瞬時周波数を更新する。Arduino非依存、ホストのg++でテストできる
   （`test/run.sh`、13ケース全緑）。50/60Hz判別も同じクラスを2本(50Hz用/60Hz用)
   並走させて振幅を比べるだけの形で実装した(後述)
2. **`firmware/src/main.cpp`に`NAMZ_GRIDFREQ_RECORD`ビルドモードを追加**
   （`platformio.ini`に`[env:record]`）。`fs`がNtpTimebaseで規正できるまで
   (600秒以上・8標本以上)は何もせず、規正できた時点でGoertzelを起動、
   窓が確定するたびに`GFRQ`レコードを1件積み、30件でバッチを閉じて
   `timebase_source=NTP`で`Uploader`へ送る
3. **`batch-uplink`のpinをv1.0.0からv1.6.0へ上げた**（ユーザー指示）。理由は後述

## なぜ「C++移植はフェーズ2待ち」を覆したか

`docs/log/2026-08-07-goertzel-reference.md`(Python参照実装を書いた回)の時点では
「C++移植・firmware組み込みは方式A/Bの選択が構造に効く可能性がある」として
保留していた。これをユーザーと検討し直すと:

- **PPS(方式A/B)が効くのは「結果をどうGNSS絶対時刻に固定するか」という後段の
  較正だけ**で、Goertzel本体(単一ビンDFTで位相・累積位相を出す部分)は
  Lチャンネルの生サンプルと`fs`(の値、出処は問わない)だけで完結する。
  これは参照実装を書いた回に既に確認済みの整理だった
- **`GFRQ`ヘッダには`timebase_source`が最初から用意されている**
  (→[wire-format.md](../wire-format.md))。PPSが無い区間を「NTP品質」と
  正直に申告して送れば、「測れなかった区間を測れたように見せるな」という
  不変条件(→[timebase.md](../timebase.md))を破らずに済む。**バッチに品質が
  ちゃんと入るなら、PPS到着を待つ理由は無い**という判断

したがって、C++移植・GFRQ送信をフェーズ2の前に始めることにした。
**フェーズ2(PPS)が通ったら**、`NAMZ_GRIDFREQ_RECORD`モードは
`timebase_source`を`NTP`から`PPS`(または`PPS_NTP`)に切り替えるだけで済む
——`GoertzelEstimator`にも`GridFreqWire`にもPPS固有の分岐は無い。

## 実装の要点

### GoertzelEstimatorを逐次・再帰にした理由

Python参照実装は窓ぶん(≈48000サンプル)のバッファへ`Σx[n]exp(-jθn)`を直接計算する。
firmwareではこれをそのまま持ち込むと、(a) 48000サンプル×2(50/60Hz判別用に2本
走らせると×2)ぶんのバッファ、(b) 96000回/秒のtrig呼び出し、の両方が重い。
標準的なGoertzelアルゴリズムは2次IIR再帰(状態は`s1`/`s2`の2個、係数`2cos(θ)`は
窓ごとに1回だけ計算)で同じ和を計算できるので、これに置き換えた。
数学的に同じ値を計算していることは`test/test_goertzel.cpp`で確認している:

- 符号の検証: 入力を公称より+0.2Hz/-0.2Hz振ったとき、`freqHz()`も同じ符号で動くこと
  (再帰の位相の向きを取り違えると、ここが逆に出る)
- 振幅の検証: 振幅`A`の正弦波1本に対し`magnitude()`が`A*N/2`に一致すること
- 高調波除去: 3倍高調波を基本波と同程度の振幅で混ぜても`freqHz()`が動かないこと
  (`docs/signal-processing.md`が「高調波は直交ビンに落ちて原理的に除去される」
  とした設計そのものの検証)
- `resetWindow()`: DMA溢れ相当のギャップを模して、`cyclesQ16`が巻き戻らず、
  直後の窓が新しい基準点(位相差ゼロ)から再開すること

### 50/60Hz判別もバッファを持たない

判別用に1秒ぶんのL chサンプル(≈188KB)をSRAMへバッファするのは避けた
(→[hardware.md](../hardware.md)の「PSRAMは意図的に有効化しない」)。
代わりに`GoertzelEstimator`を50Hz用・60Hz用の2本立て、同じサンプル列を
両方に流し込んで窓の終わりに`magnitude()`を比べるだけにした。ライブラリ自体は
Python版と対になる一括版`detectNominalFreq()`も持つ(テスト済み)が、firmwareの
`setup()`では使っていない。

### 記録開始のゲート

`NAMZ_GRIDFREQ_RECORD`は起動直後にGoertzelを始めない。`fs`が`NtpTimebase`で
規正できる(`NtpTimebase::kMinObs`=8標本・`kMinSpanSeconds`=600秒)まで待ち、
規正できた時点の`fs`でGoertzelを1回だけ構成する。**Goertzelはコンストラクタで
`fs`を固定する設計**なので(`docs/log/2026-08-07-goertzel-reference.md`の
Python版と同じAPI)、以後`fs`がわずかにドリフトしても追随しない
——追随させたいなら呼び出し側が作り直す、という設計に留めた
(初回ロック後の再構成は今回のスコープに入れていない)。

DMA溢れを検知したら該当窓を`resetWindow()`で捨て、次に確定するバッチへ
`GfrqFlagDiscontinuity`を立てる。**`cyclesQ16`は巻き戻さない**——絶対値で持つ
という`docs/storage.md`の不変条件を、記録モードでも同じ形で守っている。

### batch-uplinkのpinをv1.6.0へ

当初`docs/batch-uplink.md`は「Electabuzzはv1.0.0を指し続ける」としていたが、
ユーザーからv1.6.0(最新)を使ってよいという指示があった。実際に調べると:

- v1.1.0〜v1.6.0はすべてNamazu側がOTA・リモート再起動・生存台帳表示のために
  切ったタグで、**いずれも`Uploader`への新規オプトイン引数か新規メソッドの追加のみ**
  (Namazu自身のログにも「Electabuzzの既定動作は変えない」設計と明記されている)
- 実際、**Namazu自身のpinは既にv1.6.0**だった(`firmware/platformio.ini`実測)。
  「地震計はv1.0.0に留まり続ける」という`docs/batch-uplink.md`の当初の記述は
  既に実態と合っていなかった
- 記録モードで使いたい`dropOldestWhenFull`(RAM/spill満杯時に最古を捨てる
  オプトイン動作)はv1.1.0で追加されたもので、v1.0.0のままでは使えない

pinをv1.6.0へ上げ、`docs/batch-uplink.md`の「現在の pin」を主張している箇所を
書き直した(切り出し当初の経緯・「なぜ一般化を先にやるか」という判断プロセスの
説明はそのまま残してある——それ自体は今も正しい判断だったため)。

## 分かったこと・確認したこと

- `firmware/lib/GridFreq/test/run.sh`・`firmware/lib/Timebase/test/run.sh`・
  `firmware/lib/Goertzel/test/run.sh`が全緑(v1.6.0のBatchでもゴールデン
  フィクスチャが1バイトも変わらないことを確認——`Batch`のABIはv1.0.0から
  変わっていない)
- `pio run -e s3 -e gridfreqtest -e record`が全て緑(soak・フェーズ1疎通確認・
  新しい記録モードの3ビルドとも通る)
- **実機には投入していない。** soakが母艦で走行中で、繋ぎ直すと回帰が
  積み直しになるため(→CLAUDE.mdの注意)。`record`モードの実地確認
  (`fs`ロック後にGoertzelが実際に起動し、バッチが`ingest`まで届くか)は
  次にポートを開く機会に回す

## 次に何が可能になったか

`env:record`は`secrets.h`に`kDeviceId`/`kIngestUrl`/`kHmacSecret`を埋めて
焼けば動く状態にある。実地確認では最低限:

- `fs`ロックまで(NTPで600秒以上)待って`# goertzel armed`ログが出ること
- バッチが`# batch enqueue`ログを吐き、`ingest` Lambda側で`series/`に着弾すること
- `timebase_source`が`NTP`(値`1`)として記録され、`f_nominal_mhz`が`50000`に
  判別されること

を見る。フェーズ2(PPS)が実装できたら、`timebase_source`の切り替えと
`GfrqFlagPpsLocked`/`GfrqFlagGnssFix`の配線が残作業になる
(Goertzel本体・GFRQ送信経路は変更不要)。
