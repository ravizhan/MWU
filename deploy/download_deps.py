# /// script
# dependencies = [
#   "requirements-parser"
# ]
# ///

import os
import subprocess
import sys

import requirements

SKIPPED_PACKAGES = {
    "nuitka",
    "requirements-parser",
    "packaging",
    "pip",
    "pylint",
    "maafw",
    "maaagentbinary",
    "pillow",
}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    try:
        with open("requirements.txt") as f:
            packages = [req.name for req in requirements.parse(f) if req.name]
    except FileNotFoundError:
        sys.exit("错误: 找不到 requirements.txt 文件")

    for pkg_name in packages:
        if pkg_name in SKIPPED_PACKAGES:
            continue
        cmd = ["uv", "pip", "install", pkg_name, "--target", "build/deps"]
        print(f"执行命令: {' '.join(cmd)}")
        subprocess.check_call(cmd)


if __name__ == "__main__":
    main()
