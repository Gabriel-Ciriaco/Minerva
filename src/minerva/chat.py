"""
`minerva chat`: conversa no terminal com um modelo do Ollama usando as ferramentas do Minerva
no mesmo processo, sem servidor MCP no meio.

As ferramentas são as do servidor (`server.build`): mesmas descrições, mesmos limites por
pergunta e o mesmo log. A conversa com o Ollama usa só a biblioteca padrão (HTTP + NDJSON).
A memória entra no prompt; para gravar, o modelo chama `lembrar` e o aluno confirma.
"""
import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from minerva import config as config_mod, connect as connect_mod, index, server
from minerva import search as engine

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_CONTEXT = 8192
MAX_TOOL_ROUNDS = 12   # rodadas de ferramentas por pergunta; depois o modelo responde sem elas
HISTORY_PAIRS = 4      # perguntas anteriores mantidas (só pergunta e resposta final)
EXIT = {"/sair", "/exit", "/quit"}
SECTIONS = ("Convenções", "Decisões da disciplina", "Andamento", "Dificuldades")
MCP_TOOLS = {"search", "outline", "read"}

CHAT_NOTE = """\
## Neste chat (minerva chat)
- Você roda no terminal do aluno, via Ollama; `search`, `outline` e `read` são as ferramentas do Minerva.
- Você não abre arquivos. O MEMORIA.md atual está abaixo; para gravar uma linha nele, chame `lembrar` \
(o aluno confirma no terminal antes de gravar).
- Responda em português."""

REMEMBER_TOOL = {"type": "function", "function": {
    "name": "lembrar",
    "description": ("Propõe ao aluno uma linha curta para o MEMORIA.md: uma convenção dele, uma decisão "
                    "da disciplina confirmada nos materiais, onde ele parou ou um erro recorrente. "
                    "O aluno confirma antes de gravar. No máximo uma vez por tarefa."),
    "parameters": {"type": "object", "properties": {
        "secao": {"type": "string", "enum": list(SECTIONS)},
        "linha": {"type": "string", "description": "uma linha curta, sem quebras"},
    }, "required": ["secao", "linha"]},
}}


class ChatError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Cliente HTTP do Ollama
# ---------------------------------------------------------------------------

def normalize_host(raw):
    """Aceita `host`, `host:porta` ou URL. 0.0.0.0 (endereço de escuta do servidor) vira 127.0.0.1."""
    raw = (raw or "").strip() or DEFAULT_HOST
    if "://" not in raw:
        raw = "http://" + raw
    parts = urllib.parse.urlsplit(raw)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 11434)
    except ValueError:
        raise ChatError(f"host do Ollama inválido: {raw}") from None
    host = parts.hostname or "localhost"
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme}://{host}:{port}{parts.path.rstrip('/')}"


def resolve_host(cfg_ollama, flag=None):
    """--host > minerva.yaml > OLLAMA_HOST > padrão."""
    return normalize_host(flag or cfg_ollama.get("host") or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST)


class Ollama:
    def __init__(self, host, timeout=600, probe_timeout=10):
        self.host, self.timeout, self.probe_timeout = normalize_host(host), timeout, probe_timeout

    def _open(self, path, payload=None, timeout=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(self.host + path, data=data,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except (ValueError, AttributeError):
                pass
            raise ChatError(f"o Ollama respondeu {exc.code}: {detail}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise ChatError(f"o Ollama não respondeu em {self.host} ({getattr(exc, 'reason', exc)}); "
                            "o container está rodando? (`docker ps`)") from None

    def _json(self, path, payload=None):
        with self._open(path, payload, self.probe_timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def version(self):
        return self._json("/api/version").get("version", "?")

    def models(self):
        return [m.get("name") or m.get("model") for m in self._json("/api/tags").get("models", [])]

    def capabilities(self, model):
        """Lista do /api/show (ex.: completion, tools, thinking) ou None se a versão não informa."""
        caps = self._json("/api/show", {"model": model, "name": model}).get("capabilities")
        return caps if isinstance(caps, list) else None

    def chat(self, payload):
        """Pedaços da resposta (streaming NDJSON)."""
        with self._open("/api/chat", {**payload, "stream": True}) as r:
            for line in r:
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise ChatError(f"Ollama: {chunk['error']}")
                yield chunk
                if chunk.get("done"):
                    return


def pick_model(client, wanted):
    models = client.models()
    if wanted:
        names = set(models) | {m.rsplit(":", 1)[0] for m in models if m.endswith(":latest")}
        if wanted not in names:
            raise ChatError(f"o modelo {wanted!r} não está no Ollama (tem: {', '.join(models) or 'nenhum'}); "
                            f"baixe com `ollama pull {wanted}` dentro do container")
        return wanted
    if len(models) == 1:
        return models[0]
    if not models:
        raise ChatError("nenhum modelo no Ollama; baixe um que suporte ferramentas, "
                        "ex.: `ollama pull qwen3:8b` dentro do container")
    raise ChatError(f"escolha o modelo com --modelo (ou `ollama: {{modelo: ...}}` no minerva.yaml): "
                    f"{', '.join(models)}")


def check_tools(client, model):
    caps = client.capabilities(model)
    if caps is not None and "tools" not in caps:
        raise ChatError(f"o modelo {model} não suporta ferramentas (capacidades: {', '.join(caps)}); "
                        "use um com suporte a tools, ex.: qwen3")


# ---------------------------------------------------------------------------
# Prompt, memória e ferramentas
# ---------------------------------------------------------------------------

def system_prompt(workspace):
    mem = Path(workspace) / connect_mod.MEMORY_NAME
    memory = mem.read_text(encoding="utf-8") if mem.exists() else ""
    memory = re.sub(r"<!--.*?-->\n?", "", memory, flags=re.S).strip() or "(vazio)"
    return f"{connect_mod.rules_text(workspace)}\n\n{CHAT_NOTE}\n\n## MEMORIA.md atual\n{memory}\n"


def remember(workspace, section, line, confirm):
    """Acrescenta `- linha` na seção do MEMORIA.md se o aluno confirmar."""
    line = " ".join(str(line or "").split())[:300]
    if section not in SECTIONS or not line:
        return engine.error("ARGUMENTO_INVALIDO", f"secao deve ser uma de {list(SECTIONS)} e linha não pode ser vazia")
    if not confirm(f"Gravar no {connect_mod.MEMORY_NAME} [{section}]: {line}"):
        return engine._dumps({"gravado": False, "motivo": "o aluno recusou; não proponha de novo agora"})
    connect_mod.ensure_memory(workspace)
    path = Path(workspace) / connect_mod.MEMORY_NAME
    lines = path.read_text(encoding="utf-8").splitlines()
    header = f"## {section}"
    start = next((k for k, text in enumerate(lines) if text.strip() == header), None)
    if start is None:
        lines += ["", header]
        start = len(lines) - 1
    end = next((k for k in range(start + 1, len(lines)) if lines[k].startswith("## ")), len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    lines.insert(end, f"- {line}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return engine._dumps({"gravado": True})


def ollama_tools(mcp_tools):
    out = []
    for t in mcp_tools:
        params = {k: v for k, v in t.input_schema.items() if k != "title"}
        out.append({"type": "function",
                    "function": {"name": t.name, "description": t.description or "", "parameters": params}})
    return out + [REMEMBER_TOOL]


def run_tool(mcp, workspace, name, args, confirm):
    if name == "lembrar":
        return remember(workspace, args.get("secao"), args.get("linha"), confirm)
    if name not in MCP_TOOLS:
        return engine.error("FERRAMENTA_DESCONHECIDA", f"use search, outline, read ou lembrar (recebido {name!r})")
    if name == "read" and isinstance(args.get("refs"), str):  # modelos pequenos mandam um ref solto
        args = {**args, "refs": [args["refs"]]}
    try:
        result = asyncio.run(mcp.call_tool(name, args))
    except Exception as exc:  # noqa: BLE001 - argumento inválido volta ao modelo para ele corrigir
        return engine.error("ARGUMENTO_INVALIDO", " ".join(str(exc).split())[:400])
    return "".join(getattr(c, "text", "") for c in result.content)


# ---------------------------------------------------------------------------
# Conversa
# ---------------------------------------------------------------------------

def _short(args):
    text = json.dumps(args, ensure_ascii=False)
    return text if len(text) <= 90 else text[:87] + "..."


def _stream(client, payload, out):
    parts, calls, thinking = [], [], False
    for chunk in client.chat(payload):
        msg = chunk.get("message") or {}
        if msg.get("thinking") and not thinking and not parts:
            out.write("  (pensando...)\n")
            out.flush()
            thinking = True
        text = msg.get("content") or ""
        if text:
            if not parts:
                out.write("\nminerva> ")
            parts.append(text)
            out.write(text)
            out.flush()
        calls += msg.get("tool_calls") or []
    if parts:
        out.write("\n")
    return "".join(parts), calls


def answer(client, model, workspace, mcp, tools, options, think, history, question, confirm, out):
    """Responde uma pergunta, executando as ferramentas pedidas. Devolve o texto final."""
    turn = [{"role": "user", "content": question}]
    for round_ in range(MAX_TOOL_ROUNDS + 1):
        last = round_ == MAX_TOOL_ROUNDS
        messages = [{"role": "system", "content": system_prompt(workspace)}] + history + turn
        payload = {"model": model, "messages": messages, "options": options}
        if last:
            messages.append({"role": "user", "content": "Pare de chamar ferramentas e responda agora com o "
                             "que encontrou, dizendo o que não está nos materiais."})
        else:
            payload["tools"] = tools
        if think is not None:
            payload["think"] = think
        content, calls = _stream(client, payload, out)
        turn.append({"role": "assistant", "content": content, **({"tool_calls": calls} if calls else {})})
        if not calls or last:
            return content
        for call in calls:
            fn = call.get("function") or {}
            name, args = fn.get("name", ""), fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            out.write(f"  · {name}({_short(args)})\n")
            out.flush()
            turn.append({"role": "tool", "tool_name": name,
                         "content": run_tool(mcp, workspace, name, args, confirm)})
    return ""


def run(workspace, model=None, host=None, think=None, context=None, log=False, ask=input, out=None):
    out = out or sys.stdout
    ws = Path(workspace).resolve()
    cfg = config_mod.load(ws)
    index.connect_ro(ws).close()  # sem índice: falha já, com a instrução de rodar ingest
    client = Ollama(resolve_host(cfg.ollama, host))
    model = pick_model(client, model or cfg.ollama.get("modelo"))
    check_tools(client, model)

    budget = engine.QuestionBudget()
    mcp = server.build(ws, log=log, budget=budget)
    tools = ollama_tools(asyncio.run(mcp.list_tools()))
    options = {"num_ctx": context or cfg.ollama.get("contexto") or DEFAULT_CONTEXT}
    connect_mod.ensure_memory(ws)

    def confirm(text):
        return ask(f"\n{text}\nGravar? [s/N] ").strip().lower() in ("s", "sim", "y", "yes")

    out.write(f"minerva chat: {model} em {client.host}. Digite /sair para encerrar.\n")
    history = []
    while True:
        try:
            question = ask("\nvocê> ").strip()
        except (EOFError, KeyboardInterrupt):
            out.write("\n")
            return
        if question.lower() in EXIT:
            return
        if not question:
            continue
        budget.new_question()
        try:
            reply = answer(client, model, ws, mcp, tools, options, think, history, question, confirm, out)
        except KeyboardInterrupt:
            out.write("\n(interrompido)\n")
            continue
        except ChatError as exc:
            out.write(f"\nerro: {exc}\n")
            continue
        history = (history + [{"role": "user", "content": question},
                              {"role": "assistant", "content": reply}])[-2 * HISTORY_PAIRS:]
