# アクティブアンテナ到着、屋外(窓越し)で初回fix・約2時間の記録・バイアス電圧実測

## 経緯

発注していたアクティブアンテナ(GPS+BD+GLONASS対応品、→ [log/2026-08-07-antenna-order.md](2026-08-07-antenna-order.md))が到着した。既にu-centorとの疎通は済んでいるNEO-M8N(→ [log/2026-08-12-neo-m8n-ucenter-first-connection.md](2026-08-12-neo-m8n-ucenter-first-connection.md))にアンテナを繋ぎ、段階1の判定(→ [gnss.md](../gnss.md)、[risks.md](../risks.md)リスク5)に着手した。

## 初回接続で3D Fixを確認

窓を開けてアンテナケーブルを屋外に出す形で接続したところ、即座にu-center上で3D Fixが取れた。GPS 4機(G12/G13/G15/G24)・GLONASS 4機(R1/R8/R11/R12)の計8機、PDOP 3.3・HDOP 2.2、SNRは29〜49dB-Hz。

## 約2時間11分の屋外baselineをu-centerで記録

u-centerの録画機能(`COM3___9600_260813_094726 soto.ubx`、5.5MB)で09:48:02〜11:58:57の連続ログを取った。中身をスクリプトでパースして確認した結果:

- **GGAセンテンス7,856件。** fix quality は起動直後の1件を除き全区間`1`(標準GPS fix)を維持
- **捕捉衛星数(numSV)は3〜12機、平均9.4機。** 起動直後は3機・HDOP 9.33(悪い)だったが、数分でHDOPは1〜2台まで収束し安定した
- 高度は起動直後429〜446mの範囲で暴れたが、収束後は430〜440m台

**ただしUBXバイナリの`NAV-PVT`は全区間でわずか8件しか記録されていなかった**(記録開始直後の十数秒分のみ)。原因はCFG-MSGでNAV-PVT/NAV-SATの出力レートを明示的に設定していなかったこと——u-centerが起動時にポーリングした分しか入っていない。GGAで代用はできたが、衛星ごとのCN0(NAV-SATの中身)は今回のログには無い。

## 対策: Configuration ViewでNAV-PVT/NAV-SATを1Hz出力に設定

`View > Configuration View > MSG` で対象メッセージの UART1 レートを`1`に設定する操作を行った。**設定操作は行ったが、次回の記録で実際にNAV-SATが全区間入っているかは未確認**——確認できたら追記する。EEPROM保存(`CFG > Save current configuration`)も合わせて行う想定。

## SMAのバイアス電圧を実測: 約3.2V

[open-questions.md](../open-questions.md)に残っていた未検証項目「SMAにアンテナ用のバイアス電圧が出ているか」を実測した。アンテナを一旦外し、SMAコネクタの中心ピン-GND間をDMMで測定したところ**約3.2V**。u-blox系の典型値である3.3V付近と一致し、**アクティブアンテナへの給電が設計通り機能していると確認できた**(既にfixが取れていたことからの推測ではなく、実測での裏取り)。

## 次にやること

- **定置モード(`CFG-NAV5`のdynModel=Stationary)を設定する**(ユーザーがConfiguration Viewで操作済みと申告、こちらも次回ログでの反映確認が要る)
- **屋内(窓ガラス貼り付け)での記録を取り、屋外baselineと比較する。** USB-TTLアダプタのケーブル長が窓際の設置候補地点に届かないため、USB延長ケーブル待ちで一時中断中
- 数日単位でログを積み、段階1の判定(4機以上を安定維持できるか)を完了させる
