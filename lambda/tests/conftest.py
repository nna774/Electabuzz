import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LAMBDA_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(LAMBDA_ROOT)

sys.path.insert(0, LAMBDA_ROOT)

GOLDEN_PATH = os.path.join(REPO_ROOT, "testdata", "gfrq_v1_golden.hex")


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
