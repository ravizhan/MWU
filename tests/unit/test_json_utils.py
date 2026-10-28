"""Tests for json_utils.py — a thin wrapper around json5 and stdlib json."""

import io

import json_utils as json


def test_alias_is_value_error():
    assert json.JSONDecodeError is ValueError


def test_loads_accepts_json5_syntax():
    assert json.loads("{a: 1, /* comment */ b: 'x',}") == {"a": 1, "b": "x"}


def test_load_reads_from_file_object():
    assert json.load(io.StringIO('{"a": 1}')) == {"a": 1}


def test_dumps_forwards_indent():
    assert json.dumps({"a": 1}, indent=2) == '{\n  "a": 1\n}'
