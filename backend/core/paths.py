"""应用路径解析。

打包后程序根与项目目录都是可执行文件所在目录。源码运行时按 MaaPracticeBoilerplate
模板的源码结构组织测试数据：程序根是仓库根（page/、config/、agent/、deps/），
项目目录（interface.json 所在目录，含 resource/ 等 PI 相对路径的基准）是 assets/。
"""

import sys
from pathlib import Path


def resolve_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resolve_project_dir() -> Path:
    root = resolve_app_root()
    if getattr(sys, "frozen", False):
        return root
    return root / "assets"
