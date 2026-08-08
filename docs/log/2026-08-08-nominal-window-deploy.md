# NOMINAL区間の即記録・事後補正(案A)を実機・実クラウドへ投入した

## やったこと

[log/2026-08-08-nominal-window-implementation.md](2026-08-08-nominal-window-implementation.md)
で実装したコードを、実際のクラウド・実機へ投入した。

### terraform apply

`terraform/`で`build_lambda.sh`を実行し(worktree側の`lambda/`から`api.zip`/
`ingest.zip`を再生成)、`terraform plan`で差分を確認してから`apply`した。

```
Plan: 0 to add, 2 to change, 0 to destroy.
```

`aws_lambda_function.api`と`aws_lambda_function.ingest`のコードのみが
in-place更新された(バケット・IAM・Function URL等は無変更)。`ingest`の
コードハッシュも変わっているが、`lambda/ingest/handler.py`自体は無変更—
`build_lambda.sh`が毎回zipを作り直す都合(pip installやzipのタイムスタンプ)
によるもので、機能的な差分ではない。

apply後、`/recent?minutes=1`を叩いて実データが返ることを確認した(実機は
既にNTPロック済みの状態だったので`freq_hz_corrected`は全てnull——想定どおり、
ロック済みの区間には補正値を出さない)。

### 実機書き込み

worktreeには`firmware/src/secrets.h`と`terraform/terraform.tfvars`が
無かった(gitignore対象)ので、本体の作業ツリー(`/Users/nana/codes/Electabuzz`)
から手でコピーした(→ この2ファイルの扱いは
[log/2026-08-07-terraform-apply-and-secrets.md](2026-08-07-terraform-apply-and-secrets.md)
と同じパターン)。

USBシリアルポートは`pio device list`のVID:PIDで特定した
(`1A86:55D3`=WCH CH343、`067B:2303`=Prolific PL2303は無関係な別デバイスと
判別)。`/dev/cu.usbmodem5CCD0331811`が本機だった。

`pio run -e record -t upload --upload-port /dev/cu.usbmodem5CCD0331811`で
書き込み、`tools/soak_capture.py`と同じ手法(pyserialでopen前にDTR/RTSを
落とす)で起動ログを直接確認した:

```
# electabuzz gridfreq record (PPS/NTPロックとも待たず開始。timebase_sourceはgFs.source()を正直に申告)
# session_id=7
# wifi connected ip=10.255.255.158 rssi=-57
# f_nominal detected: 50Hz (mag50=60156823353 mag60=2587955549)
[uploader] spill files on boot: 0
# recording started immediately (timebase_source=NOMINAL); will re-arm goertzel once fs locks via NTP (~600s)
# fs n=1 source=NOMINAL ppm=0.0000 resid_ns=4294967295 l_pp=7905931 r_pp=3640
```

**設計どおり、起動直後から記録が始まっている。** 「waiting for fs to lock」で
10分間止まっていた旧挙動は無くなった。

## 次に何が可能になったか

この起動でNOMINAL→NTPの遷移を実際に跨ぐ(約600秒後)。遷移後、①該当セッションの
`timebase_source`がNOMINALからNTPへ切り替わること②`/recent`で
`freq_hz_corrected`がそのNOMINAL区間に遡って現れること③ダッシュボードで
3本の線が実データで意図どおりに出ることを確認するのが次の一手
(600秒経ってから`/recent?minutes=15`等で確認できる)。
