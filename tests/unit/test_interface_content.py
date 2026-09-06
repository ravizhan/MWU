"""services/interface_content.py 单元测试。"""

import httpx
import pytest

from models.interface import (
    Controller,
    InterfaceModel,
    Resource,
    Task,
)
from services.interface_content import (
    InterfaceContentError,
    InterfaceContentService,
)


def _make_interface(tasks=None):
    return InterfaceModel(
        interface_version=2,
        name="Test",
        controller=[Controller(name="adb", type="Adb")],
        resource=[Resource(name="main", path=["resource"])],
        task=tasks or [Task(name="A", entry="A")],
    )


def _service(tmp_path, translations=None, tasks=None):
    return InterfaceContentService(
        _make_interface(tasks=tasks), tmp_path, translations or {}
    )


# ---------------------------------------------------------------------------
# i18n 解析
# ---------------------------------------------------------------------------


class TestResolveI18n:
    def test_plain_text_not_reference(self, tmp_path):
        svc = _service(tmp_path)
        assert svc.resolve_i18n("普通文本", "zh-CN") is None
        assert svc.resolve_i18n("$", "zh-CN") is None

    def test_reference_lookup_nested_and_full_key(self, tmp_path):
        translations = {
            "zh_cn": {"a": {"b": "嵌套值"}, "flat.key": "平键值"},
            "en_us": {"a": {"b": "nested value"}},
        }
        svc = _service(tmp_path, translations)
        assert svc.resolve_i18n("$a.b", "zh-CN") == "嵌套值"
        assert svc.resolve_i18n("$flat.key", "zh-CN") == "平键值"

    def test_locale_fallback_chain(self, tmp_path):
        translations = {"zh_cn": {"k": "中文"}, "en_us": {"k": "english"}}
        svc = _service(tmp_path, translations)
        # en-US 命中 en_us
        assert svc.resolve_i18n("$k", "en-US") == "english"
        # zh-CN 命中 zh_cn
        assert svc.resolve_i18n("$k", "zh-CN") == "中文"

    def test_missing_key_returns_none(self, tmp_path):
        svc = _service(tmp_path, {"zh_cn": {"other": "x"}})
        assert svc.resolve_i18n("$missing", "zh-CN") is None

    def test_unresolved_reference_not_treated_as_translated(self, tmp_path):
        """未命中的 $key 不能被当正常已翻译值返回。"""
        svc = _service(tmp_path, {})
        assert svc.resolve_text("$missing.key", "zh-CN") == "$missing.key"


# ---------------------------------------------------------------------------
# resolve_text
# ---------------------------------------------------------------------------


class TestResolveText:
    def test_empty_falls_back(self, tmp_path):
        svc = _service(tmp_path)
        assert svc.resolve_text(None, "zh-CN", "fb") == "fb"
        assert svc.resolve_text("   ", "zh-CN", "fb") == "fb"

    def test_plain_text_passthrough(self, tmp_path):
        svc = _service(tmp_path)
        assert svc.resolve_text("hello", "zh-CN", "fb") == "hello"

    def test_reference_resolved(self, tmp_path):
        svc = _service(tmp_path, {"zh_cn": {"k": "值"}})
        assert svc.resolve_text("$k", "zh-CN", "fb") == "值"


# ---------------------------------------------------------------------------
# resolve_document
# ---------------------------------------------------------------------------


class TestResolveDocument:
    def test_direct_text(self, tmp_path):
        svc = _service(tmp_path)
        assert svc.resolve_document("直接文档内容", "zh-CN") == "直接文档内容"

    def test_root_contained_file(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "readme.md").write_text("# 文档", encoding="utf-8")
        svc = _service(tmp_path)
        assert svc.resolve_document("docs/readme.md", "zh-CN") == "# 文档"

    def test_file_escape_rejected(self, tmp_path):
        svc = _service(tmp_path)
        with pytest.raises(InterfaceContentError):
            svc.resolve_document("../etc/passwd", "zh-CN")

    def test_missing_file_raises_with_path(self, tmp_path):
        svc = _service(tmp_path)
        with pytest.raises(InterfaceContentError, match="docs/missing.md"):
            svc.resolve_document("docs/missing.md", "zh-CN")

    def test_i18n_reference_to_file(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "zh.md").write_text("中文文档", encoding="utf-8")
        (tmp_path / "docs" / "en.md").write_text("english doc", encoding="utf-8")
        svc = _service(
            tmp_path,
            {"zh_cn": {"doc": "docs/zh.md"}, "en_us": {"doc": "docs/en.md"}},
        )
        assert svc.resolve_document("$doc", "zh-CN") == "中文文档"
        assert svc.resolve_document("$doc", "en-US") == "english doc"

    def test_http_url_fetch(self, tmp_path, monkeypatch):
        def fake_get(self, url):
            return httpx.Response(200, text="远程文档")

        monkeypatch.setattr(httpx.Client, "get", fake_get)
        svc = _service(tmp_path)
        assert svc.resolve_document("https://example.com/doc.md", "zh-CN") == "远程文档"

    def test_http_failure_raises(self, tmp_path, monkeypatch):
        def fake_get(self, url):
            return httpx.Response(404, text="not found")

        monkeypatch.setattr(httpx.Client, "get", fake_get)
        svc = _service(tmp_path)
        with pytest.raises(InterfaceContentError, match="404"):
            svc.resolve_document("https://example.com/doc.md", "zh-CN")

    def test_empty_document_raises(self, tmp_path):
        svc = _service(tmp_path)
        with pytest.raises(InterfaceContentError):
            svc.resolve_document("  ", "zh-CN")


# ---------------------------------------------------------------------------
# 来源白名单
# ---------------------------------------------------------------------------


class TestCollectDocumentSources:
    def test_task_doc_sources_collected(self, tmp_path):
        task = Task(name="A", entry="A", doc="docs/a.md", description="直接说明")
        svc = _service(tmp_path, tasks=[task])
        sources = svc.collect_document_sources()
        assert "docs/a.md" in sources
        assert "直接说明" in sources

    def test_translated_sources_collected(self, tmp_path):
        task = Task(name="A", entry="A", doc="$doc")
        svc = _service(
            tmp_path,
            {"zh_cn": {"doc": "docs/zh.md"}, "en_us": {"doc": "docs/en.md"}},
            tasks=[task],
        )
        sources = svc.collect_document_sources()
        assert "$doc" in sources
        assert "docs/zh.md" in sources
        assert "docs/en.md" in sources

    def test_interface_welcome_description(self, tmp_path):
        svc = _service(tmp_path)
        sources = svc.collect_document_sources()
        # welcome/description 默认为 None，不产生来源
        assert sources == {}
