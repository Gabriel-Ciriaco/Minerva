import json

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
])
def test_invalid_config_is_explicit_error(tmp_path, text):
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "minerva.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)
