"""跨平台 cron 转换与冲突判定（纯函数，无 I/O）。

输入为 ``models.scheduler.parse_portable_cron`` 提取出的 :class:`NativeCron`
（严格子集：5 字段、单值或 *、分钟必须具体），此处只做 OS 格式转换。
"""

from models.scheduler import NativeCron

# Unix 星期（0=周日）→ schtasks 三字母英文缩写
_SCHTASKS_DOW = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")

# 月份 1-12 → 三字母英文缩写
_SCHTASKS_MONTHS = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)


def to_schtasks_args(nc: NativeCron) -> list[str]:
    """转换为 ``schtasks /Create`` 的调度参数段（``/SC`` 之后的部分）。

    映射规则（选择最简单且正确的组合）：
    - 仅分钟受限（hour 为 None）→ ``/SC HOURLY /ST 00:MM``，每小时在该分钟触发。
    - 小时受限、无日/星期/月 → ``/SC DAILY /ST HH:MM``。
    - 星期受限 → ``/SC WEEKLY /ST HH:MM /D DOW``（三字母英文，Unix 0=周日）。
    - 月与日同时受限 → ``/SC MONTHLY /ST HH:MM /D day /M MON``（三字母英文月份）。
    - 仅日受限（无月）→ ``/SC MONTHLY /ST HH:MM /D day``（schtasks 缺省每月执行）。
    """
    if nc.hour is None:
        return ["/SC", "HOURLY", "/ST", f"00:{nc.minute:02d}"]

    start = f"{nc.hour:02d}:{nc.minute:02d}"
    if nc.dow is not None:
        return ["/SC", "WEEKLY", "/ST", start, "/D", _SCHTASKS_DOW[nc.dow]]
    if nc.month is not None:
        assert nc.day is not None  # 解析规则保证
        return [
            "/SC",
            "MONTHLY",
            "/ST",
            start,
            "/D",
            str(nc.day),
            "/M",
            _SCHTASKS_MONTHS[nc.month - 1],
        ]
    if nc.day is not None:
        return ["/SC", "MONTHLY", "/ST", start, "/D", str(nc.day)]
    return ["/SC", "DAILY", "/ST", start]


def to_launchd_calendar(nc: NativeCron) -> dict[str, int]:
    """转换为 launchd ``StartCalendarInterval`` 字典。

    ``Minute`` 恒有；``Hour``/``Day``/``Month``/``Weekday`` 仅在该字段受限时出现
    （launchd 省略字段表示任意值，与 cron 的 ``*`` 对应）。
    """
    calendar: dict[str, int] = {"Minute": nc.minute}
    if nc.hour is not None:
        calendar["Hour"] = nc.hour
    if nc.day is not None:
        calendar["Day"] = nc.day
    if nc.month is not None:
        calendar["Month"] = nc.month
    if nc.dow is not None:
        # launchd 与 Unix 同为 0/7=周日；解析后 dow 已归一化为 0-6
        calendar["Weekday"] = nc.dow
    return calendar


def to_crontab_line(nc: NativeCron) -> str:
    """转换为标准 crontab 5 字段行；None 写 ``*``，星期 0 写 ``0``。"""
    return " ".join(
        str(value) if value is not None else "*"
        for value in (nc.minute, nc.hour, nc.day, nc.month, nc.dow)
    )


def _days_overlap(a: NativeCron, b: NativeCron) -> bool:
    """判断两个严格 cron 的「日期维度」是否可能同一天触发。

    month/day/dow 任一字段两侧均受限且取值不同 → 不可能同日；
    其余组合（含一侧限定星期、另一侧限定具体日的 OR 语义）保守视为可能同日。
    """
    if a.month is not None and b.month is not None and a.month != b.month:
        return False
    if a.day is not None and b.day is not None and a.day != b.day:
        return False

    # 一侧限定星期、另一侧限定具体日（含月）时，cron 的 dom/dow 为 OR 语义：
    # 无法用静态字段比较，保守判定为可能重叠。
    return not (a.dow is not None and b.dow is not None and a.dow != b.dow)


def native_crons_may_conflict(a: NativeCron, b: NativeCron) -> bool:
    """判断两个严格 cron 表达式是否可能在同一分钟内同时触发。

    用于系统级唤醒任务的创建/更新校验：冷启动单例假设要求任意两个
    原生唤醒不得同分钟触发，否则两个进程会竞态绑定端口导致任务丢失。
    判定保守（宁可误报冲突）：任一字段两侧均受限且不同才视为不冲突。
    """
    if a.minute != b.minute:
        return False
    if a.hour is not None and b.hour is not None and a.hour != b.hour:
        return False
    return _days_overlap(a, b)


def unix_dow_to_aps(dow: int) -> int:
    """Unix 星期（0=周日）→ APScheduler 星期（0=周一）。"""
    return (dow + 6) % 7


def aps_dow_to_unix(dow: int) -> int:
    """APScheduler 星期（0=周一）→ Unix 星期（0=周日）。"""
    return (dow + 1) % 7
