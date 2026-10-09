"""Route (a): call the MCP server's send_email tool from Python over stdio (Plan decision D6).

Server parameters come from mcp_config.json (gitignored; same shape as
mcp_config.json.example) when present, otherwise the bundled server is started
with the current environment (SMTP_USER / SMTP_PASS must then be exported).
Each call starts a short-lived stdio session; live runs send at most --max-send
emails, so the simplicity is worth the ~1 s startup per email.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SERVER = ROOT / "mcp_server" / "gmail_smtp_server.py"


class SendError(RuntimeError):
    pass


def load_server_params(config_path: Path | None, server_name: str = "gmail") -> tuple[str, list[str], dict]:
    env = dict(os.environ)
    if config_path and Path(config_path).exists():
        spec = json.loads(Path(config_path).read_text())["mcpServers"][server_name]
        command = sys.executable if spec.get("command") in ("python", "python3") else spec["command"]
        args = [str(ROOT / a) if a.endswith(".py") and not os.path.isabs(a) else a for a in spec.get("args", [])]
        placeholders = [k for k, v in spec.get("env", {}).items() if "<" in str(v)]
        if placeholders:
            raise SendError(f"{config_path}: replace placeholder values for {', '.join(placeholders)}")
        env.update({k: str(v) for k, v in spec.get("env", {}).items()})
        return command, args, env
    return sys.executable, [str(DEFAULT_SERVER)], env


class McpEmailClient:
    def __init__(self, config_path: Path | None = None, server_name: str = "gmail"):
        self.command, self.args, self.env = load_server_params(config_path, server_name)

    async def _session_call(self, method: str, *args):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=self.command, args=self.args, env=self.env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await getattr(session, method)(*args)

    def list_tools(self) -> list[str]:
        result = asyncio.run(self._session_call("list_tools"))
        return [t.name for t in result.tools]

    def send_email(self, to: str, subject: str, body: str, references: str = "", original_to: str = "") -> str:
        arguments = {"to": to, "subject": subject, "body": body,
                     "references": references, "original_to": original_to}
        result = asyncio.run(self._session_call("call_tool", "send_email", arguments))
        text = " ".join(getattr(c, "text", "") for c in result.content).strip()
        if result.isError:
            raise SendError(text or "send_email failed")
        return text
