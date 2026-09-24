"""Config resolution tests: env overrides and scanner detection."""

from __future__ import annotations

import gmail_mcp.config as config


def test_scan_command_env_override_is_split(monkeypatch):
    monkeypatch.setenv("GMAIL_MCP_SCAN_CMD", "/usr/bin/scanner --flag 'a b'")
    assert config.scan_command() == ["/usr/bin/scanner", "--flag", "a b"]


def test_scan_command_empty_env_disables_scanning(monkeypatch):
    monkeypatch.setenv("GMAIL_MCP_SCAN_CMD", "")
    assert config.scan_command() is None


def test_scan_command_detects_clamscan(monkeypatch):
    monkeypatch.delenv("GMAIL_MCP_SCAN_CMD", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda name: f"/bin/{name}")
    cmd = config.scan_command()
    assert cmd is not None
    assert cmd[0] == "/bin/clamscan"


def test_scan_command_none_when_no_scanner(monkeypatch):
    monkeypatch.delenv("GMAIL_MCP_SCAN_CMD", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    monkeypatch.setattr(config, "_CLAMSCAN_FALLBACKS", ())
    assert config.scan_command() is None


def test_quarantine_dir_is_under_attachment_root(monkeypatch, tmp_path):
    monkeypatch.setenv("GMAIL_MCP_ATTACHMENT_DIR", str(tmp_path))
    assert config.quarantine_dir() == tmp_path / "quarantine"
