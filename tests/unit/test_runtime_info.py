"""services/runtime_info.py 单元测试。"""

import sys

from services import runtime_info


def test_app_root_source_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_info, "is_packaged_build", lambda: False)
    monkeypatch.setattr(
        runtime_info, "__file__", str(tmp_path / "services" / "runtime_info.py")
    )
    assert runtime_info.app_root() == tmp_path


def test_app_root_packaged_build(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_info, "is_packaged_build", lambda: True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "MWU.exe"))
    assert runtime_info.app_root() == tmp_path


def test_is_packaged_build_false_in_source():
    # 测试进程即源码运行（无 __compiled__ / sys.frozen），必须判为非打包
    assert runtime_info.is_packaged_build() is False


def test_is_packaged_build_detects_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert runtime_info.is_packaged_build() is True
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert runtime_info.is_packaged_build() is False


def test_debug_override_default_off(monkeypatch):
    monkeypatch.delenv("MWU_DEBUG", raising=False)
    assert runtime_info.is_debug_override() is False


def test_debug_override_env(monkeypatch):
    monkeypatch.setenv("MWU_DEBUG", "1")
    assert runtime_info.is_debug_override() is True
    monkeypatch.setenv("MWU_DEBUG", "0")
    assert runtime_info.is_debug_override() is False
    monkeypatch.setenv("MWU_DEBUG", "")
    assert runtime_info.is_debug_override() is False


def test_telemetry_build_allowed_requires_packaged(monkeypatch):
    monkeypatch.setattr(runtime_info, "is_packaged_build", lambda: False)
    assert runtime_info.telemetry_build_allowed() is False
    monkeypatch.setattr(runtime_info, "is_packaged_build", lambda: True)
    assert runtime_info.telemetry_build_allowed() is True
    monkeypatch.setattr(runtime_info, "is_debug_override", lambda: True)
    assert runtime_info.telemetry_build_allowed() is False


def test_mwu_version_prefers_version_file(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_info, "app_root", lambda: tmp_path)
    (tmp_path / "version").write_text("v9.9.9\n", encoding="utf-8")
    assert runtime_info.mwu_version() == "v9.9.9"


def test_normalize_language():
    assert runtime_info.normalize_language("zh-CN") == "zh_cn"
    assert runtime_info.normalize_language("zh_CN") == "zh_cn"
    assert runtime_info.normalize_language("en-US") == "en_us"
    assert runtime_info.normalize_language("EN_us ") == "en_us"
    assert runtime_info.normalize_language("") == "zh_cn"
    assert runtime_info.normalize_language(None) == "zh_cn"
