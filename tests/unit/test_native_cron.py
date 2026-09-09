"""Tests for services/native_cron.py — parse + OS conversion."""

import pytest

from services.native_cron import (
    NativeCron,
    aps_dow_to_unix,
    native_crons_may_conflict,
    parse_native_cron,
    to_crontab_line,
    to_launchd_calendar,
    to_schtasks_args,
    unix_dow_to_aps,
)


class TestParseNativeCron:
    """Direct parse_native_cron tests for return values."""

    def test_basic_daily(self):
        nc = parse_native_cron("0 9 * * *")
        assert nc == NativeCron(minute=0, hour=9, day=None, month=None, dow=None)

    def test_dow_7_normalized_to_0(self):
        nc = parse_native_cron("30 4 * * 7")
        assert nc.dow == 0

    def test_specific_dow(self):
        nc = parse_native_cron("0 9 * * 5")
        assert nc.dow == 5

    def test_specific_month_day(self):
        nc = parse_native_cron("0 9 15 6 *")
        assert nc.month == 6
        assert nc.day == 15

    def test_minute_only(self):
        nc = parse_native_cron("45 * * * *")
        assert nc.minute == 45
        assert nc.hour is None


# ---------------------------------------------------------------------------
# to_schtasks_args
# ---------------------------------------------------------------------------


class TestToSchtasksArgs:
    def test_daily(self):
        assert to_schtasks_args(parse_native_cron("0 9 * * *")) == [
            "/SC",
            "DAILY",
            "/ST",
            "09:00",
        ]

    def test_hourly_minute_only(self):
        assert to_schtasks_args(parse_native_cron("5 * * * *")) == [
            "/SC",
            "HOURLY",
            "/ST",
            "00:05",
        ]

    def test_weekly_dow7_normalized_to_sun(self):
        assert to_schtasks_args(parse_native_cron("30 14 * * 7")) == [
            "/SC",
            "WEEKLY",
            "/ST",
            "14:30",
            "/D",
            "SUN",
        ]

    def test_weekly_dow1_is_mon(self):
        assert to_schtasks_args(parse_native_cron("0 9 * * 1")) == [
            "/SC",
            "WEEKLY",
            "/ST",
            "09:00",
            "/D",
            "MON",
        ]

    def test_monthly_with_month(self):
        assert to_schtasks_args(parse_native_cron("0 9 15 3 *")) == [
            "/SC",
            "MONTHLY",
            "/ST",
            "09:00",
            "/D",
            "15",
            "/M",
            "MAR",
        ]

    def test_monthly_day_only(self):
        assert to_schtasks_args(parse_native_cron("0 9 15 * *")) == [
            "/SC",
            "MONTHLY",
            "/ST",
            "09:00",
            "/D",
            "15",
        ]


# ---------------------------------------------------------------------------
# to_launchd_calendar
# ---------------------------------------------------------------------------


class TestToLaunchdCalendar:
    def test_daily_has_minute_and_hour_only(self):
        calendar = to_launchd_calendar(parse_native_cron("0 9 * * *"))
        assert calendar == {"Minute": 0, "Hour": 9}
        assert "Day" not in calendar
        assert "Month" not in calendar
        assert "Weekday" not in calendar

    def test_hourly_has_minute_only(self):
        calendar = to_launchd_calendar(parse_native_cron("5 * * * *"))
        assert calendar == {"Minute": 5}
        assert "Hour" not in calendar

    def test_weekly_has_weekday(self):
        calendar = to_launchd_calendar(parse_native_cron("30 14 * * 1"))
        assert calendar == {"Minute": 30, "Hour": 14, "Weekday": 1}

    def test_monthly_has_day_and_month(self):
        calendar = to_launchd_calendar(parse_native_cron("0 9 15 3 *"))
        assert calendar == {"Minute": 0, "Hour": 9, "Day": 15, "Month": 3}
        assert "Weekday" not in calendar


# ---------------------------------------------------------------------------
# to_crontab_line — round-trip
# ---------------------------------------------------------------------------


class TestToCrontabLine:
    @pytest.mark.parametrize(
        ("cron", "expected"),
        [
            ("0 9 * * *", "0 9 * * *"),
            ("5 * * * *", "5 * * * *"),
            ("59 23 31 12 *", "59 23 31 12 *"),
            # dow 7 归一化为 0
            ("30 14 * * 7", "30 14 * * 0"),
        ],
    )
    def test_round_trip(self, cron, expected):
        assert to_crontab_line(parse_native_cron(cron)) == expected


# ---------------------------------------------------------------------------
# unix_dow_to_aps / aps_dow_to_unix round-trip
# ---------------------------------------------------------------------------


class TestDowConversion:
    @pytest.mark.parametrize("dow", list(range(7)))
    def test_round_trip(self, dow):
        assert aps_dow_to_unix(unix_dow_to_aps(dow)) == dow


# ---------------------------------------------------------------------------
# native_crons_may_conflict — same-minute co-fire detection
# ---------------------------------------------------------------------------


def _nc(cron: str) -> NativeCron:
    return parse_native_cron(cron)


class TestNativeCronsMayConflict:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            # 同一时刻每日触发
            ("0 9 * * *", "0 9 * * *"),
            # 分钟通配的一小时任务 vs 同时刻每日任务（每小时任务每分钟都会撞每日同分任务）
            ("5 * * * *", "5 3 * * *"),
            # 星期不同但 OR 语义无法静态排除：一侧限定星期、另一侧不限日
            ("0 9 * * 1", "0 9 * * *"),
            # 一侧限定星期、另一侧限定具体日（dom/dow OR 语义，保守判冲突）
            ("0 9 * * 3", "0 9 15 * *"),
            # 仅日受限 vs 不限日，同日会撞
            ("30 8 1 * *", "30 8 * * *"),
            # 月受限（日随之受限）vs 不限月同日，该月会撞
            ("0 12 10 6 *", "0 12 10 * *"),
        ],
    )
    def test_conflict_detected(self, a, b):
        assert native_crons_may_conflict(_nc(a), _nc(b))
        # 判定对参数顺序对称
        assert native_crons_may_conflict(_nc(b), _nc(a))

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            # 分钟不同
            ("0 9 * * *", "1 9 * * *"),
            # 小时不同（分钟相同）
            ("0 9 * * *", "0 10 * * *"),
            # 星期不同
            ("0 9 * * 1", "0 9 * * 2"),
            # 具体日不同
            ("0 9 1 * *", "0 9 2 * *"),
            # 月不同（日相同）
            ("0 9 15 1 *", "0 9 15 2 *"),
        ],
    )
    def test_no_conflict(self, a, b):
        assert not native_crons_may_conflict(_nc(a), _nc(b))
        assert not native_crons_may_conflict(_nc(b), _nc(a))
