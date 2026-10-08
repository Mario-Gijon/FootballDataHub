from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from football_data_hub.core import browser_runtime as mod


def config(tmp_path: Path, **kwargs):
    return mod.BrowserRuntimeConfig(profile_dir=tmp_path / "browser", **kwargs)


@pytest.mark.parametrize("choice", ["brave", "chrome", "chromium", "auto"])
def test_supported_browser_choices(tmp_path, choice):
    assert config(tmp_path, browser=choice).browser == choice


def test_invalid_browser(tmp_path):
    with pytest.raises(ValueError):
        config(tmp_path, browser="firefox")


def test_invalid_timeout(tmp_path):
    with pytest.raises(ValueError):
        config(tmp_path, startup_timeout_seconds=0)


def test_invalid_start_url(tmp_path):
    with pytest.raises(ValueError):
        config(tmp_path, start_url="file:///etc/passwd")


def test_browser_resolution(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/brave" if name == "brave" else None)
    assert mod.find_browser("auto") == "/usr/bin/brave"
    with pytest.raises(mod.BrowserRuntimeError):
        mod.find_browser("chrome")


def test_xvfb_command(monkeypatch, tmp_path):
    monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/xvfb-run")
    command = mod.build_command(config(tmp_path), "/usr/bin/brave", 9012)
    assert command[:4] == ["/usr/bin/xvfb-run", "-a", "-s", "-screen 0 1920x1080x24"]
    assert "--ozone-platform=x11" in command
    assert "--remote-debugging-address=127.0.0.1" in command
    assert "--remote-debugging-port=9012" in command
    assert "--user-data-dir=" + str(tmp_path / "browser") in command


def test_xvfb_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(mod.shutil, "which", lambda _: None)
    with pytest.raises(mod.BrowserRuntimeError, match="xvfb-run"):
        mod.build_command(config(tmp_path), "/usr/bin/brave", 9912)


def test_non_xvfb_command_needs_no_xvfb(monkeypatch, tmp_path):
    monkeypatch.setattr(mod.shutil, "which", lambda _: None)
    command = mod.build_command(config(tmp_path, use_xvfb=False), "/usr/bin/brave", 9012)
    assert command[0] == "/usr/bin/brave"
    assert "--ozone-platform=x11" in command


def test_profile_lock_exclusive(tmp_path):
    profile = tmp_path / "browser"
    profile.mkdir()
    fd = mod._acquire_profile_lock(profile)
    try:
        with pytest.raises(mod.BrowserProfileInUse):
            mod._acquire_profile_lock(profile)
    finally:
        mod._release_profile_lock(fd)
    next_fd = mod._acquire_profile_lock(profile)
    mod._release_profile_lock(next_fd)


def test_wait_for_cdp_exited_process():
    fake = Mock()
    fake.poll.return_value = 1
    fake.returncode = 1
    with pytest.raises(mod.BrowserRuntimeError, match="terminó"):
        mod.wait_for_cdp(9123, fake, 0.01)


def test_start_process_scrubs_wayland_and_releases_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "find_browser", lambda _: "/usr/bin/brave")
    monkeypatch.setattr(mod, "reserve_loopback_port", lambda: 9124)
    monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/xvfb-run")
    monkeypatch.setattr(mod, "wait_for_cdp", lambda *args: {"webSocketDebuggerUrl": "ws://127.0.0.1/x"})
    saved = {}

    class FakePopen:
        def __init__(self, command, **kwargs):
            saved["command"] = command
            saved["env"] = kwargs["env"]
            saved["new_session"] = kwargs["start_new_session"]
            self.pid = 1234
            self.returncode = 0

        def poll(self):
            return 0

    monkeypatch.setattr(mod.subprocess, "Popen", FakePopen)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("WAYLAND_SOCKET", "10")
    runtime = mod.start_browser(config(tmp_path))
    assert runtime.cdp_url == "http://127.0.0.1:9124"
    assert saved["env"]["XDG_SESSION_TYPE"] == "x11"
    assert "WAYLAND_DISPLAY" not in saved["env"]
    assert "WAYLAND_SOCKET" not in saved["env"]
    assert saved["new_session"] is True
    runtime.close()
    runtime.close()
    fd = mod._acquire_profile_lock((tmp_path / "browser").resolve())
    mod._release_profile_lock(fd)


def test_start_failure_releases_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "find_browser", lambda _: "/usr/bin/brave")
    monkeypatch.setattr(mod, "reserve_loopback_port", lambda: 9124)
    monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/xvfb-run")
    fake = Mock()
    fake.poll.return_value = 1
    fake.returncode = 1
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *args, **kw: fake)
    def fail(*args):
        raise mod.BrowserRuntimeError("fallo")
    monkeypatch.setattr(mod, "wait_for_cdp", fail)
    with pytest.raises(mod.BrowserRuntimeError):
        mod.start_browser(config(tmp_path))
    fd = mod._acquire_profile_lock((tmp_path / "browser").resolve())
    mod._release_profile_lock(fd)


def test_loopback_port_valid():
    assert 0 < mod.reserve_loopback_port() < 65536
