"""Network isolation: sockets are blocked, and httpx2 stays confined to client.py."""

from __future__ import annotations

from pathlib import Path

import httpx2
import pytest
from pytest_socket import SocketBlockedError


def test_unmocked_client_is_blocked_by_pytest_socket() -> None:
    """An httpx2.Client with no mock transport must never reach the network."""
    client = httpx2.Client()
    try:
        with pytest.raises(SocketBlockedError):
            client.get("http://127.0.0.1:9/")
    finally:
        client.close()


def test_httpx2_confined_to_transport_client_module() -> None:
    """Only src/booth_review/transport/client.py may import httpx2 (D-14)."""
    src_root = Path(__file__).resolve().parents[1] / "src" / "booth_review"
    offenders = []
    for path in src_root.rglob("*.py"):
        if path == src_root / "transport" / "client.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "httpx2" in text:
            offenders.append(path)
    assert offenders == []
