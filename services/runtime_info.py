"""集中提供应用根路径、MWU 版本、运行语言规范化和发布/调试判定。

此前这些信息散落于 main.py、maa_utils.py、settings_io.py、agent_service.py，
且各自实现略有差异。本模块是唯一权威来源。

注意：本模块不得导入项目内其他模块（避免循环导入），仅使用标准库。
"""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path


def app_root() -> Path:
    """应用根目录。

    打包构建（Nuitka `__compiled__` / `sys.frozen`）取可执行文件所在目录；
    源码运行取本模块上两级目录（即仓库根 / 应用根）。
    """
    if is_packaged_build():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_packaged_build() -> bool:
    """是否为打包（发布/调试构建）运行。

    Nuitka 会在每个编译模块的全局命名空间注入 `__compiled__`；
    PyInstaller 等设置 `sys.frozen`。不使用 `__debug__` 判断。
    """
    if "__compiled__" in globals():
        return True
    return bool(getattr(sys, "frozen", False))


def is_debug_override() -> bool:
    """MWU_DEBUG=1 显式调试标记。

    仅用于进一步禁用遥测；不能反向允许源码运行上报。
    """
    import os

    return os.environ.get("MWU_DEBUG", "").strip() == "1"


def telemetry_build_allowed() -> bool:
    """当前构建形态是否允许（经用户授权后）发送遥测。

    打包 stable/beta 构建允许；源码运行、测试、MWU_DEBUG=1 强制禁用。
    """
    return is_packaged_build() and not is_debug_override()


def mwu_version() -> str:
    """MWU 客户端版本。

    优先读取应用根目录下的 `version` 文件（发布包由 CI 写入）；
    读取失败（含源码开发环境，该文件滞后）时回退到包元数据。
    """
    version_file = app_root() / "version"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    try:
        return metadata.version("MWU")
    except metadata.PackageNotFoundError:
        return "unknown"


def normalize_language(locale: str | None) -> str:
    """将 UI locale 规范化为 PI 语言键形式。

    "zh-CN" / "zh_CN" / "ZH_CN" → "zh_cn"；空值回退 "zh_cn"。
    """
    if not locale or not locale.strip():
        return "zh_cn"
    return locale.strip().replace("-", "_").lower()
