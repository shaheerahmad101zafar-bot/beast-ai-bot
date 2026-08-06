"""
Global socket tuning for low-latency outbound connections.
"""

from __future__ import annotations

import socket
from typing import Any

import config

_PATCHED = False
_ORIG_CREATE_CONNECTION = socket.create_connection


def tune_socket(sock: socket.socket) -> socket.socket:
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, int(config.SOCKET_TCP_NODELAY))
    except Exception:
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    if getattr(config, "SOCKET_SO_REUSEPORT", False) and hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass
    return sock


def apply_global_socket_tuning() -> None:
    global _PATCHED
    if _PATCHED:
        return

    def _wrapped_create_connection(*args: Any, **kwargs: Any):
        sock = _ORIG_CREATE_CONNECTION(*args, **kwargs)
        return tune_socket(sock)

    socket.create_connection = _wrapped_create_connection
    _PATCHED = True
