# main.cpp統合設計(PPS方式A): PpsEdgeDetector・PpsTimebase・GnssNmeaの配線

## 位置づけ

**これは設計であり、まだmain.cppには手を入れていない。** 3本のライブラリ
(`PpsTimebase`・`PpsEdgeDetector`・`GnssNmea`、いずれも
[log/2026-08-12-pps-timebase-impl.md](2026-08-12-pps-timebase-impl.md)・
[log/2026-08-12-pps-edge-detector-impl.md](2026-08-12-pps-edge-detector-impl.md)・
[log/2026-08-12-gnss-nmea-impl.md](2026-08-12-gnss-nmea-impl.md))はホストテストで
検証済みだが、main.cppはArduino依存で host からは検証できない(コンパイルすら
このセッションのサンドボックスでは確認できない、→ 各ログの「残タスク」)。
**閾値(`kPpsEdgeThreshold`)も未校正のプレースホルダのまま**なので、この設計を
そのままmain.cppへ書き写しても「動く」ことは保証されない——実配線・実測の
前段として、配線の形だけを先に固めておくためのドキュメントである。

## 全体のデータフロー

```
                         ┌─ Core1 (i2sTask / pumpI2s) ───────────────────┐
                         │                                                │
  I2S DMA → buf[i*2]=L ──┼─→ gRecordGoertzel.addSample(l) ──(窓完成)──┐   │
            buf[i*2+1]=R ┼─→ gEdgeDetector.feed(r) ──(エッジ検出)──┐ │   │
                         │                                          │ │   │
                         └──────────────────────────────────────────┼─┼───┘
                                                                     │ │
                                                    gPpsEdgeQueue ◄──┘ │
                                                    gWindowQueue ◄─────┘
                         ┌─ Core0 (loop) ─────────────────────────────────┐
                         │                                                 │
  gPpsEdgeQueue ─→ gPps.addEdge(ticks) ─→ (usable()遷移でGoertzel再武装)  │
  gWindowQueue  ─→ バッチ組み立て ─→ hf.fs_measured_uhz / tb_* / flags   │
  Serial1 bytes ─→ gNmeaReader.feed() ─→ parseGga() ─→ gGnssFix          │
  gFs(NtpTimebase) ─────────────────────→ 絶対時刻(batchStartUs)は従来通り │
                         └─────────────────────────────────────────────────┘
```

**設計の要点は1つ。** PPSは「fsの精度」だけを上書きし、「絶対時刻への固定」は
引き続き`gFs`(NtpTimebase)が担う。この役割分担は
[log/2026-08-12-pps-timebase-impl.md](2026-08-12-pps-timebase-impl.md)で
決めた通りで、`PpsTimebase`に`unixUsAt()`相当を持たせていないのはこのため。

## config.hに足す定数

```cpp
// --- GNSS UART (→ docs/hardware.md「GNSS(NEO-M8N)配線」節。設計案・実配線はまだ) ---
static constexpr int kGnssUartRxPin = 2;         // GPIO2(ESP32 RX)← GNSSのTXD
static constexpr int kGnssUartTxPin = 1;         // GPIO1(ESP32 TX)→ GNSSのRXD
static constexpr uint32_t kGnssUartBaud = 9600;  // u-bloxの既定ボーレート

// --- PPSエッジ検出(R ch)。→ firmware/lib/PpsEdge/ ---
// **未校正のプレースホルダ。** R ch AFEを実配線し、env:gridfreqtestの要領で
// 実際のパルス波形(振幅・立ち上がり時定数)を捕捉してから較正すること。
// 今の値は「型を合わせるためだけの仮の数字」で、実測の裏付けが無い。
static constexpr double kPpsEdgeThreshold = 100000.0;  // TODO: 実測後に決める
static constexpr uint64_t kPpsEdgeRefractorySamples = kFsNominalHz / 2;  // 0.5秒相当

// --- ステータス表示LED追加分(GPIO8は既存の予約を消費する) ---
static constexpr int kLedPpsLockPin = 8;  // 緑LED前提。PPSでロック済み(HIGH)/未ロック(LOW)
```

## pumpI2s()の変更(Core1)

既存の`gRecordGoertzel`と全く同じ「record modeでだけ非null」パターンを踏襲する。

```cpp
// 既存の gRecordGoertzel の隣に追加。
std::atomic<ppsedge::PpsEdgeDetector*> gEdgeDetector{nullptr};
QueueHandle_t gPpsEdgeQueue = nullptr;  // Core1(検出) → Core0(回帰) への橋渡し
```

`pumpI2s()`のサンプルループ内、`g->addSample(l)`のすぐ下に追加:

```cpp
ppsedge::PpsEdgeDetector* edge = gEdgeDetector.load(std::memory_order_relaxed);
if (edge != nullptr) {
  double edgeTicks;
  if (edge->feed(static_cast<double>(r), edgeTicks)) {
    if (gPpsEdgeQueue != nullptr) xQueueSend(gPpsEdgeQueue, &edgeTicks, 0);
  }
}
```

**`edge->feed()`に渡す`r`はフレーム内の生サンプルそのもの。** `PpsEdgeDetector`の
内部サンプルカウンタは、`feed()`を呼んだ回数だけを1ずつ進める素朴なものなので、
**setup()で構築した瞬間から`gFrames`と1対1で対応する**(どちらも同じ実サンプル列を
同じ順序で1個ずつ数えているため)。これが成立する条件は「`gEdgeDetector`を
Goertzelと同時に、i2sTask起動前に一度だけ構築し、以後resetしないこと」
——満たせば、`feed()`が返す`outTicks`は追加のオフセット計算なしにそのまま
`PpsTimebase::addEdge()`へ渡せる絶対ティックになる。**この前提が崩れる唯一の
場面はDMAオーバーフローで、対策は次節。**

## setup()の変更(NAMZ_GRIDFREQ_RECORD)

```cpp
Serial1.begin(kGnssUartBaud, SERIAL_8N1, kGnssUartRxPin, kGnssUartTxPin);

pinMode(kLedPpsLockPin, OUTPUT);
digitalWrite(kLedPpsLockPin, LOW);

gPpsEdgeQueue = xQueueCreate(16, sizeof(double));
gEdgeDetector.store(new ppsedge::PpsEdgeDetector(kPpsEdgeThreshold, kPpsEdgeRefractorySamples),
                    std::memory_order_relaxed);
// ↑ xTaskCreatePinnedToCore(i2sTask, ...) より前に置くこと(既存のgRecordGoertzelと同じ理由)。
```

`gPps`(PpsTimebase本体)はグローバルに1個、`gFs`/`gXtal`と同じ並びで持てばよい:

```cpp
timebase::PpsTimebase gPps(kFsNominalMicroHz);
gnss::NmeaLineReader gNmeaReader;
bool gGnssFix = false;
bool gPpsSourceWasPps = false;  // gFsSourceWasNtpと同じ役目の遷移検出フラグ
```

## loop()の変更(Core0)

### 1. PPSエッジの回帰への取り込み + Goertzel再武装

既存の「NOMINAL→NTP遷移でGoertzelを作り直す」ブロックと**対になる2段目**として
書く。置き場所はNTPクエリのブロックとは独立させ、**毎loop()イテレーションで**
処理する(PPSエッジは1秒に1回来るので、128秒間隔のNTPクエリのタイミングに
縛られると再武装が遅れる)。

```cpp
double edgeTicks;
while (gPpsEdgeQueue != nullptr && xQueueReceive(gPpsEdgeQueue, &edgeTicks, 0) == pdTRUE) {
  gPps.addEdge(edgeTicks);
}

const bool nowPps = gPps.source() == timebase::Source::kPps;
digitalWrite(kLedPpsLockPin, nowPps ? HIGH : LOW);
if (nowPps && !gPpsSourceWasPps) {
  // NTPロック時と同じ手順。PPSはNTPよりさらに精度が良いので、
  // NTPで一度武装した後でもPPSロック時にもう一段作り直す価値がある。
  gridfreq::GoertzelEstimator* prev = gRecordGoertzel.load(std::memory_order_relaxed);
  const uint64_t seedCycles = prev != nullptr ? prev->cyclesQ16() : 0;
  gRecordGoertzel.store(
      new gridfreq::GoertzelEstimator(gFNominalHz, static_cast<double>(gPps.fsMicroHz()) / 1e6,
                                       1.0, seedCycles),
      std::memory_order_relaxed);
  Serial.printf("# pps locked: goertzel re-armed fs=%.6f seed_cycles_q16=%llu\n",
                static_cast<double>(gPps.fsMicroHz()) / 1e6,
                static_cast<unsigned long long>(seedCycles));
}
gPpsSourceWasPps = nowPps;
```

**旧Goertzelオブジェクトを意図的にdeleteしない**——既存のNTP再武装コードと同じ
理由(Core1が参照中の可能性、セッションに数回しか起きないのでリークは実害無し)。

### 2. GNSS UARTの読み取り

```cpp
while (Serial1.available() > 0) {
  const char c = static_cast<char>(Serial1.read());
  if (gNmeaReader.feed(c)) {
    gnss::GgaFix fix;
    if (gnss::parseGga(gNmeaReader.line(), gNmeaReader.lineLen(), fix)) {
      gGnssFix = fix.hasFix();
    }
    // GGA以外の行(GSA/RMC等)はparseGgaがfalseを返すだけで無害に無視される。
  }
}
```

**バイト数に上限を付けていないが、問題にならない。** NMEAは1Hz程度でしか
届かないので、`Serial1.available()`は通常数十バイト程度で空になる
——I2Sのように「詰まって溢れる」規模のデータ量ではない。

### 3. オーバーフロー時にPPS回帰もresetする

既存の「DMAオーバーフローで`gFs.reset()`」ブロックに1行足す。

```cpp
if (i2s.overflows != seenOverflows) {
  Serial.printf("# i2s overflow (total=%u); fs regression reset\n", i2s.overflows);
  gFs.reset();
  gPps.reset();  // ★追加。ドロップしたフレーム分だけgEdgeDetectorの
                 // サンプル計数とgFramesの対応がズレるため、PPS回帰も
                 // 測れなかった区間として切り捨てる(gFsと同じ理由)。
  seenOverflows = i2s.overflows;
}
```

**`gEdgeDetector`自体はresetしない。** ヒステリシス/不応期の状態が
1回ぶん狂う可能性はあるが実害は小さく(次のエッジで自然に復帰する)、
`PpsTimebase`側のreset()で「その前後のデータを回帰に使わない」という
一線は守れている。

### 4. GFRQヘッダの組み立て(バッチ確定時)

既存のブロックを、PPSが使えるときはPPS優先に差し替える。

```cpp
const bool ntpUsable = gFs.source() == timebase::Source::kNtp;
const bool ppsUsable = gPps.source() == timebase::Source::kPps;

hf.fs_measured_uhz = ppsUsable ? gPps.fsMicroHz() : gFs.fsMicroHz();
hf.tb_obs_count = ppsUsable ? gPps.obsCount() : gFs.obsCount();
hf.tb_residual_ns = ppsUsable ? gPps.residualNs() : gFs.residualNs();
hf.timebase_source = ppsUsable ? (ntpUsable ? kGfrqTbPpsNtp : kGfrqTbPps)
                                : (ntpUsable ? kGfrqTbNtp : kGfrqTbNominal);
hf.flags = (gBatchDiscontinuity ? kGfrqFlagDiscontinuity : 0) |
           (ppsUsable ? kGfrqFlagPpsLocked : 0) |
           (gGnssFix ? kGfrqFlagGnssFix : 0);
```

**`fs_measured_uhz`/`tb_obs_count`/`tb_residual_ns`はPPSが使えるかどうかだけで
即座に切り替わる。** バッチの途中でPPSがロックしても、そのバッチはロック後の
値で代表される——既存のNTPロックと同じ「1バッチはこの粒度でしか源を持たない」
という割り切りをそのまま踏襲している。

## この設計で意図的に決めていないこと

- **`kPpsEdgeThreshold`の実値。** R ch AFEを実配線し、`env:gridfreqtest`を
  R ch向けに使うか専用の検証モードを足すかして、実際のPPSパルス波形を
  見てから決める(→[log/2026-08-12-pps-edge-detector-impl.md](2026-08-12-pps-edge-detector-impl.md)
  の残タスク)
- **UBX-MON-VERの自動確認。** u-centerでの手動確認のままでよいという判断は
  据え置き(→[log/2026-08-12-gnss-nmea-impl.md](2026-08-12-gnss-nmea-impl.md))
- **`CFG-TP5`/`CFG-NAV5`をfirmwareから送るかどうか。** u-centerでEEPROMに
  焼けば足りるので、firmware側での自動設定は今回のスコープに含めていない

## 次にやること

1. **この設計をmain.cppへ実際に書き写す。** ホストではコンパイル確認できない
   (Arduino依存)ので、PlatformIOが使える環境での`pio run -e record`が要る
2. R ch AFEの実配線 → `kPpsEdgeThreshold`の較正
3. GNSS UARTの実配線(GPIO1/2) → NMEA疎通確認
4. アンテナ到着後、実際のfix・PPSロックを確認
