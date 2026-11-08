import json
import tomllib

import pytest

from minerva import config, connect


def test_connect_is_idempotent_and_preserves_others(tmp_path):
    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / "mcp_config.json").write_text(json.dumps({"mcpServers": {"outro": {"command": "x"}}}))
    (agents / "AGENTS.md").write_text("# Minhas regras\nnão mexa\n", encoding="utf-8")

    first = connect.connect_antigravity(tmp_path)
    assert [s for s, _ in first] == ["escrito", "escrito", "escrito"]
    second = connect.connect_antigravity(tmp_path)
    assert [s for s, _ in second] == ["igual", "igual", "igual"]

    data = json.loads((agents / "mcp_config.json").read_text())
    assert data["mcpServers"]["outro"] == {"command": "x"}
    entry = data["mcpServers"]["minerva"]
    assert entry["args"][-1] == str(tmp_path.resolve()) and entry["args"][:3] == ["-m", "minerva", "serve"]
    rules = (agents / "AGENTS.md").read_text(encoding="utf-8")
    assert rules.startswith("# Minhas regras\nnão mexa\n") and rules.count(connect.BEGIN) == 1


def test_connect_title_and_log(tmp_path):
    connect.connect_antigravity(tmp_path, log=True)
    rules = (tmp_path / ".agents" / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Tutor da disciplina (Minerva)" in rules
    entry = json.loads((tmp_path / ".agents" / "mcp_config.json").read_text())["mcpServers"]["minerva"]
    assert entry["args"][-1] == "--log"
    (tmp_path / "minerva.yaml").write_text("disciplina: Cálculo I\n", encoding="utf-8")
    connect.connect_antigravity(tmp_path, log=True)
    assert "# Tutor de Cálculo I (Minerva)" in (tmp_path / ".agents" / "AGENTS.md").read_text(encoding="utf-8")


def test_connect_conflict_requires_force(tmp_path):
    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / "mcp_config.json").write_text(json.dumps({"mcpServers": {"minerva": {"command": "velho"}}}))
    assert connect.connect_antigravity(tmp_path)[0][0] == "conflito"
    assert connect.connect_antigravity(tmp_path, force=True)[0][0] == "escrito"


def test_connect_updates_only_minerva_block(tmp_path):
    connect.connect_antigravity(tmp_path)
    path = tmp_path / ".agents" / "AGENTS.md"
    path.write_text("antes\n" + path.read_text(encoding="utf-8").replace("Tutor", "Velho") + "depois\n",
                    encoding="utf-8")
    assert connect.connect_antigravity(tmp_path)[1][0] == "escrito"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("antes\n") and text.endswith("depois\n") and "Velho" not in text


def test_memory_is_created_once_and_never_overwritten(tmp_path):
    assert connect.ensure_memory(tmp_path)[0] == "escrito"
    mem = tmp_path / "MEMORIA.md"
    assert "## Andamento" in mem.read_text(encoding="utf-8")
    mem.write_text("minha memória\n", encoding="utf-8")
    assert connect.ensure_memory(tmp_path)[0] == "igual"
    assert mem.read_text(encoding="utf-8") == "minha memória\n"


def test_rules_mention_memory(tmp_path):
    connect.connect_antigravity(tmp_path)
    rules = (tmp_path / ".agents" / "AGENTS.md").read_text(encoding="utf-8")
    assert "MEMORIA.md" in rules and "disser sim" in rules


def test_config_precedence(tmp_path):
    (tmp_path / "minerva.yaml").write_text(
        "tipos:\n  livros/: livro\n  livros/curtos/: material\n  livros/curtos/x.pdf: livro\n", encoding="utf-8")
    cfg = config.load(tmp_path)
    assert cfg.doc_type("livros/a.pdf") == "livro"
    assert cfg.doc_type("livros/curtos/b.pdf") == "material"
    assert cfg.doc_type("livros/curtos/x.pdf") == "livro"
    assert cfg.doc_type("slides/a.pdf") is None


def test_fontes_normalized(tmp_path):
    (tmp_path / "materiais").mkdir()
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "minerva.yaml").write_text("fontes: ['materiais', 'materiais/', 'a.md']\n", encoding="utf-8")
    assert config.load(tmp_path).fontes == ["a.md", "materiais/"]


@pytest.mark.parametrize("text", [
    "tipo: {a: livro}\n",            # chave desconhecida
    "tipos: {a.pdf: apostila}\n",    # tipo inválido
    "tipos: {../fora.pdf: livro}\n", # fora do workspace
    "ignorar: rascunhos/\n",         # não é lista
    "- lista\n",                     # não é mapa
    "tipos: [\n",                    # YAML quebrado
    "fontes: materiais/\n",          # não é lista
    "fontes: [nao_existe/]\n",       # inexistente
    "fontes: [../fora/]\n",          # fora do workspace
    "fontes: [.]\n",                 # workspace inteiro: basta apagar a chave
    "fontes: [a.md/]\n",             # arquivo com barra de pasta
    "ollama: qwen3\n",               # não é mapa
    "ollama: {model: qwen3}\n",      # chave em inglês
    "ollama: {contexto: 1000}\n",    # contexto pequeno demais
    "ollama: {modelo: 3}\n",         # modelo não é texto
])
def test_invalid_config_is_explicit_error(tmp_path, text):
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "minerva.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)


def test_ollama_config_does_not_change_index_signature(tmp_path):
    before = config.load(tmp_path).signature()
    (tmp_path / "minerva.yaml").write_text("ollama: {modelo: 'qwen3:8b', contexto: 16384}\n", encoding="utf-8")
    cfg = config.load(tmp_path)
    assert cfg.ollama == {"modelo": "qwen3:8b", "contexto": 16384} and cfg.signature() == before


# ---------------------------------------------------------------------------
# Claude Code e Codex
# ---------------------------------------------------------------------------

def test_connect_claude_code(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# Minhas notas\n", encoding="utf-8")
    first = connect.connect("claude-code", tmp_path)
    assert [s for s, _ in first] == ["escrito", "escrito", "escrito"]
    assert [s for s, _ in connect.connect("claude-code", tmp_path)] == ["igual", "igual", "igual"]
    entry = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["minerva"]
    assert entry == connect.server_entry(tmp_path)
    rules = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert rules.startswith("# Minhas notas\n") and "mcp__minerva__search" in rules
    assert not (tmp_path / ".agents").exists()  # não mexe em outro cliente


CODEX_EXISTING = """\
# configuração do aluno
model = "gpt-5"

[mcp_servers.outro]
command = "npx"
args = ["-y", "outro"]

[mcp_servers.minerva]
command = "C:\\\\velho\\\\python.exe"
args = ["-m", "minerva"]

[mcp_servers.minerva.env]
X = "1"

[profiles.rapido]
model = "gpt-5-mini"
"""


def test_connect_codex_creates_project_config(tmp_path):
    states = [s for s, _ in connect.connect("codex", tmp_path)]
    assert states == ["escrito", "escrito", "escrito"]
    data = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data == {"mcp_servers": {"minerva": connect.server_entry(tmp_path)}}
    assert connect.BEGIN in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert connect.connect("codex", tmp_path)[0][0] == "igual"


def test_connect_codex_preserves_everything_else(tmp_path):
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir()
    path.write_text(CODEX_EXISTING, encoding="utf-8")
    assert connect.connect("codex", tmp_path)[0][0] == "conflito"
    assert path.read_text(encoding="utf-8") == CODEX_EXISTING  # conflito não grava nada
    assert connect.connect("codex", tmp_path, force=True)[0][0] == "escrito"
    text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["mcp_servers"]["minerva"] == connect.server_entry(tmp_path)  # env antigo saiu junto
    assert data["mcp_servers"]["outro"] == {"command": "npx", "args": ["-y", "outro"]}
    assert data["model"] == "gpt-5" and data["profiles"]["rapido"]["model"] == "gpt-5-mini"
    assert text.startswith("# configuração do aluno\n") and "velho" not in text


def test_connect_codex_paths_with_accents_and_quotes(tmp_path):
    ws = tmp_path / "matéria d'o aluno"
    ws.mkdir()
    connect.connect("codex", ws)
    data = tomllib.loads((ws / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data["mcp_servers"]["minerva"]["args"][-1] == str(ws.resolve())
    # Aspas e barras invertidas (possíveis em nomes no Linux) também saem como TOML válido.
    entry = {"command": 'C:\\a "b"\\python.exe', "args": ["x'y", "ç\\", 'tab\t"']}
    assert tomllib.loads(connect._toml_table(entry))["mcp_servers"]["minerva"] == entry


@pytest.mark.parametrize("text", ["isto não é toml = = \n", "[mcp_servers]\nminerva = 3\n"])
def test_connect_codex_refuses_unsafe_edit(tmp_path, text):
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    state = connect.connect("codex", tmp_path, force=True)[0][0]
    assert state == "erro" and path.read_text(encoding="utf-8") == text


def test_status_per_client(tmp_path):
    assert all(connect.status(name, tmp_path) is None for name in connect.CLIENTS)
    connect.connect("codex", tmp_path)
    assert connect.status("codex", tmp_path)[0] == "OK"
    assert connect.status("claude-code", tmp_path) is None
    (tmp_path / "minerva.yaml").write_text("disciplina: Outra\n", encoding="utf-8")  # regras mudam
    level, msg = connect.status("codex", tmp_path)
    assert level == "AVISO" and "desatualizadas" in msg
    path = tmp_path / ".codex" / "config.toml"
    path.write_text('[mcp_servers.minerva]\ncommand = "C:/nao/existe/python.exe"\nargs = []\n', encoding="utf-8")
    assert connect.status("codex", tmp_path)[0] == "ERRO"
    path.write_text("isto não é toml = =\n", encoding="utf-8")
    assert connect.status("codex", tmp_path)[0] == "ERRO"


def test_snippet_is_valid_json(tmp_path):
    data = json.loads(connect.snippet(tmp_path))
    assert data["mcpServers"]["minerva"] == connect.server_entry(tmp_path)
