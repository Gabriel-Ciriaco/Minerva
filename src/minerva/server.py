"""
Servidor MCP (stdio, somente leitura): search, outline e read sobre o índice do workspace.

Não extrai nada: cada chamada abre o banco somente leitura e vê a última ingestão
publicada. Se a pasta mudou desde então, outline() avisa para rodar `minerva ingest`.
Logs vão para stderr; stdout é reservado ao protocolo.
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from mcp.server.mcpserver import MCPServer  # mcp 2.x (antes FastMCP)

from minerva import __version__, index
from minerva import search as engine


def build(workspace, log=False):
    workspace = Path(workspace).resolve()
    log_path = None
    if log:
        log_path = workspace / index.STATE_DIR / "logs" / f"{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)

    def call(tool, args, fn):
        t0 = time.perf_counter()
        warning = budget.tick()
        try:
            con = index.connect_ro(workspace)
        except index.IndexUnavailable as exc:
            payload = engine.error("INDICE_INDISPONIVEL", str(exc))
        else:
            try:
                payload = fn(con)
            except ValueError as exc:
                payload = engine.error("ARGUMENTO_INVALIDO", str(exc))
            finally:
                con.close()
        if warning:
            payload = engine._dumps({**json.loads(payload), "limite": warning})
        if log_path:
            # Registro sem o texto devolvido: ferramenta, argumentos, tamanho e tempo.
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "versao": __version__,
                                    "tool": tool, "args": args, "tokens": engine.est_tokens(payload),
                                    "secs": round(time.perf_counter() - t0, 3)}, ensure_ascii=False) + "\n")
        return payload

    budget = engine.QuestionBudget()
    mcp = MCPServer("minerva")

    @mcp.tool()
    def search(query: str, top_k: int = 3) -> str:
        """Busca nos materiais da disciplina. Use palavras-chave, não a pergunta inteira.

        Devolve até top_k trechos curtos com `ref` e citação (arquivo e página). Material da
        disciplina vem primeiro; `ver_tambem` sugere um livro que pode aprofundar o tema.
        """
        def run(con):
            payload = engine.search(con, query, top_k=top_k)[0]
            budget.saw_search(payload)
            return payload
        return call("search", {"query": query, "top_k": top_k}, run)

    @mcp.tool()
    def outline(source: str = "", cursor: int = 0) -> str:
        """Navega pelas fontes sem gastar tokens com conteúdo.

        Sem `source`: lista as fontes (caminho, tipo material/livro, páginas e status;
        `sem_texto` = nenhum texto extraído, a busca não alcança). Com `source` (caminho ou nome
        do arquivo): um item por página com `ref` para usar direto em read. Passe `next` como
        `cursor` para continuar.
        """
        def run(con):
            extra = {}
            if not source:
                pending = index.pending_changes(con, workspace)
                if pending:
                    extra["aviso"] = (f"{len(pending)} arquivo(s) mudaram desde a última indexação; "
                                      "peça ao aluno para rodar `minerva ingest`")
                if not cursor and not budget.list_sources():
                    return engine._dumps({"nota": "lista de fontes já enviada nesta pergunta; use a anterior", **extra})
            return engine.outline(con, source or None, cursor, extra=extra)
        return call("outline", {"source": source, "cursor": cursor}, run)

    @mcp.tool()
    def read(refs: list[str], vizinhos: int = 0, offset: int = 0) -> str:
        """Lê o texto completo de até 3 trechos pelos `ref` de search ou outline.

        vizinhos=1 inclui também a página anterior e a seguinte de cada ref. A resposta tem
        teto de ~1500 tokens no total: trecho cortado traz `continua` (chame read([ref],
        offset=continua) para o resto) e o que não coube vem em `pendentes`. Não percorra um
        documento: passadas 12 páginas dele na mesma pergunta, só lê páginas trazidas por search.
        """
        def run(con):
            refused = budget.check(con, refs)
            if refused:
                return engine.error("LEITURA_EXCESSIVA", refused)
            payload = engine.read(con, refs, vizinhos, offset)
            budget.record(con, payload)
            return payload
        return call("read", {"refs": refs, "vizinhos": vizinhos, "offset": offset}, run)

    return mcp


def serve(workspace, log=False):
    mcp = build(workspace, log)
    print(f"minerva {__version__}: servindo {Path(workspace).resolve()}", file=sys.stderr)
    mcp.run()
