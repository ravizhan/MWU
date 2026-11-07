# /// script
# dependencies = [
#   "json5",
# ]
# ///
"""把 MaaPracticeBoilerplate 结构的项目整理进 build/（MWU 程序根）。

对应模板 tools/install.py 的 install_resource / install_chores / install_agent：
assets/ 下除 MaaCommonAssets 外的内容平铺到程序根，仓库根的 README.md、LICENSE
与 agent/ 一并拷入，并写入版本号。
"""

import json
import os
import shutil
from pathlib import Path

import json5

ASSETS_DIR = Path("assets")
BUILD_DIR = Path("build")


def main() -> None:
    BUILD_DIR.mkdir(exist_ok=True)
    shutil.copytree(
        ASSETS_DIR,
        BUILD_DIR,
        ignore=shutil.ignore_patterns("MaaCommonAssets"),
        dirs_exist_ok=True,
    )

    # 与模板 configure_ocr_model 一致：项目未自带 OCR 模型时使用默认模型
    ocr_dir = BUILD_DIR / "resource" / "model" / "ocr"
    if not ocr_dir.exists():
        shutil.copytree(
            ASSETS_DIR / "MaaCommonAssets" / "OCR" / "ppocr_v6" / "small", ocr_dir
        )

    for name in ("README.md", "LICENSE"):
        if Path(name).is_file():
            shutil.copy2(name, BUILD_DIR)

    if Path("agent").is_dir():
        shutil.copytree("agent", BUILD_DIR / "agent", dirs_exist_ok=True)

    # 模板的 interface.json 带注释，按 JSON5 读取后写回标准 JSON
    interface_path = BUILD_DIR / "interface.json"
    interface = json5.loads(interface_path.read_text(encoding="utf-8"))
    # deploy/install.yml 导出的是小写 tag 环境变量
    interface["version"] = os.getenv("tag", "dev")  # noqa: SIM112
    interface_path.write_text(
        json.dumps(interface, ensure_ascii=False, indent=4), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
