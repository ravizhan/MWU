import json as _stdlib_json
from typing import Any

import json5

JSONDecodeError = ValueError


def load(fp: Any, **kwargs: Any) -> Any:
    return json5.load(fp, **kwargs)


def loads(s: str, **kwargs: Any) -> Any:
    return json5.loads(s, **kwargs)


def dump(
    obj: Any,
    fp: Any,
    *,
    indent: int | str | None = None,
    ensure_ascii: bool = True,
    **kwargs: Any,
) -> None:
    # json5.dump ignores formatting kwargs; stdlib JSON output remains valid JSON5.
    _stdlib_json.dump(
        obj,
        fp,
        indent=indent,
        ensure_ascii=ensure_ascii,
        **kwargs,
    )


def dumps(
    obj: Any,
    *,
    indent: int | str | None = None,
    ensure_ascii: bool = True,
    **kwargs: Any,
) -> str:
    # json5.dumps ignores formatting kwargs; stdlib JSON output remains valid JSON5.
    return _stdlib_json.dumps(
        obj,
        indent=indent,
        ensure_ascii=ensure_ascii,
        **kwargs,
    )
