"""ビルド時にgitの短縮hashをELBZ_FW_VERSIONへ注入する(docs/ota.md)。

pull型OTAはビルドバージョンの一致判定でトリガーするので、焼いたバイナリが
「どのコミットか」を自己申告できないと成立しない。作業ツリーが汚れていたら
-dirtyを付け、未コミット状態を配布版として掴む事故に気付けるようにする
（Namazuのget_fw_version.pyと同じ設計）。
"""

import subprocess

Import("env")  # noqa: F821  (PlatformIOのSConstruct注入シンボル)


def _git_version() -> str:
    project_dir = env["PROJECT_DIR"]
    try:
        rev = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=project_dir, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"
    try:
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=project_dir, stderr=subprocess.DEVNULL
        ).decode().strip())
    except Exception:
        dirty = False
    return rev + ("-dirty" if dirty else "")


env.Append(BUILD_FLAGS=[
    f'-DELBZ_FW_VERSION=\\"{_git_version()}\\"',
])
