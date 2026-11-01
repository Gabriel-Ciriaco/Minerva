"""
Integração com o Antigravity: só arquivos do `.agents` do workspace, nunca o config global.

Idempotente: rodar de novo sem mudanças não altera nada. No mcp_config.json só a entrada
`minerva` é criada ou atualizada; no AGENTS.md só o bloco entre os marcadores do Minerva.
"""
import json
import sys
from importlib.resources import files
from pathlib import Path

from minerva import config as config_mod

AGENTS_DIR = ".agents"
BEGIN, END = "<!-- minerva:inicio -->", "<!-- minerva:fim -->"


def server_entry(workspace, log=False):
    """Executável e argumentos separados, workspace absoluto: não depende do cwd do cliente."""
    args = ["-m", "minerva", "serve", "--workspace", str(Path(workspace).resolve())]
    return {"command": sys.executable, "args": args + (["--log"] if log else [])}


def _rules(workspace):
    disciplina = config_mod.load(workspace).disciplina
    title = f"de {disciplina}" if disciplina else "da disciplina"
    text = files("minerva").joinpath("templates/AGENTS.md").read_text(encoding="utf-8")
    return f"{BEGIN}\n{text.replace('{disciplina}', title).strip()}\n{END}\n"


def _write_config(path, workspace, force, log):
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
        return "conflito", (f"{path}: a entrada minerva é diferente\n"
                            f"  atual: {json.dumps(current, ensure_ascii=False)}\n"
                            f"  nova:  {json.dumps(entry, ensure_ascii=False)}\n"
                            "  use --force para substituir só essa entrada")
    servers["minerva"] = entry
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    others = len(servers) - 1
    return "escrito", f"{path}: entrada minerva {'atualizada' if current else 'criada'}" + \
        (f" ({others} outro(s) servidor(es) preservado(s))" if others else "")


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


def connect_antigravity(workspace, force=False, log=False):
    """Retorna [(estado, mensagem)]; estado ∈ escrito, igual, conflito, erro."""
    folder = Path(workspace).resolve() / AGENTS_DIR
    folder.mkdir(exist_ok=True)
    return [_write_config(folder / "mcp_config.json", workspace, force, log),
            _write_rules(folder / "AGENTS.md", workspace)]
