"""
Ferramentas de leitura do índice: search, outline e read.

Toda resposta é JSON e respeita um teto sobre a resposta SERIALIZADA INTEIRA (texto,
citações, erros e continuação), pela estimativa declarada de 1 token ~ 4 caracteres.
"""
import json
import re
import time

from minerva.extract import fold
from minerva.index import ref_prefix

MAX_TOP_K = 5
SEARCH_MAX_TOKENS = 600
OUTLINE_MAX_TOKENS = 600
OUTLINE_SOURCES_MAX_TOKENS = 1500  # ~50 fontes numa página só
READ_MAX_TOKENS = 1500   # lote inteiro; valor inicial, a ajustar medindo
READ_MAX_REFS = 3


def est_tokens(text):
    """Estimativa declarada do projeto: 1 token ~ 4 caracteres."""
    return (len(text) + 3) // 4


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def _fits(obj, max_tokens):
    return est_tokens(_dumps(obj)) <= max_tokens


def error(code, message):
    return _dumps({"erro": code, "dica": message})


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

# Pesos por coluna do FTS: title, heading, content.
BM25 = "bm25(chunks_fts, 5.0, 3.0, 1.0)"
# Páginas sem o termo toleradas dentro de uma seção do livro (figura, exercício no meio).
SECTION_GAP = 1

# Conservadora: só palavras funcionais e de formulação de pergunta. Palavras de
# conteúdo ("diferença", "not") nunca entram aqui.
STOPWORDS = {
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "para", "por", "com", "que", "e", "é", "ou",
    "qual", "quais", "como", "onde", "quando", "sobre", "diz", "existem", "me",
    "explique", "cai", "caem", "se", "ao", "aos", "sao", "ser", "pelo", "pela",
}
# Grupos de equivalência: qualquer variante satisfaz o grupo.
SYNONYMS = {
    "poo": ["oop", "orientacao a objetos"],
    "rnf": ["requisito nao funcional", "requisitos nao funcionais"],
    "heranca": ["inheritance"],
    "composicao": ["composition"],
}


def build_groups(raw):
    big_o = re.search(r"\bO\(", raw) is not None
    tokens = re.findall(r"[\w+#]+", fold(raw.lower()))
    kept = [t for t in tokens if t not in STOPWORDS or (t == "o" and big_o)] or tokens
    groups = []
    for t in dict.fromkeys(kept):
        variants = [t] + SYNONYMS.get(t, [])
        # Cada variante vira frase entre aspas: operadores (NOT, NEAR, AND) viram texto.
        groups.append("(" + " OR ".join('"' + v.replace('"', "") + '"' for v in variants) + ")")
    return groups


_FROM = """
FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid JOIN sources s ON s.path = c.source
WHERE chunks_fts MATCH ? AND s.stale = 0
"""
SQL = f"""
SELECT c.ref, c.cite, snippet(chunks_fts, 2, '', '', '…', 24), s.doc_type, {BM25} AS rank, c.source, c.page
{_FROM} AND s.doc_type = ? ORDER BY rank LIMIT ?
"""

_PAGE_CITE = re.compile(r" p\.\d+(?: \(impressa \d+\))?$")
_PRINTED = re.compile(r"\(impressa (\d+)\)")


def book_section(con, match, row):
    """Expande a página de livro sugerida para o trecho contínuo de páginas com os mesmos termos.

    Uma página isolada costuma ser o fim ou uma menção de passagem; o aluno precisa do início
    da seção. Devolve (ref da 1ª página, citação "arquivo p.A–B (impressa a–b)"). O intervalo
    é uma inferência pelos termos em comum, não a seção declarada pelo livro.
    """
    ref, cite, source, page = row[0], row[1], row[5], row[6]
    rows = con.execute(f"SELECT c.page, c.ref, c.cite {_FROM} AND c.source = ?", (match, source)).fetchall()
    by_page = {int(p): (r, c) for p, r, c in rows}
    start = end = int(page)
    while any(start - d in by_page for d in range(1, SECTION_GAP + 2)):
        start = max(start - d for d in range(1, SECTION_GAP + 2) if start - d in by_page)
    while any(end + d in by_page for d in range(1, SECTION_GAP + 2)):
        end = min(end + d for d in range(1, SECTION_GAP + 2) if end + d in by_page)
    if start == end:
        return ref, cite
    first_ref, first_cite = by_page[start]
    _, last_cite = by_page[end]
    base = _PAGE_CITE.sub("", first_cite)
    a, b = _PRINTED.search(first_cite), _PRINTED.search(last_cite)
    printed = f" (impressa {a.group(1)}–{b.group(1)})" if a and b else ""
    return first_ref, f"{base} p.{start}–{end}{printed}"


# O envelope vazio mais longo ("false" > "true"): piso de qualquer orçamento.
EMPTY_RESPONSE = _dumps({"r": [], "truncated": False})


def compact(rows, max_tokens, see_also=()):
    """Serializa [(ref, cite, text)] no formato do contrato, cortando até caber no orçamento.

    `see_also` são [(ref, cite)] sugeridos sem texto (ex.: livro que aprofunda o tema);
    só entram na resposta se existirem, e são os primeiros a sair se o orçamento apertar.
    """
    resp = {"r": [{"ref": r, "cite": c, "text": t} for r, c, t in rows]}
    if see_also:
        resp["ver_tambem"] = [{"ref": r, "cite": c} for r, c in see_also]
    resp["truncated"] = False
    while not _fits(resp, max_tokens) and (resp["r"] or "ver_tambem" in resp):
        resp["truncated"] = True
        if "ver_tambem" in resp:
            del resp["ver_tambem"]
            continue
        last = resp["r"][-1]
        if len(last["text"]) > 40:
            last["text"] = last["text"][: len(last["text"]) // 2] + "…"
        else:
            resp["r"].pop()
    return _dumps(resp)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def clamp_args(top_k, max_tokens):
    """Valida e limita os argumentos. Lança ValueError se inválidos."""
    if not _is_int(top_k) or not _is_int(max_tokens):
        raise ValueError("top_k e max_tokens devem ser inteiros")
    if top_k < 1 or max_tokens < 1:
        raise ValueError("top_k e max_tokens devem ser positivos")
    # O envelope vazio é o mínimo possível: um orçamento menor ainda devolve só ele.
    return min(top_k, MAX_TOP_K), max(min(max_tokens, SEARCH_MAX_TOKENS), est_tokens(EMPTY_RESPONSE))


def search(con, raw, top_k=3, max_tokens=SEARCH_MAX_TOKENS):
    """Devolve (resposta compacta serializada dentro do orçamento, estratégia).

    Material da disciplina vem antes de livros. Se o melhor resultado de livro ranquear
    acima do melhor material, ele é sugerido em `ver_tambem` (só citação, sem texto), para o
    agente oferecer ao aluno. Sem material correspondente, os livros viram a resposta.
    """
    if not isinstance(raw, str):
        raise ValueError("a consulta deve ser texto")
    top_k, max_tokens = clamp_args(top_k, max_tokens)
    groups = build_groups(raw)
    if not groups:
        return compact([], max_tokens), "vazio"

    def ranked(doc_type):
        """Candidatos (passo, linha) de um tipo: AND primeiro, OR só completa.

        Cada tipo é buscado separadamente para que páginas de livro, numerosas e cheias de
        termos comuns, não ocupem as vagas do material da disciplina.
        """
        cands = [(0, r) for r in con.execute(SQL, (" AND ".join(groups), doc_type, top_k))]
        if len(cands) < top_k and len(groups) > 1:
            seen = {r[0] for _, r in cands}
            extra = con.execute(SQL, (" OR ".join(groups), doc_type, top_k + len(seen)))
            cands += [(1, r) for r in extra if r[0] not in seen][: top_k - len(cands)]
        return cands

    material, books = ranked("material"), ranked("livro")
    passes = {p for p, _ in material + books}
    strategy = "AND" if passes == {0} else ("OR" if passes == {1} else "AND+OR")
    see_also = []
    if material:
        main = material[:top_k]
        if books:
            book_pass, book = books[0]
            material_pass, top = main[0]
            # Só sugere livro que contém TODOS os termos (passo AND) e ranqueia acima do material.
            if book_pass == 0 and (book_pass, book[4]) < (material_pass, top[4]):  # bm25: menor é melhor
                see_also = [book_section(con, " AND ".join(groups), book)]
    else:
        main = books[:top_k]
    return compact([r[:3] for _, r in main], max_tokens, see_also), strategy


# ---------------------------------------------------------------------------
# outline
# ---------------------------------------------------------------------------

def resolve_source(con, source):
    """Caminho relativo exato, ou nome de arquivo se for único. Retorna (caminho, erro)."""
    if con.execute("SELECT 1 FROM sources WHERE path = ?", (source,)).fetchone():
        return source, None
    matches = [p for (p,) in con.execute("SELECT path FROM sources") if p.rsplit("/", 1)[-1] == source]
    if len(matches) == 1:
        return matches[0], None
    if matches:
        return None, f"nome ambíguo; use o caminho: {', '.join(matches[:5])}"
    return None, "fonte desconhecida; use outline() sem argumento para ver os caminhos"


def outline(con, source=None, cursor=0, max_tokens=None, extra=None):
    """Sem `source`: fontes com caminho, tipo, páginas e status (omitido quando `ok`). Com
    `source`: um item por página/slide/seção com `ref` (aceito por read), citação e título.

    Paginado por `cursor` (índice do próximo item); `next` aparece quando há mais. Cada
    página da resposta traz pelo menos um item, então seguir `next` sempre avança. A lista
    de fontes tem teto próprio, maior: paginá-la fez o agente sair das ferramentas para
    entender o `next` (teste no Antigravity, Fase 1).
    `extra` (ex.: aviso de índice desatualizado) entra no topo da resposta.
    """
    if not _is_int(cursor) or cursor < 0:
        raise ValueError("cursor deve ser inteiro não negativo")
    head = dict(extra or {})
    if source is None:
        max_tokens = max_tokens or OUTLINE_SOURCES_MAX_TOKENS
        items = []
        for path, doc_type, status, stale, report in con.execute(
                "SELECT path, doc_type, status, stale, report FROM sources ORDER BY path"):
            item = {"source": path, "tipo": doc_type, "pags": json.loads(report).get("pages", 0)}
            status = "desatualizado" if stale else status
            if status != "ok":
                item["status"] = status
            items.append(item)
    else:
        path, err = resolve_source(con, source)
        if err:
            return error("FONTE_DESCONHECIDA", err)
        max_tokens = max_tokens or OUTLINE_MAX_TOKENS
        head["source"] = path
        items = [{"ref": r, "cite": c, "titulo": h[:60]} for r, c, h in con.execute(
            "SELECT ref, cite, heading FROM chunks WHERE source = ? ORDER BY seq", (path,))]
    if cursor > len(items):
        raise ValueError("cursor além do fim da lista")
    page, end = [], cursor
    for item in items[cursor:]:
        trial = {**head, "itens": page + [item], "next": end + 1}
        if page and not _fits(trial, max_tokens):
            break
        page, end = page + [item], end + 1
    resp = {**head, "itens": page}
    if end < len(items):
        resp["next"] = end
    return _dumps(resp)


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------

_CHUNK = """
SELECT c.id, c.source, c.seq, c.ref, c.cite, c.content
FROM chunks c JOIN sources s ON s.path = c.source WHERE s.stale = 0 AND
"""


def _validate_read(refs, vizinhos, offset):
    if isinstance(refs, str):
        refs = [refs]
    if not isinstance(refs, list) or not refs:
        raise ValueError("refs deve ser uma lista não vazia de refs")
    if len(refs) > READ_MAX_REFS:
        raise ValueError(f"no máximo {READ_MAX_REFS} refs por chamada")
    if not all(isinstance(r, str) and r for r in refs):
        raise ValueError("cada ref deve ser texto")
    if not _is_int(vizinhos) or vizinhos not in (0, 1):
        raise ValueError("vizinhos deve ser 0 ou 1")
    if not _is_int(offset) or offset < 0:
        raise ValueError("offset deve ser inteiro não negativo")
    if offset and len(refs) != 1:
        raise ValueError("offset só vale para um único ref (continuação de um trecho)")
    return list(dict.fromkeys(refs))


def _lookup(con, ref):
    row = con.execute(_CHUNK + " c.ref = ?", (ref,)).fetchone()
    if row:
        return row, None
    prefix = ref_prefix(ref)
    if "@" in ref and con.execute("SELECT 1 FROM chunks WHERE ref LIKE ? || '@%'", (prefix,)).fetchone():
        return None, "STALE_REFERENCE"
    return None, "REF_DESCONHECIDO"


class QuestionBudget:
    """Freia o agente dentro de uma pergunta.

    Sem isso ele varre o documento inteiro de 3 em 3 páginas (v3: ~50 páginas da ES_Aula 06)
    ou insiste em buscar o que não existe (v4: 34 chamadas no MVC, lista de fontes 4 vezes).
    - Páginas: passadas `per_doc` de um documento, só lê páginas que um search trouxe ou
      que já leu (continuação com offset).
    - Chamadas: a partir de `calls` chamadas, toda resposta traz um aviso para responder.
    - Lista de fontes: repetida na mesma pergunta, volta só uma nota.
    Uma pausa de `idle` segundos começa outra pergunta.
    """

    def __init__(self, per_doc=12, calls=15, idle=90, clock=time.monotonic):
        self.per_doc, self.max_calls, self.idle, self.clock = per_doc, calls, idle, clock
        self.last = None
        self._reset()

    def _reset(self):
        self.pages, self.searched = {}, set()
        self.calls, self.listed = 0, False

    def tick(self):
        """Uma chamada de ferramenta; devolve o aviso de excesso, se houver."""
        now = self.clock()
        if self.last is not None and now - self.last > self.idle:
            self._reset()
        self.last = now
        self.calls += 1
        if self.calls >= self.max_calls:
            return (f"{self.calls} chamadas nesta pergunta: pare de buscar e responda com o que "
                    "encontrou, dizendo o que não está nos materiais")
        return None

    def list_sources(self):
        """True na primeira vez que a lista de fontes é pedida nesta pergunta."""
        first, self.listed = not self.listed, True
        return first

    def saw_search(self, payload):
        self.searched.update(r["ref"] for r in json.loads(payload).get("r", []))

    def check(self, con, refs):
        """None se pode ler; senão a mensagem de recusa."""
        if isinstance(refs, str):
            refs = [refs]
        new = {}
        for ref in refs if isinstance(refs, list) else []:
            row = con.execute(_CHUNK + " c.ref = ?", (ref,)).fetchone() if isinstance(ref, str) else None
            if row and ref not in self.searched and row[0] not in self.pages.get(row[1], set()):
                new.setdefault(row[1], set()).add(row[0])
        for source, ids in new.items():
            if len(self.pages.get(source, set()) | ids) > self.per_doc:
                return (f"já foram lidas {len(self.pages.get(source, set()))} páginas de {source} nesta pergunta; "
                        "não percorra o documento. Use search com palavras-chave mais específicas "
                        "(páginas que o search trouxer podem ser lidas) ou responda com o que encontrou.")
        return None

    def record(self, con, payload):
        for item in json.loads(payload).get("r", []):
            row = con.execute(_CHUNK + " c.ref = ?", (item["ref"],)).fetchone()
            if row:
                self.pages.setdefault(row[1], set()).add(row[0])


def read(con, refs, vizinhos=0, offset=0, max_tokens=READ_MAX_TOKENS):
    """Texto completo de até 3 trechos (e, com vizinhos=1, dos trechos anterior e seguinte).

    O teto vale para a resposta inteira. Trecho cortado traz `continua` (offset para pedir o
    resto com read([ref], offset=...)); trechos que não couberam vão para `pendentes`.
    """
    refs = _validate_read(refs, vizinhos, offset)
    wanted, errors = [], []
    for ref in refs:
        row, err = _lookup(con, ref)
        if err:
            errors.append({"ref": ref, "erro": err})
            continue
        group = [row]
        if vizinhos:
            near = {n[2]: n for n in con.execute(_CHUNK + " c.source = ? AND c.seq IN (?, ?)",
                                                 (row[1], row[2] - 1, row[2] + 1))}
            group = [near.get(row[2] - 1), row, near.get(row[2] + 1)]
        wanted += [r for r in group if r]
    items = list({r[0]: r for r in wanted}.values())  # sem páginas repetidas, na ordem pedida

    base = {"r": []}
    if errors:
        base["erros"] = errors
        base["dica"] = "STALE_REFERENCE: o arquivo mudou, busque de novo. REF_DESCONHECIDO: use um ref de search/outline."

    def build(r, pending):
        return {**base, "r": r, **({"pendentes": pending} if pending else {})}

    done = []
    for i, (_, _, _, ref, cite, content) in enumerate(items):
        rest = [r[3] for r in items[i + 1:]]
        start = offset if i == 0 else 0
        text = content[start:]
        full = {"ref": ref, "cite": cite, "text": text}
        if _fits(build(done + [full], rest), max_tokens):
            done.append(full)
            continue
        # Não coube inteiro: corta o maior prefixo que cabe e indica onde continuar.
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            part = {"ref": ref, "cite": cite, "text": text[:mid], "continua": start + mid}
            if _fits(build(done + [part], rest), max_tokens):
                lo = mid
            else:
                hi = mid - 1
        if lo:
            done.append({"ref": ref, "cite": cite, "text": text[:lo], "continua": start + lo})
            return _dumps(build(done, rest))
        return _dumps(build(done, [ref] + rest))
    return _dumps(build(done, []))
