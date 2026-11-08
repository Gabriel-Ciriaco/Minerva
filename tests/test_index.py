"""Garantias novas do índice persistente (PLANO_FASE_1 §6, etapa 1.2)."""
import os
import subprocess
import sys

import pytest

from minerva import extract, index
from minerva import search as engine
from tests.conftest import loads


def _actions(rows):
    return {r["file"]: r["acao"] for r in rows}


def test_unchanged_ingest_is_noop(workspace):
    assert set(_actions(index.ingest(workspace)).values()) == {"igual"}


def test_changed_file_replaces_chunks_and_stales_old_ref(workspace):
    con = index.connect_ro(workspace)  # leitor aberto durante a ingestão
    old_ref = loads(engine.outline(con, "doc4_resumo_codigo.md"))["itens"][0]["ref"]
    md = workspace / "doc4_resumo_codigo.md"
    md.write_text("# Resumo\n## Nova seção\nconteudo totalmente novo sobre zebras\n", encoding="utf-8")
    assert _actions(index.ingest(workspace))["doc4_resumo_codigo.md"] == "alterado"
    # O mesmo leitor vê a versão nova sem reabrir.
    assert loads(engine.search(con, "zebras")[0])["r"]
    assert loads(engine.read(con, [old_ref]))["erros"][0]["erro"] == "STALE_REFERENCE"
    assert not loads(engine.search(con, "polimorfismo")[0])["r"]
    con.close()


def test_new_and_removed_files(workspace):
    (workspace / "doc1_ementa.pdf").unlink()
    (workspace / "novo.md").write_text("## X\nornitorrinco\n", encoding="utf-8")
    acts = _actions(index.ingest(workspace))
    assert acts["doc1_ementa.pdf"] == "removido" and acts["novo.md"] == "novo"


def test_scan_error_never_deletes(workspace, monkeypatch):
    def broken(*a, **k):
        raise PermissionError("sem acesso")
    monkeypatch.setattr(index, "scan", broken)
    with pytest.raises(PermissionError):
        index.ingest(workspace)
    con = index.connect_ro(workspace)
    assert con.execute("SELECT count(*) FROM sources").fetchone()[0] == 5
    con.close()


def test_failed_reextraction_keeps_old_version_out_of_search(workspace, monkeypatch):
    md = workspace / "doc4_resumo_codigo.md"
    md.write_text(md.read_text(encoding="utf-8") + "\n## Extra\nmais\n", encoding="utf-8")
    monkeypatch.setattr(index, "extract_file", lambda p: ([], {"status": "erro: Boom", "pages": 0}))
    assert _actions(index.ingest(workspace))["doc4_resumo_codigo.md"] == "falhou"
    con = index.connect_ro(workspace)
    assert not loads(engine.search(con, "polimorfismo")[0])["r"]
    status = {i["source"]: i.get("status", "ok") for i in loads(engine.outline(con))["itens"]}
    assert status["doc4_resumo_codigo.md"] == "desatualizado"
    con.close()


def test_publish_is_atomic(workspace, monkeypatch):
    md = workspace / "doc4_resumo_codigo.md"
    md.write_text("## Nova\nzebras\n", encoding="utf-8")
    def crash(con, *a):
        with con:
            con.execute("DELETE FROM chunks WHERE source = ?", ("doc4_resumo_codigo.md",))
            raise RuntimeError("queda no meio da publicação")
    monkeypatch.setattr(index, "_publish", crash)
    with pytest.raises(RuntimeError):
        index.ingest(workspace)
    con = index.connect_ro(workspace)
    assert loads(engine.search(con, "polimorfismo")[0])["r"]  # versão antiga intacta
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()
    monkeypatch.undo()
    assert _actions(index.ingest(workspace))["doc4_resumo_codigo.md"] == "alterado"


def test_killed_ingest_leaves_usable_index(workspace):
    (workspace / "grande.md").write_text("".join(f"## S{i}\nzebra {i}\n" for i in range(3000)), encoding="utf-8")
    code = ("import sys, os; from minerva import index, extract; real = extract.extract_file\n"
            "def slow(p):\n    r = real(p)\n    if p.name == 'grande.md': os._exit(9)\n    return r\n"
            "index.extract_file = slow; index.ingest(sys.argv[1])")
    proc = subprocess.run([sys.executable, "-c", code, str(workspace)])
    assert proc.returncode == 9
    assert (workspace / ".minerva" / "ingest.lock").exists()  # órfão
    acts = _actions(index.ingest(workspace))  # retoma o lock de processo morto
    assert acts["grande.md"] == "novo"


def test_live_lock_is_refused(workspace):
    lock = workspace / ".minerva" / "ingest.lock"
    lock.write_text(str(os.getpid()))
    with pytest.raises(index.IndexUnavailable):
        index.ingest(workspace)
    lock.unlink()


def test_config_change_triggers_full_reindex(workspace):
    (workspace / "minerva.yaml").write_text("ignorar: [doc2_requisitos_tabela.pdf]\n", encoding="utf-8")
    acts = _actions(index.ingest(workspace))
    assert acts["doc2_requisitos_tabela.pdf"] == "removido"
    assert acts["doc1_ementa.pdf"] == "alterado"


def _fontes_layout(workspace):
    (workspace / "materiais" / "sub").mkdir(parents=True)
    (workspace / "materiais" / "aula.md").write_text("## A\ncapivara\n", encoding="utf-8")
    (workspace / "materiais" / "sub" / "rascunho.md").write_text("## R\ntamandua\n", encoding="utf-8")
    (workspace / "exercicios").mkdir()
    (workspace / "exercicios" / "lista.md").write_text("## L\nsolucao minha\n", encoding="utf-8")


def test_fontes_limits_scan_to_listed_paths(workspace):
    _fontes_layout(workspace)
    (workspace / "minerva.yaml").write_text(
        "fontes: [materiais, doc1_ementa.pdf]\nignorar: [materiais/sub/]\n", encoding="utf-8")
    acts = _actions(index.ingest(workspace))
    assert acts["materiais/aula.md"] == "novo"
    assert acts["doc1_ementa.pdf"] == "alterado"           # assinatura mudou: reextraído
    assert acts["doc4_resumo_codigo.md"] == "removido"     # fora das fontes
    assert "exercicios/lista.md" not in acts               # nunca entrou
    assert "materiais/sub/rascunho.md" not in acts         # ignorar vale dentro das fontes
    con = index.connect_ro(workspace)
    assert index.pending_changes(con, workspace) == []
    con.close()


def test_removing_fontes_brings_workspace_back(workspace):
    _fontes_layout(workspace)
    (workspace / "minerva.yaml").write_text("fontes: [materiais/]\n", encoding="utf-8")
    index.ingest(workspace)
    (workspace / "minerva.yaml").write_text("", encoding="utf-8")
    acts = _actions(index.ingest(workspace))
    assert acts["exercicios/lista.md"] == "novo" and acts["doc4_resumo_codigo.md"] == "novo"


def test_unsupported_files_are_not_sources(workspace):
    (workspace / "script.py").write_text("print(1)\n", encoding="utf-8")
    (workspace / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (workspace / "foto.jpg").write_bytes(b"\xff\xd8")
    rows = index.ingest(workspace)
    motivos = {r["file"]: r.get("motivo") for r in rows}
    assert motivos["script.py"] == motivos["LICENSE"] == "formato não suportado"
    assert _actions(rows)["foto.jpg"] == "novo"  # imagem continua listada (imagem_sem_ocr)
    con = index.connect_ro(workspace)
    paths = {p for (p,) in con.execute("SELECT path FROM sources")}
    assert "script.py" not in paths and "foto.jpg" in paths
    assert index.pending_changes(con, workspace) == []
    con.close()


def test_unsupported_summary_is_one_line():
    from minerva.cli import _unsupported_summary
    line = _unsupported_summary(["a.py", "b/c.py", "LICENSE", "x.css"])
    assert line.startswith("4 arquivo(s)") and ".py ×2" in line and "\n" not in line


def test_schema_mismatch_requires_rebuild(workspace):
    import sqlite3
    db = sqlite3.connect(index.db_path(workspace))
    db.execute("UPDATE meta SET value = '0' WHERE key = 'schema'")
    db.commit()
    db.close()
    with pytest.raises(index.IndexUnavailable, match="rebuild"):
        index.connect_ro(workspace)
    index.ingest(workspace, rebuild=True)
    index.connect_ro(workspace).close()


def test_pending_changes_detected_without_ingest(workspace, con):
    assert index.pending_changes(con, workspace) == []
    (workspace / "novo.md").write_text("## A\nb\n", encoding="utf-8")
    assert index.pending_changes(con, workspace) == ["novo.md"]


def test_agent_files_and_hidden_dirs_are_not_sources(workspace):
    (workspace / ".agents").mkdir()
    (workspace / ".agents" / "notas.md").write_text("## x\nsegredo\n", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("## x\nsegredo\n", encoding="utf-8")
    (workspace / "memory.md").write_text("## x\nsegredo\n", encoding="utf-8")
    (workspace / "MEMORIA.md").write_text("## x\nsegredo\n", encoding="utf-8")
    index.ingest(workspace)
    con = index.connect_ro(workspace)
    assert not loads(engine.search(con, "segredo")[0])["r"]
    con.close()


def test_symlink_outside_workspace_is_skipped(workspace, tmp_path):
    outside = tmp_path / "fora.md"
    outside.write_text("## x\nexterno\n", encoding="utf-8")
    try:
        (workspace / "link.md").symlink_to(outside)
    except OSError:
        pytest.skip("criação de symlink não permitida neste sistema")
    acts = _actions(index.ingest(workspace))
    assert acts["link.md"] == "ignorado"


def test_boilerplate_and_printed_page():
    body = "\n".join(f"linha {k} do corpo" for k in range(6))
    units = [{"page": i, "content": f"Livro X - Cap 1\n{body}\nDefinição: acoplamento\n{body}\n{i - 10}",
              "heading": ""} for i in range(11, 31)]
    assert extract.printed_offset(units) == 10
    removed = extract.strip_boilerplate(units)
    assert removed >= 20 and all("Livro X" not in u["content"] for u in units)
    # Linha repetida no meio da página (definição) fica.
    assert all("Definição: acoplamento" in u["content"] for u in units)
