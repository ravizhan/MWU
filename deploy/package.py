# /// script
# ///
"""生成安装清单与资源包目录。

在 copy_resources.py、download_deps.py 之后运行。约定：
- client/ 是原样解压的 MWU 发布包，其中文件归 MWU 本体；
- build/ 是完整安装（MWU + 资源），其余文件归资源。资源覆盖了本体的同名文件（内容不同）时，
  该路径同时出现在 client 与 resource 中，客户端据此在下次更新时改用完整包，以便撤销覆盖。
输出：
- build/mwu-install.json：完整包内的安装清单；
- resource/：资源包内容（资源文件 + 同一份清单），供 install.yml 压缩为资源包。
更新器依据清单决定替换与删除范围，后端依据 mwu_version 判断能否只更新资源。
"""

import json
import os
import shutil
from pathlib import Path

CLIENT_DIR = Path("client")
BUILD_DIR = Path("build")
RESOURCE_DIR = Path("resource")
MANIFEST_NAME = "mwu-install.json"


def list_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def main() -> None:
    client = list_files(CLIENT_DIR)
    resource = {
        rel
        for rel in list_files(BUILD_DIR) - {MANIFEST_NAME}
        if rel not in client
        or (CLIENT_DIR / rel).read_bytes() != (BUILD_DIR / rel).read_bytes()
    }
    manifest = {
        # deploy/install.yml 导出的是小写 tag 环境变量
        "version": os.environ["tag"],  # noqa: SIM112
        "mwu_version": (CLIENT_DIR / "version").read_text(encoding="utf-8").strip(),
        "client": sorted(client),
        "resource": sorted(resource),
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    (BUILD_DIR / MANIFEST_NAME).write_text(text, encoding="utf-8")

    shutil.rmtree(RESOURCE_DIR, ignore_errors=True)
    for rel in resource:
        dst = RESOURCE_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BUILD_DIR / rel, dst)
    (RESOURCE_DIR / MANIFEST_NAME).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
