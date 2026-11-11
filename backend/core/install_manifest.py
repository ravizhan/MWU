"""安装清单 mwu-install.json。

由部署流程（deploy/package.py）写入程序根：记录资源版本、所用 MWU 版本，以及安装目录中
分别属于 MWU 本体（client）与资源（resource）的文件。更新器据此决定替换和删除范围，
后端据此判断能否只下载资源包。源码运行时没有清单。
"""

import logging
from pathlib import Path

from pydantic import BaseModel, ValidationError

MANIFEST_NAME = "mwu-install.json"

logger = logging.getLogger(__name__)


class InstallManifest(BaseModel):
    version: str
    mwu_version: str
    client: list[str]
    resource: list[str]

    def overrides_client(self) -> bool:
        """资源是否覆盖了同名的本体文件；资源包无法还原这类文件，只能用完整包更新。"""
        return not set(self.client).isdisjoint(self.resource)


def read_install_manifest(app_root: Path) -> InstallManifest | None:
    """读取安装清单；不存在或损坏时返回 None，更新随之退回完整包。"""
    path = app_root / MANIFEST_NAME
    try:
        return InstallManifest.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return None
    except (OSError, ValidationError) as exc:
        logger.warning("安装清单无法读取，按无清单处理: %s", exc)
        return None
