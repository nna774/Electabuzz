import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
LAMBDA_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(LAMBDA_ROOT)

sys.path.insert(0, LAMBDA_ROOT)

GOLDEN_PATH = os.path.join(REPO_ROOT, "testdata", "gfrq_v1_golden.hex")


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
