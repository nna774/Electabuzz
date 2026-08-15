# PCM1808データシートを読み直し、フルスケール解釈の仮説を確認する

## 何をしたか

AFE経験校正(`kAdcAmplitudeCalFactor=1.182`、→
[log/2026-08-15-afe-empirical-calibration.md](2026-08-15-afe-empirical-calibration.md))
で局在まで特定した「ADCコード→node A電圧」のフルスケール解釈(`0.3×VCC`)について、
TI公式のPCM1808データシート(`SLES177B`、2015年8月改訂版、
https://www.ti.com/lit/ds/symlink/pcm1808.pdf )を直接取得して該当箇所を読んだ。

## なぜやったか

`config.h`のコメントで「オーディオ用ADCでは0.6×VCCがheadroomを見込んだ公称値で、
物理クリップ点はもっと外側、というケースがありうる」という仮説を立てていたが、
これは推測でしかなく検証していなかった。1.182倍のズレの最後の容疑として、
データシートの記述を実際に確認する必要があった。

## 何が分かったか

以下を原文のまま引用する。

- §6.3 Recommended Operating Conditions:
  「Analog input voltage, full scale (–0 dB) | VCC = 5V | ... | **3** | Vp-p」
- §6.5 Electrical Characteristics — ANALOG INPUT:
  「Input voltage | | **0.6 VCC** | Vp-p」
  「Center voltage (VREF) | | 0.5 VCC | V」
  「Input impedance | | 60 | kΩ」(TYPのみ、MIN/MAX記載なし)
- DC ACCURACY: 「Gain error | TYP ±3% | MAX ±6% of FSR」

`VCC=5V`のとき`0.6×VCC=3Vpp`で、§6.3の値と§6.5の値が完全に一致する。かつ
§6.3は明示的に「full scale (–0 dB)」というラベルを付けている——**0.6×VCC Vppは
headroomを見込んだ公称値ではなく、0dBFS(デジタルコードのフルスケール)
そのものとして定義されている。** firmwareの理論式(`0.3×VCC`をコード2^23の
折り返し点とする)は、データシートの定義と完全に一致していた。

**「フルスケール解釈が違うのでは」という仮説は、データシートでは裏付けられず
棄却された。** データシート上でMIN/MAXの記載が無いのは`Input impedance`
(60kΩ、TYPのみ)だけで、`Gain error`はMAXでも±6%——単独では1.182倍(18.2%)を
説明できない。

## 何が覆ったか

`config.h`・`hardware.md`にあった「フルスケール解釈(headroom仮説)が容疑」という
記述を、「データシート上は棄却された」に書き換えた。**校正係数(1.182)自体は
変更していない**——実測値としては引き続き有効だが、理論的な裏付けが無いまま
残ったことになる。

## 次に何が可能になったか

データシートのレベルでは1.182倍のズレを説明できないと分かったので、これ以上の
原因追及にはデータシート読解ではなく実測が要る。

- オシロスコープでnode Aの波形とADCコード(またはfirmwareが計算する`ampCode`)を
  同時に見て、振幅推定のどこかにズレが無いか直接確認する
- `pumpI2s()`のI2Sデータ解釈(24bit符号付きデータを32bit枠から`>>8`で戻す処理)
  自体にビット単位のバグが無いか、コードレベルで再点検する

どちらもこのセッションでは未着手。校正係数はこのまま「1点実測に基づく経験値、
理論的根拠は不明」という位置づけで運用を続ける。
