"""Port from ``instance.json``, token from the environment, ``Terminal.discover``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import TOKEN, FakeTerminal

from spectre_terminal import (
    IncompatibleTerminal,
    LocalApiDisabled,
    Terminal,
    TokenMissing,
    discovery,
)


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private data directory for the test, as ``$XDG_DATA_HOME`` on Linux."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv(discovery.TOKEN_ENV, raising=False)
    return tmp_path


def write_instance(data_home: Path, body: str) -> Path:
    directory = data_home / "spectre-terminal"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "instance.json"
    path.write_text(body, encoding="utf-8")
    return path


# --- instance_path --------------------------------------------------------


def test_instance_path_linux_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert discovery.instance_path() == tmp_path / "spectre-terminal" / "instance.json"


def test_instance_path_linux_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = tmp_path / ".local" / "share" / "spectre-terminal" / "instance.json"
    assert discovery.instance_path() == expected


def test_instance_path_macos(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = tmp_path / "Library" / "Application Support" / "spectre-terminal" / "instance.json"
    assert discovery.instance_path() == expected


def test_instance_path_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert discovery.instance_path() == tmp_path / "Local" / "spectre-terminal" / "instance.json"
    monkeypatch.delenv("LOCALAPPDATA")
    assert discovery.instance_path() == tmp_path / "Roaming" / "spectre-terminal" / "instance.json"


# --- read_port --------------------------------------------------------------


def test_read_port_file_missing(data_home: Path) -> None:
    assert discovery.read_port() is None


def test_read_port_present(data_home: Path) -> None:
    write_instance(data_home, json.dumps({"pid": 1, "http_port": 2, "local_api_port": 48181}))
    assert discovery.read_port() == 48181


def test_read_port_null_means_disabled(data_home: Path) -> None:
    write_instance(data_home, json.dumps({"pid": 1, "http_port": 2, "local_api_port": None}))
    with pytest.raises(LocalApiDisabled, match="switched off"):
        discovery.read_port()


def test_read_port_absent_field_means_disabled(data_home: Path) -> None:
    write_instance(data_home, json.dumps({"pid": 1, "http_port": 2}))
    with pytest.raises(LocalApiDisabled):
        discovery.read_port()


def test_read_port_unreadable_falls_back(data_home: Path) -> None:
    write_instance(data_home, "{not json")
    assert discovery.read_port() is None
    write_instance(data_home, json.dumps({"local_api_port": "48180"}))
    assert discovery.read_port() is None


def test_read_port_explicit_path(tmp_path: Path) -> None:
    path = tmp_path / "instance.json"
    path.write_text(json.dumps({"local_api_port": 5}), encoding="utf-8")
    assert discovery.read_port(path) == 5


# --- token_from_env ---------------------------------------------------------


def test_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(discovery.TOKEN_ENV, f"  {TOKEN}  ")
    assert discovery.token_from_env() == TOKEN
    monkeypatch.setenv(discovery.TOKEN_ENV, "   ")
    assert discovery.token_from_env() is None
    monkeypatch.delenv(discovery.TOKEN_ENV)
    assert discovery.token_from_env() is None


# --- Terminal.discover ------------------------------------------------------


def test_discover_reads_port_and_token_and_calls_meta(
    data_home: Path, fake_terminal: FakeTerminal, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_instance(data_home, json.dumps({"local_api_port": fake_terminal.port}))
    monkeypatch.setenv(discovery.TOKEN_ENV, TOKEN)
    terminal = Terminal.discover()
    assert terminal.port == fake_terminal.port
    assert [r.path for r in fake_terminal.requests] == ["/v1/meta"]
    assert fake_terminal.last.headers["Authorization"] == f"Bearer {TOKEN}"


def test_discover_explicit_token_and_port(data_home: Path, fake_terminal: FakeTerminal) -> None:
    write_instance(data_home, json.dumps({"local_api_port": 1}))
    terminal = Terminal.discover(TOKEN, port=fake_terminal.port)
    assert terminal.port == fake_terminal.port
    assert fake_terminal.last.path == "/v1/meta"


def test_discover_falls_back_to_default_port(
    data_home: Path, monkeypatch: pytest.MonkeyPatch, fake_terminal: FakeTerminal
) -> None:
    monkeypatch.setattr(discovery, "DEFAULT_PORT", fake_terminal.port)
    terminal = Terminal.discover(TOKEN)
    assert terminal.port == fake_terminal.port


def test_discover_token_missing(data_home: Path) -> None:
    with pytest.raises(TokenMissing) as excinfo:
        Terminal.discover()
    message = str(excinfo.value)
    assert discovery.TOKEN_ENV in message
    assert "Copy token" in message and "Local API" in message


def test_discover_local_api_disabled(data_home: Path) -> None:
    write_instance(data_home, json.dumps({"local_api_port": None}))
    with pytest.raises(LocalApiDisabled):
        Terminal.discover(TOKEN)


def test_discover_incompatible_terminal(data_home: Path, fake_terminal: FakeTerminal) -> None:
    from conftest import load_fixture

    fake_terminal.override("/v1/meta", 200, {**load_fixture("meta"), "api_version": "2"})
    with pytest.raises(IncompatibleTerminal) as excinfo:
        Terminal.discover(TOKEN, port=fake_terminal.port)
    assert excinfo.value.api_version == "2" and excinfo.value.supported == "1"


def test_discover_unauthorized_propagates_with_hint(
    data_home: Path, fake_terminal: FakeTerminal
) -> None:
    from spectre_terminal import ApiError

    with pytest.raises(ApiError) as excinfo:
        Terminal.discover("spt_" + "00" * 32, port=fake_terminal.port)
    assert excinfo.value.code == "unauthorized"
    assert "stale" in excinfo.value.message and "switched off" in excinfo.value.message
