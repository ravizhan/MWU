"""应用根目录解析：打包后为可执行文件所在目录，源码运行时为仓库根目录。"""

import sys
from pathlib import Path


def resolve_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
