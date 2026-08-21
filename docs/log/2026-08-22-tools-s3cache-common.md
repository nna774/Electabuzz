# tools/s3cache.py としてS3キャッシュラッパーを共通化する

## 何が問題だったか

`tools/README.md`の「S3の`series/`を取ってくる時のキャッシュ」規約に沿って、
`check_pps_soak.py`が`get_object`だけをローカルキャッシュする`CachingS3`クラスを
自前で持っていた。スクリプトが1本のうちは問題にならないが、[NamazuHaUrokoGaNai](https://github.com/nna774/NamazuHaUrokoGaNai)
側で同じ問題（閾値やbandを変えながら同じ区間を何度も読み直す解析のたびにキャッシュ
クライアントをスクラッチで書き直すのが微妙）が起き、`tools/s3cache.py`として
恒久化されていた（[PR #121](https://github.com/nna774/NamazuHaUrokoGaNai/pull/121)）。
Electabuzz側も設計思想が最初から同一（`tools/README.md`に「Namazu側と同じ設計」と
明記している）だったので、同じ切り出しが素直に効く。

## 決めたこと

Namazu版の`tools/s3cache.py`をそのままの設計でElectabuzz側にも作り、
`check_pps_soak.py`の自前`CachingS3`/`_BytesBody`をこれに置き換えた。
`main_checkout_root()`（worktreeでもメインチェックアウト側を指す解決）は
`resolve_bucket()`（`terraform output`のcwd解決）でも使うためスクリプト側に残した。

## 次に何が可能になったか

`series/`を読む新しい解析スクリプトを書くとき、`s3cache.cached_client()`を渡すだけで
キャッシュ付きになる。今のところ利用箇所は`check_pps_soak.py`のみだが、重複実装が
増える前に共通化できた。
