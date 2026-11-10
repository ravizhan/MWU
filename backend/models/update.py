from typing import Literal

from pydantic import BaseModel

type PackageType = Literal["full", "resource", "incremental"]


class UpdatePlan(BaseModel):
    """一次更新检查的结论：要不要更新，以及下载哪个包。

    package_type：full 为完整安装包（本体 + 资源）；resource 为只含资源的包，仅当发布所用
    MWU 版本与本地一致时选用；incremental 为 MirrorChyan 增量包，按包内 changes.json 应用。
    client_version 为目标发布所用的 MWU 版本，current_client_version 为本地安装清单记录的
    MWU 版本，未知时均为 None。
    """

    current_version: str
    latest_version: str
    is_update_available: bool
    release_notes: str = ""
    download_source: Literal["mirrorchyan", "github"]
    package_type: PackageType
    client_version: str | None = None
    current_client_version: str | None = None
    download_url: str = ""
    file_hash: str = ""
    file_name: str = ""
