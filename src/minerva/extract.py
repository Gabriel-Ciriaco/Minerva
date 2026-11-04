"""
Extração: pypdf por página, python-pptx por slide, Markdown por seção ##.

Vem do protótipo da Fase 0 do Minerva: limpeza de cabeçalho/rodapé repetido,
página impressa inferida por deslocamento e estado de cada arquivo. Nunca imprime texto.
"""
import logging
import re
import time
import unicodedata
from importlib.metadata import version

import pypdf
from pptx import Presentation

# Mudar sempre que a extração ou o chunking mudarem: invalida o índice e os refs.
PIPELINE_VERSION = "p5"
TOKENIZER = "unicode61 remove_diacritics 2 tokenchars '_+#'"

# pypdf emite avisos sobre a estrutura de PDFs. Contamos em vez de imprimir.
pdf_warnings = []
logging.getLogger("pypdf").addHandler(
    type("H", (logging.Handler,), {"emit": lambda self, r: pdf_warnings.append(r.getMessage())})()
)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}

# Arquivos do agente/cliente que podem estar na pasta do workspace, mas não são fontes.
EXCLUDED_NAMES = {"agents.md", "gemini.md", "claude.md", "mcp_config.json", "memory.md", "memoria.md",
                  "minerva.yaml"}


def is_candidate(rel_parts, name):
    if any(part.startswith(".") for part in rel_parts):  # .agents/, .git/, .minerva/ ...
        return False
    return name.lower() not in EXCLUDED_NAMES


# Padrão até haver configuração no minerva.yaml: documento longo é livro de referência;
# o resto (slides, resumo, ementa) é material da disciplina e tem prioridade na busca.
BOOK_MIN_PAGES = 200


def infer_doc_type(n_units):
    return "livro" if n_units >= BOOK_MIN_PAGES else "material"


# Cabeçalho/rodapé: só linhas nas bordas da página, repetidas em boa parte do documento.
EDGE_TOP, EDGE_BOTTOM = 2, 3
BOILERPLATE_MIN_PAGES = 3
BOILERPLATE_MIN_SHARE = 0.5
BOILERPLATE_MIN_DOC_PAGES = 4

# Página impressa: muitos livros numeram a partir do 1º capítulo, e a página física do PDF
# fica deslocada (capa, sumário). Só usamos o deslocamento se ele for consistente. É uma
# inferência: pode falhar em prefácio, apêndice e paginação reiniciada.
PRINTED_MIN_SHARE = 0.5
_EDGE_NUMBER = re.compile(r"(?:^|\s)(\d{1,4})(?:\s|$)")


def fold(s):
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")


def printed_offset(units):
    """Deslocamento (física - impressa) dominante, ou 0 se não houver um padrão confiável."""
    counts = {}
    for u in units:
        lines = [l.strip() for l in u["content"].splitlines() if l.strip()]
        offsets = {u["page"] - int(n) for l in lines[:2] + lines[-2:] for n in _EDGE_NUMBER.findall(l)}
        for d in offsets:
            if 0 < d < 100:
                counts[d] = counts.get(d, 0) + 1
    if not counts:
        return 0
    offset, n = max(counts.items(), key=lambda kv: kv[1])
    return offset if n >= PRINTED_MIN_SHARE * len(units) else 0


def _norm_line(line):
    # Números variam entre páginas (data, nº do slide); o resto da linha identifica o rodapé.
    return re.sub(r"\d+", "#", fold(line.strip().lower()))


def _edges(lines):
    idx = range(len(lines))
    return set(idx[:EDGE_TOP]) | set(idx[-EDGE_BOTTOM:])


def _first_line(text, limit=80):
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:limit]
    return ""


def strip_boilerplate(units):
    """Remove cabeçalhos e rodapés repetidos do conteúdo das páginas. Retorna linhas removidas.

    Uma linha só sai se estiver na borda da página e se repetir, na borda, em pelo menos
    BOILERPLATE_MIN_PAGES páginas e BOILERPLATE_MIN_SHARE do documento. Linhas repetidas no
    meio da página (definições, fórmulas) ficam. A numeração física das páginas não muda.
    """
    pages = [[l for l in u["content"].splitlines() if l.strip()] for u in units]
    if len(pages) < BOILERPLATE_MIN_DOC_PAGES:
        return 0
    counts = {}
    for lines in pages:
        for key in {_norm_line(lines[i]) for i in _edges(lines)}:
            counts[key] = counts.get(key, 0) + 1
    threshold = max(BOILERPLATE_MIN_PAGES, BOILERPLATE_MIN_SHARE * len(pages))
    boiler = {k for k, n in counts.items() if n >= threshold}
    removed = 0
    for u, lines in zip(units, pages):
        edges = _edges(lines)
        kept = [l for i, l in enumerate(lines) if not (i in edges and _norm_line(l) in boiler)]
        removed += len(lines) - len(kept)
        if len(kept) != len(lines):
            u["content"] = "\n".join(kept)
            u["heading"] = _first_line(u["content"])
    return removed


def pipeline_config():
    """Tudo que, se mudar, torna a extração ou o índice anteriores inválidos."""
    return {
        "pipeline": PIPELINE_VERSION,
        "tokenizer": TOKENIZER,
        "pypdf": version("pypdf"),
        "python-pptx": version("python-pptx"),
    }


def extract_pdf(path, name):
    reader = pypdf.PdfReader(path)
    for i, page in enumerate(reader.pages, 1):
        try:
            text, error = (page.extract_text() or "").strip(), None
        except Exception as exc:  # noqa: BLE001 - registrada, não confundida com página vazia
            text, error = "", type(exc).__name__
        yield {"cite": f"{name} p.{i}", "page": i, "title": path.stem,
               "heading": _first_line(text), "content": text, "error": error}


def extract_pptx(path, name):
    for i, slide in enumerate(Presentation(path).slides, 1):
        title_shape = slide.shapes.title
        title = title_shape.text.strip() if title_shape is not None else ""
        parts = [
            p.text.strip()
            for shape in slide.shapes
            if shape.has_text_frame and shape != title_shape
            for p in shape.text_frame.paragraphs
            if p.text.strip()
        ]
        yield {"cite": f"{name} slide {i}", "page": i, "title": path.stem,
               "heading": title, "content": "\n".join(parts), "error": None}


def extract_md(path, name):
    lines = path.read_text(encoding="utf-8").splitlines()
    doc_title, heading, start, buf = path.stem, "", 1, []

    def flush(end):
        if buf and any(l.strip() for l in buf):
            return {"cite": f"{name} §{heading} (l.{start}-{end})", "page": start, "title": doc_title,
                    "heading": heading, "content": "\n".join(buf).strip(), "error": None}

    for n, line in enumerate(lines, 1):
        if line.startswith("# "):
            doc_title = line[2:].strip()
        elif line.startswith("## "):
            chunk = flush(n - 1)
            if chunk:
                yield chunk
            heading, start, buf = line[3:].strip(), n, []
        else:
            buf.append(line)
    chunk = flush(len(lines))
    if chunk:
        yield chunk


EXTRACTORS = {".pdf": extract_pdf, ".pptx": extract_pptx, ".md": extract_md}


def is_supported(name):
    """Formato que vira fonte. Imagens entram (status `imagem_sem_ocr`) para o aluno saber delas."""
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in EXTRACTORS or ext in IMAGE_EXT


def _status(units):
    errors = sum(1 for u in units if u["error"])
    empty = sum(1 for u in units if not u["content"] and not u["error"])
    if errors:
        return ("erro" if errors == len(units) else "erro_parcial"), empty, errors
    if units and empty == len(units):
        return "sem_texto", empty, errors   # nenhum texto extraído e nenhuma exceção
    return ("parcial" if empty else "ok"), empty, errors


def extract_file(path):
    """Extrai um arquivo. Retorna (unidades com texto, relatório só com números).

    O relatório tem `status`, `pages`, `empty`, `errors`, `boilerplate_removed`,
    `printed_offset`, `chars` e `secs`. Não lança: falha vira status `erro: <Exceção>`.
    """
    ext = path.suffix.lower()
    row = {"pages": 0, "empty": 0, "errors": 0, "chars": 0, "boilerplate_removed": 0,
           "printed_offset": 0, "secs": 0.0}
    if ext in IMAGE_EXT or ext not in EXTRACTORS:
        row["status"] = "imagem_sem_ocr" if ext in IMAGE_EXT else "nao_suportado"
        return [], row
    t0 = time.perf_counter()
    try:
        units = list(EXTRACTORS[ext](path, path.name))
    except Exception as exc:  # noqa: BLE001 - um arquivo ruim não derruba a ingestão
        row.update(status=f"erro: {type(exc).__name__}", secs=round(time.perf_counter() - t0, 2))
        return [], row
    offset = printed_offset(units) if ext == ".pdf" else 0
    if offset:
        for u in units:
            if u["page"] > offset:
                u["cite"] += f" (impressa {u['page'] - offset})"
    removed = strip_boilerplate(units)
    status, empty, errors = _status(units)
    row.update(status=status, pages=len(units), empty=empty, errors=errors, boilerplate_removed=removed,
               printed_offset=offset, chars=sum(len(u["content"]) for u in units),
               secs=round(time.perf_counter() - t0, 2))
    return [u for u in units if u["content"]], row
