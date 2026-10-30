"""密码字段的本地加解密（Fernet）：明文只存在于内存与 API 响应中。

密钥存放在每个用户的数据目录（Windows LOCALAPPDATA / macOS Application Support /
XDG 配置目录），只拷贝 config/ 不会带走秘密；换机器或换系统用户后需要重新填写密码。
"""

import functools
import logging
import os
import sys
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from models.interface import InterfaceModel
from models.scheduler import TaskOptionsByTask, TaskOptionValue

logger = logging.getLogger(__name__)

_PREFIX = "mwu-secret:v1:"

_password_fields: dict[str, set[str]] = {}


def _key_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "MWU" / "secret.key"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MWU" / "secret.key"
    return (
        Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        / "MWU"
        / "secret.key"
    )


@functools.cache
def _fernet() -> Fernet:
    """读取密钥文件；不存在时生成并原子落盘（仅当前用户可读）。"""
    path = _key_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp_path.write_bytes(Fernet.generate_key())
        os.replace(tmp_path, path)
        if sys.platform != "win32":
            os.chmod(path, 0o600)
    return Fernet(path.read_bytes())


def configure(interface: InterfaceModel) -> None:
    """记录「选项名 → password 输入名」映射，供加密时定位密码字段。"""
    global _password_fields
    _password_fields = {}
    for option_name, option in (interface.option or {}).items():
        names = {item.name for item in option.inputs or [] if item.password}
        if names:
            _password_fields[option_name] = names


def _seal_value(value: str) -> str:
    if not value or value.startswith(_PREFIX):
        return value
    return _PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def seal_option_map(options: dict[str, TaskOptionValue]) -> dict[str, TaskOptionValue]:
    """返回密码字段已加密的副本；非密码项与已加密值原样保留。"""
    sealed: dict[str, TaskOptionValue] = {}
    for option_name, value in options.items():
        names = _password_fields.get(option_name)
        if names is None or not isinstance(value, dict):
            sealed[option_name] = value
            continue
        sealed[option_name] = {
            field_name: (
                _seal_value(field_value) if field_name in names else field_value
            )
            for field_name, field_value in value.items()
        }
    return sealed


def seal_task_options(task_options: TaskOptionsByTask) -> TaskOptionsByTask:
    return {
        task_name: seal_option_map(options)
        for task_name, options in task_options.items()
    }


def reveal(value: Any) -> Any:
    """返回解密后的递归副本；无法解密的值清空并记录警告（不记录值本身）。"""
    if isinstance(value, str):
        if not value.startswith(_PREFIX):
            return value
        try:
            return _fernet().decrypt(value[len(_PREFIX) :]).decode("utf-8")
        except InvalidToken:
            logger.warning("无法解密已保存的密码字段，已清空；请重新填写")
            return ""
    if isinstance(value, dict):
        return {key: reveal(item) for key, item in value.items()}
    if isinstance(value, list):
        return [reveal(item) for item in value]
    return value
