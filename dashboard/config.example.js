// terraform output の api_url をここに入れて config.js として保存・アップロードする。
// （画面の入力欄でも上書きでき、その場合 localStorage に保存される）
// api_url は CloudFront 経由(30秒キャッシュ)のURL。生の Function URL が要る時は
// api_url_direct を使う(→ terraform/api_cache.tf)。
window.ELBZ_API_URL = "https://xxxxxxxxxxxxx.cloudfront.net";
