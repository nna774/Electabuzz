import importlib.util
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
LAMBDA_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(LAMBDA_ROOT)

sys.path.insert(0, LAMBDA_ROOT)

GOLDEN_PATH = os.path.join(REPO_ROOT, "testdata", "gfrq_v1_golden.hex")


@pytest.fixture(autouse=True)
def _no_real_aws(monkeypatch):
    """テストから本物のAWSへ届く経路を断つ。

    テストは`NAMZ_DEVICES_TABLE`に本番と同じテーブル名を入れて一部の関数だけ差し替えて
    いるので、差し替え漏れがあると`.envrc`の`AWS_PROFILE`で本番の生存台帳へ書き込む。
    実際にgoldenの`device_id=2`の行が作られ、watchdogが存在しないデバイスの欠測を
    通知し続けた。漏れた呼び出しは接続拒否で即座に失敗させる。
    """
    for k in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "1")


def load_handler(name: str) -> types.ModuleType:
    """`lambda/<name>/handler.py` を `<name>_handler` という名前で読み込む。

    zip の中では各関数の handler.py がルートに置かれる（`handler.handler`）ので、
    素直に `import handler` すると関数を増やしたときに名前が衝突する。
    テスト側だけ名前を分けておけば、本番の配置を歪めずに複数を同時に持てる。
    """
    mod_name = f"{name}_handler"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    path = os.path.join(LAMBDA_ROOT, name, "handler.py")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_hex(path: str) -> bytes:
    """'#' から行末までコメント、空白は全て無視。

    書式は testdata/gfrq_v1_golden.hex の冒頭に書いてある。
    firmware 側のテストも同じファイルを同じ規則で読む。
    """
    out = []
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            out.append(line.split("#", 1)[0].strip())
    return bytes.fromhex("".join(out))
