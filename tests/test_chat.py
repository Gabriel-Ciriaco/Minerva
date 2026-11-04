"""`minerva chat` contra um Ollama falso (HTTP local com respostas roteirizadas em NDJSON)."""
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from minerva import chat, server
from minerva import search as engine


class FakeOllama:
    def __init__(self, replies=(), models=("qwen3:8b",), caps=("completion", "tools")):
        self.replies, self.models, self.caps, self.requests = list(replies), list(models), caps, []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body, ctype="application/json"):
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/version":
                    self._send(json.dumps({"version": "0.0-teste"}))
                elif self.path == "/api/tags":
                    self._send(json.dumps({"models": [{"name": m} for m in fake.models]}))
                else:
                    self.send_error(404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/api/show":
                    caps = {} if fake.caps is None else {"capabilities": list(fake.caps)}
                    self._send(json.dumps(caps))
                elif self.path == "/api/chat":
                    fake.requests.append(body)
                    chunks = fake.replies.pop(0)
                    self._send("".join(json.dumps(c) + "\n" for c in chunks), "application/x-ndjson")
                else:
                    self.send_error(404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def tool_call(name, **args):
    return [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": name, "arguments": args}}]}, "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True}]


def text(*parts):
    return [{"message": {"role": "assistant", "content": p}, "done": False} for p in parts] + \
           [{"message": {"role": "assistant", "content": ""}, "done": True}]


@pytest.fixture
def fake():
    servers = []

    def make(*a, **k):
        servers.append(FakeOllama(*a, **k))
        return servers[-1]
    yield make
    for s in servers:
        s.close()


def run_chat(workspace, fake_server, answers, **kw):
    it = iter(answers)
    out = io.StringIO()
    chat.run(workspace, model=kw.pop("model", "qwen3:8b"), host=fake_server.url,
             ask=lambda prompt: next(it), out=out, **kw)
    return out.getvalue()


def test_tool_call_runs_minerva_search_and_answers(workspace, fake):
    f = fake([tool_call("search", query="singleton"), text("O Singleton garante ", "uma instância.")])
    out = run_chat(workspace, f, ["o que é singleton?", "/sair"])
    first, second = f.requests
    assert {t["function"]["name"] for t in first["tools"]} == {"search", "outline", "read", "lembrar"}
    system = first["messages"][0]
    assert system["role"] == "system" and "Tutor" in system["content"] and "MEMORIA.md atual" in system["content"]
    assert first["options"]["num_ctx"] == chat.DEFAULT_CONTEXT and "think" not in first
    tool_msg = second["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_name"] == "search"
    assert json.loads(tool_msg["content"])["r"]  # resultado real do índice
    assert second["messages"][-2]["tool_calls"][0]["function"]["name"] == "search"
    assert "· search" in out and "uma instância." in out


def test_previous_questions_keep_only_question_and_answer(workspace, fake):
    f = fake([tool_call("search", query="singleton"), text("resposta 1"), text("resposta 2")])
    run_chat(workspace, f, ["pergunta 1", "pergunta 2", "/sair"], think=False)
    msgs = f.requests[2]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2]["content"] == "resposta 1" and f.requests[2]["think"] is False


@pytest.mark.parametrize("reply, saved", [("s", True), ("n", False)])
def test_remember_asks_before_writing(workspace, fake, reply, saved):
    f = fake([tool_call("lembrar", secao="Convenções", linha="usar ∅ para transição indefinida"), text("ok")])
    run_chat(workspace, f, ["guarda isso", reply, "/sair"])
    memory = (workspace / "MEMORIA.md").read_text(encoding="utf-8")
    assert ("- usar ∅ para transição indefinida" in memory) is saved
    assert json.loads(f.requests[1]["messages"][-1]["content"])["gravado"] is saved
    if saved:  # na seção certa, antes da próxima
        conv, dec = memory.index("## Convenções"), memory.index("## Decisões da disciplina")
        assert conv < memory.index("- usar ∅") < dec


def test_tool_rounds_are_capped(workspace, fake):
    f = fake([tool_call("search", query="x")] * chat.MAX_TOOL_ROUNDS + [text("final")])
    out = run_chat(workspace, f, ["insiste", "/sair"])
    last = f.requests[-1]
    assert "tools" not in last and "Pare de chamar ferramentas" in last["messages"][-1]["content"]
    assert "final" in out


def test_model_checks(workspace, fake):
    with pytest.raises(chat.ChatError, match="não suporta ferramentas"):
        run_chat(workspace, fake(caps=("completion",)), [])
    with pytest.raises(chat.ChatError, match="não está no Ollama"):
        run_chat(workspace, fake(), [], model="llama3.1")
    with pytest.raises(chat.ChatError, match="escolha o modelo"):
        run_chat(workspace, fake(models=("a:1", "b:2")), [], model=None)
    out = run_chat(workspace, fake(models=("qwen3:latest",), caps=None), ["/sair"], model="qwen3")
    assert "qwen3 em" in out  # ":latest" implícito; versão sem `capabilities` não bloqueia


def test_ollama_down_is_clear_error(workspace):
    with pytest.raises(chat.ChatError, match="não respondeu"):
        chat.run(workspace, model="x", host="http://127.0.0.1:9", ask=lambda p: "/sair", out=io.StringIO())


def test_run_tool_tolerates_small_model_mistakes(workspace):
    mcp = server.build(workspace)
    ref = json.loads(chat.run_tool(mcp, workspace, "search", {"query": "singleton"}, None))["r"][0]["ref"]
    assert json.loads(chat.run_tool(mcp, workspace, "read", {"refs": ref}, None))["r"]  # ref solto vira lista
    assert json.loads(chat.run_tool(mcp, workspace, "abrir_pdf", {}, None))["erro"] == "FERRAMENTA_DESCONHECIDA"
    assert json.loads(chat.run_tool(mcp, workspace, "read", {"refs": 5}, None))["erro"] == "ARGUMENTO_INVALIDO"


@pytest.mark.parametrize("raw, url", [
    ("", "http://localhost:11434"),
    ("0.0.0.0:11434", "http://127.0.0.1:11434"),
    ("ollama", "http://ollama:11434"),
    ("http://localhost:11434/", "http://localhost:11434"),
    ("https://ollama.exemplo.com", "https://ollama.exemplo.com:443"),
])
def test_normalize_host(raw, url):
    assert chat.normalize_host(raw) == url


def test_new_question_resets_budget():
    budget = engine.QuestionBudget()
    for _ in range(20):
        budget.tick()
    budget.new_question()
    assert budget.tick() is None and budget.list_sources()
