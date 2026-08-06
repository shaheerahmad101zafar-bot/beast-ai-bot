"""
Fast JSON compatibility helpers preferring orjson/ujson.
"""

from __future__ import annotations

import json as _json
from typing import Any

try:
    import orjson as _backend

    def loads(data: bytes | bytearray | memoryview | str) -> Any:
        return _backend.loads(data)

    def dumps(obj: Any) -> bytes:
        return _backend.dumps(obj)

except Exception:  # noqa: BLE001
    try:
        import ujson as _backend  # type: ignore[assignment]

        def loads(data: bytes | bytearray | memoryview | str) -> Any:
            if isinstance(data, (bytes, bytearray, memoryview)):
                data = bytes(data).decode("utf-8")
            return _backend.loads(data)

        def dumps(obj: Any) -> bytes:
            return _backend.dumps(obj).encode("utf-8")

    except Exception:  # noqa: BLE001
        def loads(data: bytes | bytearray | memoryview | str) -> Any:
            if isinstance(data, (bytes, bytearray, memoryview)):
                data = bytes(data).decode("utf-8")
            return _json.loads(data)

        def dumps(obj: Any) -> bytes:
            return _json.dumps(obj).encode("utf-8")
