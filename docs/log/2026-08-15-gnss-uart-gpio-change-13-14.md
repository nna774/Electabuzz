# GNSS UART の候補ピンを GPIO1/2 → GPIO13/14 に変更した

## 経緯

`docs/hardware.md`の配線設計案(2026-08-12)ではGNSS UARTの候補ピンをGPIO1(TX)/GPIO2(RX)としていたが、現物での取り回しの都合でGPIO9〜14あたりの方が配線しやすいと判明した。除外リスト(GPIO33〜37/26〜32/43-44/19-20/0-3-45-46/15-18/4-8)のいずれにも当たらない未使用GPIOであることを確認した上で、GPIO13(TX)/GPIO14(RX)に決定した。

GPIO46は除外リストのストラップ対象であることに加え、ESP32-S3では入力専用ピンなのでTXには使えないと分かった——候補から外す理由として記録しておく。

## 変更内容

- `firmware/src/config.h`: `kGnssUartTxPin`を1→13、`kGnssUartRxPin`を2→14に変更
- `docs/hardware.md`: GNSS配線の設計案節を新しいピン番号に合わせて更新

実配線・実測はまだで、この節は引き続き設計案のままである。呼び出し箇所は`main.cpp:584`の`Serial1.begin()`一箇所のみで、`env:record`ビルドがSUCCESSすることを確認した。
