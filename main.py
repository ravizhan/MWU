# Nuitka 编译参数：第三方包以字节码打包，只把项目代码编译成 C，大幅缩短构建时间和产物体积。
# 新增运行时依赖时在此补一行，漏写不会报错，只会让该包回到 C 编译。
# 字节码模块缓存在 Nuitka 4.3 热缓存下会崩溃（UncompiledPythonModule 缺少 getCompilationMode），必须禁用。
# nuitka-project: --disable-cache=bytecode
# nuitka-project: --noinclude-custom-mode=annotated_doc:bytecode
# nuitka-project: --noinclude-custom-mode=annotated_types:bytecode
# nuitka-project: --noinclude-custom-mode=anyio:bytecode
# nuitka-project: --noinclude-custom-mode=apscheduler:bytecode
# nuitka-project: --noinclude-custom-mode=certifi:bytecode
# nuitka-project: --noinclude-custom-mode=click:bytecode
# nuitka-project: --noinclude-custom-mode=cron_converter:bytecode
# nuitka-project: --noinclude-custom-mode=cryptography:bytecode
# nuitka-project: --noinclude-custom-mode=dateutil:bytecode
# nuitka-project: --noinclude-custom-mode=fastapi:bytecode
# nuitka-project: --noinclude-custom-mode=h11:bytecode
# nuitka-project: --noinclude-custom-mode=httpcore:bytecode
# nuitka-project: --noinclude-custom-mode=httpx:bytecode
# nuitka-project: --noinclude-custom-mode=idna:bytecode
# nuitka-project: --noinclude-custom-mode=json5:bytecode
# nuitka-project: --noinclude-custom-mode=maa:bytecode
# nuitka-project: --noinclude-custom-mode=numpy:bytecode
# nuitka-project: --noinclude-custom-mode=opentelemetry:bytecode
# nuitka-project: --noinclude-custom-mode=PIL:bytecode
# nuitka-project: --noinclude-custom-mode=plyer:bytecode
# nuitka-project: --noinclude-custom-mode=pydantic:bytecode
# nuitka-project: --noinclude-custom-mode=pydantic_core:bytecode
# nuitka-project: --noinclude-custom-mode=pydantic_extra_types:bytecode
# nuitka-project: --noinclude-custom-mode=sentry_sdk:bytecode
# nuitka-project: --noinclude-custom-mode=six:bytecode
# nuitka-project: --noinclude-custom-mode=sqlalchemy:bytecode
# nuitka-project: --noinclude-custom-mode=starlette:bytecode
# nuitka-project: --noinclude-custom-mode=strenum:bytecode
# nuitka-project: --noinclude-custom-mode=typing_extensions:bytecode
# nuitka-project: --noinclude-custom-mode=typing_inspection:bytecode
# nuitka-project: --noinclude-custom-mode=tzdata:bytecode
# nuitka-project: --noinclude-custom-mode=tzlocal:bytecode
# nuitka-project: --noinclude-custom-mode=urllib3:bytecode
# nuitka-project: --noinclude-custom-mode=uvicorn:bytecode
import argparse
import socket
import sys
import time

import httpx
import uvicorn

from backend.app import app
from backend.runtime import app_state

EXIT_SUCCESS = 0
EXIT_FAILED = 1


def _port_in_use(host: str = "127.0.0.1", port: int = 5566) -> bool:
    """端口已被监听即视为已有实例在运行（单实例判定）"""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def delegate_native_dispatch(task_id: str) -> int:
    """已有实例运行时，将系统级任务通过 HTTP 移交给已运行实例"""
    attempts = 6
    for attempt in range(attempts):
        try:
            response = httpx.post(
                "http://127.0.0.1:5566/api/internal/scheduler/native-dispatch",
                json={"task_id": task_id},
                timeout=10,
            )
        except Exception as e:
            # 连接失败：端口已由赢家绑定但服务尚未就绪 → 短退避后重试，避免丢任务。
            # 成功连接后的非 2xx（401/404/409 等）属于应用层拒绝，不重试。
            if attempt < attempts - 1:
                print(
                    f"委托系统级任务失败（第 {attempt + 1}/{attempts} 次，将重试）: {e}",
                    file=sys.stderr,
                )
                time.sleep(2)
                continue
            print(f"委托系统级任务失败: {e}", file=sys.stderr)
            return EXIT_FAILED
        if response.status_code < 200 or response.status_code >= 300:
            print(
                f"委托系统级任务失败: HTTP {response.status_code} {response.text}",
                file=sys.stderr,
            )
            return EXIT_FAILED
        return EXIT_SUCCESS
    return EXIT_FAILED


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MWU 启动参数")
    parser.add_argument(
        "--scheduled-task",
        type=str,
        default=None,
        help="系统级调度任务 ID（冷启动时移交给已运行实例或直接执行）",
    )
    args = parser.parse_args()

    if _port_in_use():
        if args.scheduled_task:
            sys.exit(delegate_native_dispatch(args.scheduled_task))
        print("应用已在运行")
        sys.exit(EXIT_FAILED)

    if args.scheduled_task:
        app_state.pending_scheduled_task_id = args.scheduled_task

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5566,
        timeout_graceful_shutdown=1,
    )
