"""Asserções do benchmark_fts5.py da Fase 0, agora sobre o índice persistente."""
import pytest

from minerva import search as engine
from tests.conftest import loads

# (pergunta, prefixos de citação aceitos; vazio = ausente nas fontes)
QUESTIONS = [
    ("O que cai sobre herança e polimorfismo?", ["doc4_resumo_codigo.md §2."]),
    ("qual o padrao singleton e factory method?", ["doc3_slides_padroes.pptx slide 2"]),
    ("qual o peso da prova P1?", ["doc1_ementa.pdf p.2"]),
    ("horário de atendimento", ["doc1_ementa.pdf p.2"]),
    ("heranca e polimorfismo", ["doc4_resumo_codigo.md §2."]),
    ("Quais classes existem em C++?", ["doc4_resumo_codigo.md §2.", "doc3_slides_padroes.pptx slide 2"]),
    ("qual o tempo de ordenacao O(n log n)?", ["doc4_resumo_codigo.md §1."]),
    ("quais as metricas de RNF e teto de tokens?", ["doc2_requisitos_tabela.pdf p.1"]),
    ("padrões de projeto em POO", ["doc3_slides_padroes.pptx slide 1"]),
    ("o que diz sobre loose coupling e composition?", ["doc3_slides_padroes.pptx slide 3", "doc4_resumo_codigo.md §3."]),
    ("inheritance", ["doc4_resumo_codigo.md §3."]),
    ("diferença entre Strategy e State", ["doc3_slides_padroes.pptx slide 3"]),
    ("defina coesão", []),  # só existe no PDF de imagem, sem texto
]
HOSTILE = ['NOT NULL', 'C#', 'snake_case', 'NEAR(a b)', '"; DROP TABLE x; --', '***', '', '(((']
INVALID_ARGS = [("q", -1, 600), ("q", 3, 0), ("q", "3", 600), ("q", True, 600), (None, 3, 600)]


@pytest.mark.parametrize("question,expected", QUESTIONS)
def test_hit_at_3(con, question, expected):
    cites = [r["cite"] for r in loads(engine.search(con, question)[0])["r"]]
    if expected:
        assert any(c.startswith(e) for c in cites for e in expected), cites
    else:
        assert cites == []


@pytest.mark.parametrize("budget", [1, 10, 40, 80, 150, 600, 5000])
def test_search_budget_on_whole_response(con, budget):
    floor = engine.est_tokens(engine.EMPTY_RESPONSE)
    limit = max(min(budget, engine.SEARCH_MAX_TOKENS), floor)
    for q, _ in QUESTIONS:
        assert engine.est_tokens(engine.search(con, q, top_k=5, max_tokens=budget)[0]) <= limit


@pytest.mark.parametrize("args", INVALID_ARGS)
def test_invalid_args_rejected(con, args):
    with pytest.raises(ValueError):
        engine.search(con, *args)


@pytest.mark.parametrize("q", HOSTILE)
def test_hostile_queries_do_not_raise(con, q):
    assert "r" in loads(engine.search(con, q)[0])


def test_material_before_book_and_book_suggestion(tmp_path, workspace):
    from minerva import index
    (workspace / "minerva.yaml").write_text("tipos:\n  doc4_resumo_codigo.md: livro\n", encoding="utf-8")
    index.ingest(workspace)
    con = index.connect_ro(workspace)
    try:
        # Só o "livro" fala de herança: ele vira a resposta.
        resp = loads(engine.search(con, "heranca polimorfismo")[0])
        assert resp["r"][0]["cite"].startswith("doc4_resumo_codigo.md")
        # Material tem prioridade quando também responde.
        resp = loads(engine.search(con, "padroes de projeto")[0])
        assert all(not r["cite"].startswith("doc4") for r in resp["r"])
    finally:
        con.close()
