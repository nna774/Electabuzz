# 2026-08-14 `v_rms_mv` をfirmwareへ実配線した

## 背景

[2026-08-13の決定](2026-08-13-vrms-basis-point-decision.md)で`v_rms_mv`の基準点は
「トランス二次側の実効値[mV]」と確定していたが、`main.cpp:688`は
`gridfreq::addRecord(*gCurrentBatch, rec.cyclesQ16, /*vRmsMv=*/0, /*flags=*/0)`の
まま実値を出していなかった。決定ログが「未着手のまま残すもの」として明記していた
firmware配線(ADCコード→volt換算)を実装した。

## 実装したこと

**経路: `GoertzelEstimator::magnitude()` → ADCコード振幅 → PCM1808入力(node A)の
電圧振幅 → AFE分圧を逆算してトランス二次側の電圧振幅 → 実効値[mV]。**

1. `firmware/src/config.h`に AFE の物理定数を追加した(R1=100kΩ・R2=6.8kΩ・
   PCM1808入力インピーダンス60kΩ typ・VCC実測4.84V・ADCフルスケールコード2^23)。
   **すべて`docs/hardware.md`に既にある実測値・設計値の書き写しで、新規の実測は
   していない。** 実効分圧比`kAfeDividerRatio`はここから逆算する定数式で持つ
   (ハードコードした数値を書かない——分圧網を直したら自動で追従する)。
2. `firmware/src/main.cpp`に`computeVRmsMv(magnitude, windowSamples)`を追加した。
   - 単一ビンDFTの振幅は正弦波1本なら概ね`A*N/2`になる
     (`firmware/lib/Goertzel/test/test_goertzel.cpp`で検証済みの関係をそのまま使う)
   - フルスケール(コード=2^23)が`0.3×VCC`[V]に対応する
     (データシートの`0.6×VCC`Vppの半分。→`hardware.md`「アナログフロントエンド」節)
   - AFE分圧(ADC入力インピーダンスの負荷込み)を逆算してトランス二次側へ戻す
   - ピークからRMSへ(÷√2)、Vからmvへ(×1000)、u16へclamp
3. `WindowRecord`に`vRmsMv`フィールドを追加し、`pumpI2s()`内で
   `g->addSample()`がtrueを返した直後(=`magnitude()`が有効な唯一のタイミング)に
   `computeVRmsMv()`を呼んで確定させた。`loop()`側の`addRecord()`呼び出しは
   この値をそのまま渡すだけにした。

## 検証したこと

**往復計算(Python)で数値の整合を確認した。** `docs/hardware.md`の実測値
(2026-08-03、100V系コンセント駆動・無負荷、DMM実測10.3VAC)を入力として
「secondary_rms → 期待されるADCコード振幅」を計算し、それを`computeVRmsMv()`と
同じ式で逆算すると`10300mV`が誤差なく戻ることを確認した。副産物として、この時の
ADCコード振幅がフルスケールの**57.7%**になることも分かり、`hardware.md`に実機で
記載済みの値(「実測の無負荷出力29.1Vpp では FS比57.7〜63.8%」)と一致した——
**独立に導いた数値が既存の実機記載と一致した**ことが実装の妥当性の裏付けになる。

firmware側は以下で確認した。テストにADC実データは要らない(`computeVRmsMv()`は
純粋関数で、Goertzelのユニットテストが`magnitude()≈A*N/2`の関係を別途検証済み)。

```sh
.venv/bin/pio run -d firmware -e s3 -e gridfreqtest -e record  # 3つともSUCCESS
firmware/lib/Goertzel/test/run.sh                              # PASSED (0 failures)
```

`provision`envは元々`secrets.h`(gitignore対象)が無いと失敗する既知の状態で、
今回の変更とは無関係。

## 未着手のまま残すもの

- **実機での確認。** `v_rms_mv`が実際に送信されデータとして`series/`に着弾するか、
  実測トランス電圧(DMM)と記録値が近い値になるかは、この変更ではまだ確認していない
- **巻数比の精密測定**(壁側電圧が要る場面が来たら。→`open-questions.md`)は
  この変更の対象外——`v_rms_mv`自体はトランス二次側基準で完結している
- **`flags`の空きビット割り当て**(AC入力線断線検知等)は別件のまま
