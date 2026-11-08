"""运行期间阻止系统休眠（不阻止息屏）。

wakepy 1.0.0 的 Windows 方法在独立线程里调用 SetThreadExecutionState，随后无限期等待释放事件；
激活失败时 wakepy 不会对该方法调用 exit_mode，这个非守护线程永远不退出，应用关闭时进程卡住。
这里用失败时补发释放事件的子类替换原方法。
"""

from collections.abc import Callable

from wakepy import ActivationResult, Mode, keep
from wakepy.methods.windows import WindowsKeepRunning


class _WindowsKeepRunning(WindowsKeepRunning):
    name = "MWU-SetThreadExecutionState"

    def enter_mode(self) -> None:
        try:
            super().enter_mode()
        except BaseException:
            self._release.set()
            raise


def keep_running(on_fail: Callable[[ActivationResult], None]) -> Mode:
    return keep.running(omit=[WindowsKeepRunning.name], on_fail=on_fail)
