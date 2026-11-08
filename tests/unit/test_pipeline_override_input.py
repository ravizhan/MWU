from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.maa_worker.pipeline_override import PipelineOverrideService
from backend.models.interface import InputCase, Option

PROJECT_DIR = Path(__file__).resolve().parent / "project"


def _override(input_type: str, value: str):
    option = Option(
        type="input",
        inputs=[InputCase(name="target", input_type=input_type)],
        pipeline_override={"Node": {"param": "{target}", "text": "at {target}"}},
    )
    worker = SimpleNamespace(
        interface=SimpleNamespace(option={"Opt": option}),
        context=SimpleNamespace(interface_base_dir=PROJECT_DIR),
        device_state=SimpleNamespace(current_resource_name=None),
    )
    return PipelineOverrideService(worker)._build_option_override(
        "Opt", {"Opt": {"target": value}}, set()
    )


@pytest.mark.parametrize("input_type", ["file", "directory"])
def test_relative_path_input_is_resolved_against_project_dir(input_type):
    expected = str(PROJECT_DIR / "resource/config.json")

    assert _override(input_type, "resource/config.json") == {
        "Node": {"param": expected, "text": f"at {expected}"}
    }


def test_absolute_path_and_text_input_are_kept_verbatim():
    absolute = str(PROJECT_DIR.parent / "elsewhere" / "a.json")

    assert _override("file", absolute)["Node"]["param"] == absolute
    assert _override("text", "resource/a.json")["Node"]["param"] == "resource/a.json"
    assert _override("directory", "")["Node"]["param"] == ""


def test_project_root_selection_resolves_to_project_dir():
    assert Path(_override("directory", ".")["Node"]["param"]) == PROJECT_DIR


@pytest.mark.parametrize("pipeline_type", ["int", "bool"])
def test_path_input_rejects_non_string_pipeline_type(pipeline_type):
    with pytest.raises(ValidationError):
        InputCase(name="target", input_type="file", pipeline_type=pipeline_type)
