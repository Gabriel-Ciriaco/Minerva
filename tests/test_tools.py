"""Contratos de outline e read (PLANO_FASE_1 §4)."""
import pytest

from minerva import index
from minerva import search as engine
from tests.conftest import loads


def test_outline_lists_sources_with_status(con):
    items = loads(engine.outline(con))["itens"]
    by_source = {i["source"]: i for i in items}
    assert by_source["doc5_digitalizado_sem_texto.pdf"]["status"] == "sem_texto"
    assert by_source["doc3_slides_padroes.pptx"]["pags"] == 3


def test_source_list_fits_one_page_with_many_sources(workspace):
    # 45 fontes com caminhos longos como os do corpus real: sem `next`.
    folder = workspace / "referencias-disciplinas" / "es1-fundamentos"
    folder.mkdir(parents=True)
    for i in range(40):
        (folder / f"ES_Aula {i:02d} - material.md").write_text(f"## A\ntexto {i}\n", encoding="utf-8")
    index.ingest(workspace)
    con = index.connect_ro(workspace)
    try:
        payload = engine.outline(con)
        resp = loads(payload)
        assert len(resp["itens"]) == 45 and "next" not in resp
        assert engine.est_tokens(payload) <= engine.OUTLINE_SOURCES_MAX_TOKENS
        assert "status" not in resp["itens"][0]  # "ok" é omitido
    finally:
        con.close()


def test_outline_refs_are_readable(con):
    items = loads(engine.outline(con, "doc3_slides_padroes.pptx"))["itens"]
    assert len(items) == 3
    resp = loads(engine.read(con, [items[1]["ref"]]))
    assert resp["r"][0]["cite"] == "doc3_slides_padroes.pptx slide 2"


def test_outline_page_without_text_has_no_ref(con):
    assert loads(engine.outline(con, "doc5_digitalizado_sem_texto.pdf"))["itens"] == []


def test_outline_unknown_and_ambiguous_source(workspace):
    for d in ("turma_a", "turma_b"):
        (workspace / d).mkdir()
        (workspace / d / "aula01.md").write_text("## A\ntexto\n", encoding="utf-8")
    index.ingest(workspace)
    con = index.connect_ro(workspace)
    try:
        assert loads(engine.outline(con, "nao_existe.pdf"))["erro"] == "FONTE_DESCONHECIDA"
        assert "ambíguo" in loads(engine.outline(con, "aula01.md"))["dica"]
        assert loads(engine.outline(con, "turma_b/aula01.md"))["source"] == "turma_b/aula01.md"
        # Nome único continua funcionando sem o caminho.
        assert loads(engine.outline(con, "doc4_resumo_codigo.md"))["source"] == "doc4_resumo_codigo.md"
    finally:
        con.close()


def test_outline_cursor_always_advances_within_budget(con):
    seen, cursor = [], 0
    while True:
        payload = engine.outline(con, "doc4_resumo_codigo.md", cursor, max_tokens=1)
        resp = loads(payload)
        assert len(resp["itens"]) == 1  # orçamento mínimo ainda avança um item
        seen += resp["itens"]
        if "next" not in resp:
            break
        cursor = resp["next"]
    assert len(seen) == 3
    with pytest.raises(ValueError):
        engine.outline(con, None, -1)


def _refs(con, source):
    return [i["ref"] for i in loads(engine.outline(con, source))["itens"]]


@pytest.mark.parametrize("budget", [50, 120, 300, 1500])
def test_read_batch_respects_budget(con, budget):
    refs = _refs(con, "doc4_resumo_codigo.md")
    payload = engine.read(con, refs, vizinhos=1, max_tokens=budget)
    assert engine.est_tokens(payload) <= budget


def test_read_continuation_recovers_full_text(con):
    ref = _refs(con, "doc4_resumo_codigo.md")[1]
    full = loads(engine.read(con, [ref]))["r"][0]["text"]
    parts, offset = [], 0
    while True:
        item = loads(engine.read(con, [ref], offset=offset, max_tokens=80))["r"][0]
        parts.append(item["text"])
        if "continua" not in item:
            break
        assert item["continua"] > offset
        offset = item["continua"]
    assert "".join(parts) == full


def test_read_reports_pending(con):
    refs = _refs(con, "doc4_resumo_codigo.md")
    resp = loads(engine.read(con, refs, max_tokens=120))
    returned = [r["ref"] for r in resp["r"]]
    assert set(returned) | set(resp.get("pendentes", [])) == set(refs)


def test_read_neighbors_dedup_and_order(con):
    refs = _refs(con, "doc3_slides_padroes.pptx")
    resp = loads(engine.read(con, [refs[1], refs[2]], vizinhos=1))
    assert [r["ref"] for r in resp["r"]] == refs  # 1,2,3 sem repetir 2 e 3


@pytest.mark.parametrize("refs,kw", [
    ([], {}), (["a", "b", "c", "d"], {}), ([1], {}), (["a"], {"vizinhos": 2}),
    (["a"], {"vizinhos": True}), (["a", "b"], {"offset": 5}), (["a"], {"offset": -1}),
])
def test_read_invalid_args(con, refs, kw):
    with pytest.raises(ValueError):
        engine.read(con, refs, **kw)


def test_read_unknown_ref(con):
    resp = loads(engine.read(con, ["xxxx1@000000p0"]))
    assert resp["r"] == [] and resp["erros"][0]["erro"] == "REF_DESCONHECIDO"


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _slides(con):
    return [i["ref"] for i in loads(engine.outline(con, "doc3_slides_padroes.pptx"))["itens"]]


def test_read_budget_refuses_sweeping_a_document(con):
    budget = engine.QuestionBudget(per_doc=2, clock=FakeClock())
    s1, s2, s3 = _slides(con)
    for ref in (s1, s2):
        assert budget.check(con, [ref]) is None
        budget.record(con, engine.read(con, [ref]))
    assert "doc3_slides_padroes.pptx" in budget.check(con, [s3])
    assert budget.check(con, [s1]) is None  # já lida: continuação com offset continua valendo
    assert budget.check(con, ["doc1_ementa.pdf#inexistente"]) is None  # erro de ref fica com read


def test_read_budget_counts_neighbours_and_allows_search_hits(con):
    budget = engine.QuestionBudget(per_doc=2, clock=FakeClock())
    s1, s2, s3 = _slides(con)
    budget.record(con, engine.read(con, [s2], vizinhos=1))  # 3 páginas de uma vez
    assert budget.check(con, [s3]) is None  # já lida pelos vizinhos
    budget = engine.QuestionBudget(per_doc=1, clock=FakeClock())
    budget.record(con, engine.read(con, [s1]))
    assert budget.check(con, [s2]) is not None
    budget.saw_search(engine._dumps({"r": [{"ref": s2}]}))
    assert budget.check(con, [s2]) is None


def test_read_budget_resets_after_a_pause(con):
    clock = FakeClock()
    budget = engine.QuestionBudget(per_doc=1, idle=90, clock=clock)
    s1, s2, _ = _slides(con)
    budget.tick()
    budget.record(con, engine.read(con, [s1]))
    assert budget.list_sources() and not budget.list_sources()
    clock.t = 60
    budget.tick()
    assert budget.check(con, [s2]) is not None
    clock.t = 200  # nova pergunta
    budget.tick()
    assert budget.check(con, [s2]) is None
    assert budget.list_sources()


def test_question_budget_warns_after_too_many_calls():
    budget = engine.QuestionBudget(calls=3, clock=FakeClock())
    assert budget.tick() is None and budget.tick() is None
    assert "3 chamadas" in budget.tick()
