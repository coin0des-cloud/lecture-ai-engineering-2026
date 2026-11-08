"""ADKのMCPクライアントが講座のMCPサーバーを認識することを確認する。"""

import asyncio
import json

from google.adk.tools.mcp_tool import McpToolset

from app.agent import MCP_CONFIG, build_mcp_agent

GLOSSARY_TOOL = "glossary_search_glossary"


def _glossary_only_config(tmp_path):
    """外部MCPサーバーを起動せず、用語集サーバーだけを使う。"""
    config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    assert "glossary" in config["mcpServers"], "app/mcp_servers.json に glossary サーバーが必要"
    path = tmp_path / "mcp_servers.json"
    path.write_text(
        json.dumps({"mcpServers": {"glossary": config["mcpServers"]["glossary"]}}),
        encoding="utf-8",
    )
    return path


def test_glossary_server_exposes_search_tool(tmp_path):
    target = build_mcp_agent(_glossary_only_config(tmp_path))
    toolsets = [tool for tool in target.tools if isinstance(tool, McpToolset)]
    assert len(toolsets) == 1

    async def discover_tools():
        try:
            return await toolsets[0].get_tools_with_prefix()
        finally:
            await toolsets[0].close()

    offered = {tool.name for tool in asyncio.run(discover_tools())}
    assert GLOSSARY_TOOL in offered
