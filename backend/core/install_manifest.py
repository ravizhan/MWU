"""安装清单 mwu-install.json。

由部署流程（deploy/package.py）写入程序根：记录资源版本、所用 MWU 版本，以及安装目录中
分别属于 MWU 本体（client）与资源（resource）的文件。更新器据此决定替换和删除范围，
后端据此判断能否只下载资源包。源码运行时没有清单。
"""

from pathlib import Path

from pydantic import BaseModel

MANIFEST_NAME = "mwu-install.json"


class InstallManifest(BaseModel):
    version: str
    mwu_version: str
    client: list[str]
    resource: list[str]


def read_install_manifest(app_root: Path) -> InstallManifest | None:
    path = app_root / MANIFEST_NAME
    if not path.is_file():
        return None
    return InstallManifest.model_validate_json(path.read_bytes())
