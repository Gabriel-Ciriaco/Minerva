"""Sobe `python -m minerva serve` via stdio, como o Antigravity faz, e chama as ferramentas."""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_server_end_to_end(workspace, tmp_path):
    async def run():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "minerva", "serve", "--workspace", str(workspace), "--log"],
            cwd=str(tmp_path))  # cwd diferente do workspace: não pode depender dele
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            assert names == {"search", "outline", "read"}

            async def call(tool, args):
                return json.loads((await s.call_tool(tool, args)).content[0].text)

            assert "itens" in await call("outline", {})
            pages = await call("outline", {"source": "doc3_slides_padroes.pptx"})
            got = await call("read", {"refs": [pages["itens"][0]["ref"]], "vizinhos": 1})
            assert [x["cite"] for x in got["r"]] == ["doc3_slides_padroes.pptx slide 1",
                                                     "doc3_slides_padroes.pptx slide 2"]
            assert (await call("search", {"query": "singleton"}))["r"]
            assert (await call("read", {"refs": []}))["erro"] == "ARGUMENTO_INVALIDO"
            (workspace / "novo.md").write_text("## A\nb\n", encoding="utf-8")
            sources = await call("outline", {})
            assert "aviso" in sources and "nota" in sources  # 2ª lista na mesma pergunta

    asyncio.run(run())
    logs = list((workspace / ".minerva" / "logs").glob("*.jsonl"))
    assert len(logs) == 1
    lines = [json.loads(l) for l in logs[0].read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 6 and all("text" not in json.dumps(l) for l in lines)
