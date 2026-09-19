"""End to end: talk to a real server process over stdio, exactly as an MCP client would."""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "record_memory", "search_memory", "search_memory_semantic", "read_memory",
    "get_handoff", "recent", "list_projects", "audit_usage",
}


def _items(result) -> list:
    return [json.loads(block.text) for block in result.content]


async def _session_flow():
    params = StdioServerParameters(command=sys.executable, args=["-m", "ai_memory.server"], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}

            saved = _items(await session.call_tool("record_memory", {
                "project": "e2e", "type": "handoff", "title": "端到端測試",
                "content": "下一步：發布 1.0", "llm": "pytest",
            }))[0]
            hits = _items(await session.call_tool("search_memory", {"query": "端到端", "llm": "pytest"}))
            handoff = _items(await session.call_tool("get_handoff", {"project": "e2e"}))
            evil = _items(await session.call_tool("record_memory", {
                "project": "../../evil", "type": "decision", "title": "t", "content": "c",
            }))[0]
            return init, tools, saved, hits, handoff, evil


def test_full_protocol_roundtrip():
    init, tools, saved, hits, handoff, evil = asyncio.run(asyncio.wait_for(_session_flow(), timeout=90))

    assert init.serverInfo.name == "ai-memory"
    assert "get_handoff" in (init.instructions or "")
    assert tools == EXPECTED_TOOLS

    assert saved["ok"] is True and saved["indexed"] is True
    assert [h["path"] for h in hits] == [saved["path"]]
    assert handoff[0]["content"] == "下一步：發布 1.0"
    assert "error" in evil
