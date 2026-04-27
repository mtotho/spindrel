"""Tests for chrome resolution in integrations.sdk.

Specifically guards the wrapper-bypass behaviour: when chromium is
installed via dpkg-extract into ``/opt/spindrel-pkg``, the
``…/usr/bin/chromium`` wrapper is broken (it sources ``/etc/chromium.d/*``
which doesn't exist because dpkg-x doesn't run postinst). We must prefer
the underlying ELF binary at ``…/usr/lib/chromium/chromium`` when it
exists.
"""
from __future__ import annotations

import os

import pytest

from integrations.sdk import _prefer_underlying_chromium, find_chrome_path


def _make_executable(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(path, 0o755)


def test_prefer_underlying_returns_underlying_when_present(tmp_path):
    prefix = tmp_path / "spindrel-pkg"
    wrapper = prefix / "usr" / "bin" / "chromium"
    underlying = prefix / "usr" / "lib" / "chromium" / "chromium"
    _make_executable(str(wrapper))
    _make_executable(str(underlying))

    assert _prefer_underlying_chromium(str(wrapper)) == str(underlying)


def test_prefer_underlying_returns_input_when_no_underlying(tmp_path):
    prefix = tmp_path / "spindrel-pkg"
    wrapper = prefix / "usr" / "bin" / "chromium"
    _make_executable(str(wrapper))

    assert _prefer_underlying_chromium(str(wrapper)) == str(wrapper)


def test_prefer_underlying_passes_through_non_wrapper_paths(tmp_path):
    other = tmp_path / "opt" / "google-chrome"
    _make_executable(str(other))
    assert _prefer_underlying_chromium(str(other)) == str(other)


def test_prefer_underlying_passes_through_non_chromium_basename(tmp_path):
    prefix = tmp_path / "spindrel-pkg"
    other = prefix / "usr" / "bin" / "firefox"
    _make_executable(str(other))
    # An underlying chromium would exist but the input is "firefox" — no swap.
    underlying = prefix / "usr" / "lib" / "chromium" / "chromium"
    _make_executable(str(underlying))
    assert _prefer_underlying_chromium(str(other)) == str(other)


def test_find_chrome_path_via_env_swaps_to_underlying(tmp_path, monkeypatch):
    prefix = tmp_path / "spindrel-pkg"
    wrapper = prefix / "usr" / "bin" / "chromium"
    underlying = prefix / "usr" / "lib" / "chromium" / "chromium"
    _make_executable(str(wrapper))
    _make_executable(str(underlying))

    monkeypatch.setenv("CHROME_PATH", str(wrapper))
    monkeypatch.setenv("PATH", str(wrapper.parent))

    assert find_chrome_path() == str(underlying)


@pytest.mark.parametrize("env_var", ["CHROME_PATH", "PUPPETEER_EXECUTABLE_PATH"])
def test_find_chrome_path_keeps_non_wrapper_env(tmp_path, monkeypatch, env_var):
    chrome = tmp_path / "google-chrome"
    _make_executable(str(chrome))

    monkeypatch.setenv(env_var, str(chrome))
    if env_var != "CHROME_PATH":
        monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.setenv("PATH", str(chrome.parent))

    assert find_chrome_path() == str(chrome)
