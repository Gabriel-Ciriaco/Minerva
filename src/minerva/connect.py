"""
Integração com clientes MCP: arquivos só dentro do workspace, nunca a configuração global.

| cliente     | servidor MCP              | regras            |
|-------------|---------------------------|-------------------|
| antigravity | .agents/mcp_config.json   | .agents/AGENTS.md |
| claude-code | .mcp.json                 | CLAUDE.md         |
| codex       | .codex/config.toml        | AGENTS.md         |

Idempotente: rodar de novo sem mudanças não altera nada. Na configuração do cliente só a
entrada `minerva` é criada ou atualizada; no arquivo de regras só o bloco entre os
marcadores do Minerva. O resto dos arquivos é preservado.
"""
import copy
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from minerva import config as config_mod

AGENTS_DIR = ".agents"
MEMORY_NAME = "MEMORIA.md"
BEGIN, END = "<!-- minerva:inicio -->", "<!-- minerva:fim -->"


@dataclass(frozen=True)
class Client:
    nome: str
    config: str  # caminho relativo ao workspace
    rules: str
    fmt: str     # json | toml
    dica: str    # o que fazer depois de escrever


CLIENTS = {
    "antigravity": Client(
        "Antigravity", f"{AGENTS_DIR}/mcp_config.json", f"{AGENTS_DIR}/AGENTS.md", "json",
        "Recarregue o Antigravity (ou reabra a pasta) e confira se o servidor `minerva` aparece "
        "nas ferramentas MCP."),
    "claude-code": Client(
        "Claude Code", ".mcp.json", "CLAUDE.md", "json",
        "Abra o Claude Code nesta pasta, aprove o servidor `minerva` do .mcp.json quando ele "
        "perguntar e confira com /mcp."),
    "codex": Client(
        "Codex CLI", ".codex/config.toml", "AGENTS.md", "toml",
        "Abra o Codex nesta pasta e marque-a como confiável quando ele perguntar: sem isso ele "
        "ignora o .codex/config.toml. Confira se o servidor `minerva` aparece nas ferramentas MCP."),
}


def server_entry(workspace, log=False):
    """Executável e argumentos separados, workspace absoluto: não depende do cwd do cliente."""
    args = ["-m", "minerva", "serve", "--workspace", str(Path(workspace).resolve())]
    return {"command": sys.executable, "args": args + (["--log"] if log else [])}


def snippet(workspace, log=False):
    """Entrada no formato mais comum (`mcpServers`), para colar em outros clientes."""
    return json.dumps({"mcpServers": {"minerva": server_entry(workspace, log)}}, indent=2, ensure_ascii=False)


def rules_text(workspace):
    """Regras do agente (templates/AGENTS.md) com o nome da disciplina, sem marcadores."""
    disciplina = config_mod.load(workspace).disciplina
    title = f"de {disciplina}" if disciplina else "da disciplina"
    text = files("minerva").joinpath("templates/AGENTS.md").read_text(encoding="utf-8")
    return text.replace("{disciplina}", title).strip()


def _rules(workspace):
    return f"{BEGIN}\n{rules_text(workspace)}\n{END}\n"


# ---------------------------------------------------------------------------
# Configuração do servidor
# ---------------------------------------------------------------------------

def _conflict(path, current, entry):
    return "conflito", (f"{path}: a entrada minerva é diferente\n"
                        f"  atual: {json.dumps(current, ensure_ascii=False)}\n"
                        f"  nova:  {json.dumps(entry, ensure_ascii=False)}\n"
                        "  use --force para substituir só essa entrada")


def _write_json(path, workspace, force, log):
    entry = server_entry(workspace, log)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return "erro", f"{path} não é JSON válido; corrija ou apague o arquivo"
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
            return "erro", f"{path} não tem o formato esperado ({{\"mcpServers\": {{...}}}})"
    servers = data.setdefault("mcpServers", {})
    current = servers.get("minerva")
    if current == entry:
        return "igual", f"{path}: entrada minerva já atualizada"
    if current is not None and not force:
        return _conflict(path, current, entry)
    servers["minerva"] = entry
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    others = len(servers) - 1
    return "escrito", f"{path}: entrada minerva {'atualizada' if current else 'criada'}" + \
        (f" ({others} outro(s) servidor(es) preservado(s))" if others else "")


_TOML_HEADER = re.compile(r"^\s*\[{1,2}([^\[\]]+)\]{1,2}\s*(?:#.*)?$")


def _toml_table(entry):
    # Strings JSON (com ensure_ascii=False) são strings básicas TOML válidas; a releitura confere.
    return ("[mcp_servers.minerva]\n"
            f"command = {json.dumps(entry['command'], ensure_ascii=False)}\n"
            f"args = {json.dumps(entry['args'], ensure_ascii=False)}\n")


def _write_toml(path, workspace, force, log):
    """Edita só a tabela [mcp_servers.minerva] (e subtabelas); grava apenas se a releitura
    mostrar a entrada nova e todo o resto do arquivo igual ao que era."""
    entry = server_entry(workspace, log)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return "erro", f"{path} não é TOML válido ({exc}); corrija ou apague o arquivo"
    servers = data.get("mcp_servers", {})
    if not isinstance(servers, dict):
        return "erro", f"{path}: mcp_servers não é uma tabela"
    current = servers.get("minerva")
    if current == entry:
        return "igual", f"{path}: entrada minerva já atualizada"
    if current is not None and not force:
        return _conflict(path, current, entry)

    kept, skipping = [], False
    for line in text.splitlines(keepends=True):
        m = _TOML_HEADER.match(line)
        if m:
            name = ".".join(p.strip().strip("\"'") for p in m.group(1).split("."))
            skipping = name == "mcp_servers.minerva" or name.startswith("mcp_servers.minerva.")
        if not skipping:
            kept.append(line)
    base = "".join(kept).rstrip()
    new = (base + "\n\n" if base else "") + _toml_table(entry)

    expected = copy.deepcopy(data)
    expected.setdefault("mcp_servers", {})["minerva"] = entry
    try:
        ok = tomllib.loads(new) == expected
    except tomllib.TOMLDecodeError:
        ok = False
    if not ok:
        return "erro", (f"{path}: não consegui trocar a entrada minerva com segurança; "
                        f"edite à mão e use:\n{_toml_table(entry)}")
    path.write_text(new, encoding="utf-8")
    return "escrito", f"{path}: entrada minerva {'atualizada' if current else 'criada'}"


def _read_entry(client, path):
    """(entrada minerva ou None, erro ou None)."""
    try:
        text = path.read_text(encoding="utf-8")
        if client.fmt == "toml":
            servers = tomllib.loads(text).get("mcp_servers", {})
        else:
            servers = json.loads(text or "{}").get("mcpServers", {})
    except (OSError, ValueError, AttributeError) as exc:  # JSON/TOML inválidos são ValueError
        return None, f"ilegível ({type(exc).__name__})"
    if not isinstance(servers, dict):
        return None, "com formato inesperado"
    return servers.get("minerva"), None


# ---------------------------------------------------------------------------
# Regras e memória
# ---------------------------------------------------------------------------

def _write_rules(path, workspace):
    block = _rules(workspace)
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        return "escrito", f"{path}: criado"
    text = path.read_text(encoding="utf-8")
    start, end = text.find(BEGIN), text.find(END)
    if start == -1 or end == -1 or end < start:
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        path.write_text(text + sep + block, encoding="utf-8")
        return "escrito", f"{path}: bloco do Minerva acrescentado ao fim; o resto não foi alterado"
    new = text[:start] + block.rstrip("\n") + text[end + len(END):]
    if new == text:
        return "igual", f"{path}: bloco do Minerva já atualizado"
    path.write_text(new, encoding="utf-8")
    return "escrito", f"{path}: bloco do Minerva atualizado; o resto não foi alterado"


def _rules_state(path, workspace):
    """ok, ausente ou desatualizado."""
    if not path.exists():
        return "ausente"
    text = path.read_text(encoding="utf-8")
    start, end = text.find(BEGIN), text.find(END)
    if start == -1 or end == -1 or end < start:
        return "ausente"
    return "ok" if text[start:end + len(END)] == _rules(workspace).rstrip("\n") else "desatualizado"


def ensure_memory(workspace):
    """Cria o MEMORIA.md na raiz do workspace se não existir; nunca altera um existente."""
    path = Path(workspace).resolve() / MEMORY_NAME
    if path.exists():
        return "igual", f"{path}: mantido"
    path.write_text(files("minerva").joinpath("templates/MEMORIA.md").read_text(encoding="utf-8"),
                    encoding="utf-8")
    return "escrito", f"{path}: criado"


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def connect(name, workspace, force=False, log=False):
    """Retorna [(estado, mensagem)]; estado ∈ escrito, igual, conflito, erro."""
    ws = Path(workspace).resolve()
    client = CLIENTS[name]
    cfg_path = ws / client.config
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    writer = _write_toml if client.fmt == "toml" else _write_json
    return [writer(cfg_path, ws, force, log), _write_rules(ws / client.rules, ws), ensure_memory(ws)]


def connect_antigravity(workspace, force=False, log=False):
    return connect("antigravity", workspace, force, log)


def status(name, workspace):
    """None se o cliente não está conectado nesta pasta; senão (nível, mensagem) para o doctor."""
    ws = Path(workspace).resolve()
    client = CLIENTS[name]
    path = ws / client.config
    if not path.exists():
        return None
    entry, err = _read_entry(client, path)
    if err:
        return "ERRO", f"{client.nome}: {path} {err}"
    if entry is None:
        return None
    fix = f"rode `minerva connect {name} --force`"
    command = entry.get("command") if isinstance(entry, dict) else None
    if not isinstance(command, str) or not Path(command).exists():
        return "ERRO", f"{client.nome}: o Python da entrada minerva não existe ({command}); {fix}"
    if entry not in (server_entry(ws), server_entry(ws, log=True)):
        return "AVISO", f"{client.nome}: entrada minerva difere da gerada por este ambiente; {fix} se o .venv mudou"
    rules = _rules_state(ws / client.rules, ws)
    if rules != "ok":
        word = "ausentes" if rules == "ausente" else "desatualizadas"
        return "AVISO", f"{client.nome}: regras {word} em {client.rules}; rode `minerva connect {name}`"
    return "OK", f"{client.nome}: {client.config} aponta para este Python e este workspace"
