# AFE校正・ダッシュボード表示を実機・実クラウドへデプロイし、実測との一致を確認した

## 何をしたか

`kAdcAmplitudeCalFactor`校正(PR #46)とダッシュボードの`v_rms_mv`表示(PR #47)を
マージし、以下をデプロイした。

- `tools/publish_ota.sh`でビルド(`env:record`、version `efa8199`)・S3公開
- `tools/request_ota.py request 1 efa8199 --yes`で実機へ配信許可
- 約1分でDynamoDB(`electabuzz-devices`)の`fw_version`が`efa8199`に更新、
  実機が新ファームで再起動(session_id 21→22)したのを確認
- ダッシュボードを`aws s3 sync`+CloudFront invalidationで再デプロイ

## なぜやったか

`v_rms_mv`のAFE校正・ダッシュボード表示という一連の作業(→
[log/2026-08-15-afe-empirical-calibration.md](2026-08-15-afe-empirical-calibration.md)、
[log/2026-08-15-dashboard-v-rms-mv-display.md](2026-08-15-dashboard-v-rms-mv-display.md))
の仕上げとして、実機・実クラウドで校正後の値が実測(DMM)に近づくことを
確認する必要があった。

## 何が分かったか

デプロイ後、本番ダッシュボード(`https://electabuzz.dark-kuins.net`)で
以下を確認した。

- **トランス二次側電圧: 10.18V**(直近30点平均10.179V)——DMM実測10.21V
  (PR #45)との差は**0.3%**。校正前(約8.5V、17〜20%低い)から大幅に改善した
- **壁側電圧(概算): 103V**——実際の壁電圧(102.8〜102.9V、PR #45)とほぼ
  一致。二次側の校正・巻数比(10.08倍)の両方が噛み合った結果
- ビルド版数`efa8199`がダッシュボードの品質テーブルにも反映されていることを
  確認(OTA配信経路の生存確認を兼ねる)

## 何が覆ったか

覆っていない。校正係数(`kAdcAmplitudeCalFactor=1.182`)が実機で機能する
ことが実データで裏付けられた。

## 次に何が可能になったか

`v_rms_mv`・壁側電圧概算とも実用に足る精度で表示できるようになった。
残っているのは:

- フルスケール解釈(`0.3×VCC`)自体の最終確認(データシート再読 or
  オシロでの波形直接確認)——今回の1点校正が「なぜ効くか」の理論的な
  裏付けはまだ無い
- 巻数比・AFE校正とも**1点(または少数回)校正でしかない**——複数回・
  複数条件(負荷変動・気温・日をまたいだ再現性)での再検証はこれから
