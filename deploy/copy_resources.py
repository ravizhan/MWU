import json
import os
import shutil
from pathlib import Path

Path("build").mkdir(exist_ok=True)
shutil.copytree("agent", "build/agent")
shutil.copytree("assets/resource", "build/resource")
shutil.copy2("assets/interface.json", "build")
with Path("build/interface.json").open(encoding="utf-8") as f:
    interface = json.load(f)
# 下游 install.yml 导出的是小写 tag 环境变量
interface["version"] = os.getenv("tag", "dev")  # noqa: SIM112
interface["agent"] = {
    "child_exec": "./python/python.exe",
    "child_args": ["-u", "./agent/main.py"],
    "timeout": -1,
}
with Path("build/interface.json").open("w", encoding="utf-8") as f:
    json.dump(interface, f, ensure_ascii=False, indent=4)

shutil.copytree(
    Path("assets") / "MaaCommonAssets" / "OCR" / "ppocr_v4" / "zh_cn",
    Path("build") / "resource" / "base" / "model" / "ocr",
    dirs_exist_ok=True,
)
