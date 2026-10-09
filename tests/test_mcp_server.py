"""Real MCP round trips against the bundled server (no email is sent). Skipped if `mcp` is not installed."""
import json

import pytest

pytest.importorskip("mcp")

from pipeline.notify.mcp_client import McpEmailClient, SendError, load_server_params  # noqa: E402


def no_creds_client(monkeypatch):
    for k in ("SMTP_USER", "SMTP_PASS"):
        monkeypatch.delenv(k, raising=False)
    return McpEmailClient(config_path=None)


def test_server_lists_send_email(monkeypatch):
    assert "send_email" in no_creds_client(monkeypatch).list_tools()


def test_tool_error_surfaces_as_send_error(monkeypatch):
    # without SMTP credentials the server refuses before any network call
    with pytest.raises(SendError, match="SMTP_USER and SMTP_PASS"):
        no_creds_client(monkeypatch).send_email("me@test.com", "s", "b")


def test_config_placeholders_rejected(tmp_path):
    cfg = tmp_path / "mcp_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"gmail": {"command": "python", "args": ["mcp_server/gmail_smtp_server.py"],
                                                        "env": {"SMTP_USER": "<your_gmail_address>"}}}}))
    with pytest.raises(SendError, match="placeholder"):
        load_server_params(cfg)
