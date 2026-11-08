"""Linha de comando: init, ingest, search, outline, doctor, connect, serve."""
import argparse
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from minerva import __version__, config as config_mod, connect as connect_mod, index
from minerva import search as engine

GITIGNORE_NEW = """\
# Gerado por `minerva init`: materiais da disciplina, o índice e os logs nunca vão para o git.
# Só os arquivos listados com ! são versionados.
/*
!/.gitignore
!/minerva.yaml
"""


def _ws(args):
    return Path(args.workspace).resolve()


def _git_tracked(ws):
    if not shutil.which("git"):
        return None
    out = subprocess.run(["git", "-C", str(ws), "ls-files", "-z"], capture_output=True)
    if out.returncode != 0:
        return None
    return {p for p in out.stdout.decode("utf-8", "replace").split("\0") if p}


def cmd_init(args):
    ws = Path(args.pasta or args.workspace).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    (ws / index.STATE_DIR).mkdir(exist_ok=True)
    cfg = ws / config_mod.CONFIG_NAME
    if cfg.exists():
        print(f"mantido: {cfg}")
    else:
        cfg.write_text(config_mod.TEMPLATE, encoding="utf-8")
        print(f"criado: {cfg}")
    state, _ = connect_mod.ensure_memory(ws)
    print(f"{'criado' if state == 'escrito' else 'mantido'}: {ws / connect_mod.MEMORY_NAME}")
    gi = ws / ".gitignore"
    if not gi.exists() and not (ws / ".git").exists():
        gi.write_text(GITIGNORE_NEW, encoding="utf-8")
        print(f"criado: {gi} (ignora tudo, exceto minerva.yaml)")
    else:
        lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
        if not any(l.strip().strip("/") == index.STATE_DIR for l in lines):
            with open(gi, "a", encoding="utf-8") as f:
                f.write(("\n" if lines and lines[-1] else "") + "# Minerva: índice e logs\n/.minerva/\n")
            print(f"acrescentado /.minerva/ a {gi}; o resto foi mantido")
        print("aviso: repositório existente; confira se os materiais da disciplina não estão versionados "
              "(`minerva doctor` verifica)")
    print("próximo passo: minerva ingest")


def cmd_ingest(args):
    ws = _ws(args)
    t0 = time.perf_counter()
    try:
        rows = index.ingest(ws, rebuild=args.rebuild)
    except (index.IndexUnavailable, config_mod.ConfigError, OSError) as exc:
        sys.exit(f"erro: {exc}")
    counts, unsupported = {}, []
    for r in rows:
        if r.get("motivo") == "formato não suportado":
            unsupported.append(r["file"])
            continue
        counts[r["acao"]] = counts.get(r["acao"], 0) + 1
        if r["acao"] == "igual" and not args.verbose:
            continue
        detail = r.get("status", r.get("motivo", ""))
        if "pages" in r:
            detail += (f"  {r.get('doc_type', '-')}  {r['pages']} pág  {r.get('trechos', 0)} trechos"
                       f"  rodapé -{r.get('boilerplate_removed', 0)}")
        print(f"  {r['acao']:9} {r['file']}  {detail}")
    con = index.connect_ro(ws)
    n_src, n_chunks = con.execute("SELECT (SELECT count(*) FROM sources), (SELECT count(*) FROM chunks)").fetchone()
    issues = con.execute("SELECT count(*) FROM sources WHERE status != 'ok' OR stale = 1").fetchone()[0]
    con.close()
    print(f"{n_src} fontes, {n_chunks} trechos; " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
          + f"; {time.perf_counter() - t0:.1f} s")
    if unsupported:
        print(_unsupported_summary(unsupported))
    if issues:
        print(f"{issues} fonte(s) com status diferente de ok; veja `minerva outline` ou `minerva doctor`")


def _unsupported_summary(paths):
    """Uma linha: `41 arquivo(s) fora do índice por formato (.py ×18, .pyc ×9, ...)`."""
    by_ext = {}
    for p in paths:
        name = p.rsplit("/", 1)[-1]
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else "(sem extensão)"
        by_ext[ext] = by_ext.get(ext, 0) + 1
    top = sorted(by_ext.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = ", ".join(f"{e} ×{n}" for e, n in top[:6]) + (", ..." if len(top) > 6 else "")
    return (f"{len(paths)} arquivo(s) fora do índice por formato ({shown}); "
            "use `fontes:` no minerva.yaml para ler só os materiais")


def _with_con(args, fn):
    try:
        con = index.connect_ro(_ws(args))
    except index.IndexUnavailable as exc:
        sys.exit(f"erro: {exc}")
    try:
        print(fn(con))
    except ValueError as exc:
        sys.exit(f"erro: {exc}")
    finally:
        con.close()


def cmd_search(args):
    _with_con(args, lambda con: engine.search(con, " ".join(args.termos), top_k=args.top_k)[0])


def cmd_outline(args):
    _with_con(args, lambda con: engine.outline(con, args.fonte, args.cursor))


def cmd_read(args):
    _with_con(args, lambda con: engine.read(con, args.refs, args.vizinhos, args.offset))


def cmd_doctor(args):
    ws = _ws(args)
    problems = 0

    def report(level, msg):
        nonlocal problems
        problems += level == "ERRO"
        print(f"[{level:5}] {msg}")

    v = sys.version_info
    report("OK" if v >= (3, 11) else "ERRO", f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(a)")
        report("OK", f"SQLite {sqlite3.sqlite_version} com FTS5")
    except sqlite3.OperationalError:
        report("ERRO", "SQLite sem FTS5")
    cfg = None
    try:
        cfg = config_mod.load(ws)
        report("OK", "minerva.yaml válido ou ausente (padrões)"
               + (f"; fontes: {', '.join(cfg.fontes)}" if cfg.fontes else "; lendo o workspace inteiro"))
    except config_mod.ConfigError as exc:
        report("ERRO", str(exc))
    if cfg is not None:
        try:
            unsupported = index.scan(ws, cfg)[2]
        except OSError:
            unsupported = []
        if unsupported:
            report("AVISO", _unsupported_summary(unsupported))

    try:
        con = index.connect_ro(ws)
    except index.IndexUnavailable as exc:
        report("ERRO", str(exc))
        con = None
    if con:
        pending = index.pending_changes(con, ws)
        report("AVISO" if pending else "OK",
               f"{len(pending)} arquivo(s) mudaram desde o último ingest" if pending else "índice em dia")
        no_text = False
        for path, status, stale in con.execute(
                "SELECT path, status, stale FROM sources WHERE status != 'ok' OR stale = 1 ORDER BY path"):
            report("AVISO", f"{path}: {'desatualizado (reextração falhou)' if stale else status}")
            no_text |= status in ("sem_texto", "imagem_sem_ocr")
        if no_text:
            report("DICA", "sem_texto/imagem_sem_ocr: a busca não alcança esses arquivos; procure uma versão "
                           "digital ou aplique OCR antes (veja \"PDFs escaneados\" no README)")
        sources = [p for (p,) in con.execute("SELECT path FROM sources")]
        con.close()
        tracked = _git_tracked(ws)
        if tracked is not None:
            leaked = sorted(set(sources) & tracked)
            leaked += sorted(p for p in tracked if p.startswith(f"{index.STATE_DIR}/"))
            report("AVISO" if leaked else "OK",
                   f"{len(leaked)} fonte(s) ou arquivo(s) do índice versionados no git: {', '.join(leaked[:5])}"
                   if leaked else "nenhuma fonte versionada no git")

    mem = ws / connect_mod.MEMORY_NAME
    if mem.exists():
        size = mem.stat().st_size
        report("AVISO" if size > 2048 else "OK",
               f"{connect_mod.MEMORY_NAME}: {size / 1024:.1f} KB"
               + ("; peça ao agente para consolidar (vai em toda conversa)" if size > 2048 else ""))
    else:
        report("AVISO", f"{connect_mod.MEMORY_NAME} ausente; `minerva init` ou `connect` cria")

    connected = 0
    for name in connect_mod.CLIENTS:
        try:
            state = connect_mod.status(name, ws)
        except config_mod.ConfigError:
            state = None
        if state:
            connected += 1
            report(*state)
    ollama = cfg.ollama if cfg is not None else {}
    if ollama:
        _doctor_ollama(ollama, report)
    elif not connected:
        report("AVISO", "nenhum cliente conectado; rode `minerva connect antigravity|claude-code|codex` "
                        "ou configure o Ollama para `minerva chat`")
    sys.exit(1 if problems else 0)


def _doctor_ollama(ollama, report):
    from minerva import chat
    client = chat.Ollama(chat.resolve_host(ollama), probe_timeout=3)
    try:
        version = client.version()
        model = ollama.get("modelo")
        if model:
            chat.pick_model(client, model)
            chat.check_tools(client, model)
        report("OK", f"Ollama {version} em {client.host}" + (f"; modelo {model} com ferramentas" if model else ""))
    except chat.ChatError as exc:
        report("AVISO", f"Ollama: {exc}")


def cmd_connect(args):
    ws = _ws(args)
    try:
        if args.cliente == "outro":
            print("Entrada do servidor para a configuração MCP do seu cliente:\n")
            print(connect_mod.snippet(ws, args.log))
            print("\nRegras para o arquivo de instruções do cliente (nada foi gravado):\n")
            print(connect_mod.rules_text(ws))
            return
        results = connect_mod.connect(args.cliente, ws, force=args.force, log=args.log)
    except config_mod.ConfigError as exc:
        sys.exit(f"erro: {exc}")
    for state, msg in results:
        print(f"[{state}] {msg}")
    if any(s in ("conflito", "erro") for s, _ in results):
        sys.exit(1)
    if any(s == "escrito" for s, _ in results):
        print(connect_mod.CLIENTS[args.cliente].dica)


def cmd_chat(args):
    from minerva import chat
    try:
        chat.run(_ws(args), model=args.modelo, host=args.host, think=False if args.sem_pensar else None,
                 context=args.contexto, log=args.log)
    except (chat.ChatError, config_mod.ConfigError, index.IndexUnavailable) as exc:
        sys.exit(f"erro: {exc}")


def cmd_serve(args):
    from minerva import server
    server.serve(_ws(args), log=args.log)


def main(argv=None):
    p = argparse.ArgumentParser(prog="minerva", description="Busca citada nos materiais da disciplina.")
    p.add_argument("--version", action="version", version=f"minerva {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--workspace", "-w", default=".", help="pasta da disciplina (padrão: a atual)")
        sp.set_defaults(fn=fn)
        return sp

    sp = add("init", cmd_init, "prepara a pasta da disciplina")
    sp.add_argument("pasta", nargs="?")
    sp = add("ingest", cmd_ingest, "indexa (ou atualiza) os materiais")
    sp.add_argument("--rebuild", action="store_true", help="apaga e reconstrói o índice")
    sp.add_argument("--verbose", "-v", action="store_true", help="lista também os arquivos sem mudança")
    sp = add("search", cmd_search, "busca (mesmo JSON da ferramenta)")
    sp.add_argument("termos", nargs="+")
    sp.add_argument("--top-k", type=int, default=3)
    sp = add("outline", cmd_outline, "fontes, ou páginas de uma fonte")
    sp.add_argument("fonte", nargs="?")
    sp.add_argument("--cursor", type=int, default=0)
    sp = add("read", cmd_read, "lê trechos pelo ref")
    sp.add_argument("refs", nargs="+")
    sp.add_argument("--vizinhos", type=int, default=0)
    sp.add_argument("--offset", type=int, default=0)
    add("doctor", cmd_doctor, "verifica instalação, índice e conexão")
    sp = add("connect", cmd_connect, "conecta um cliente MCP (arquivos só dentro do workspace)")
    sp.add_argument("cliente", choices=[*connect_mod.CLIENTS, "outro"],
                    help="outro: só mostra a entrada e as regras para colar em outro cliente")
    sp.add_argument("--force", action="store_true", help="substitui a entrada minerva divergente")
    sp.add_argument("--log", action="store_true", help="servidor registra chamadas (sem texto) em .minerva/logs/")
    sp = add("chat", cmd_chat, "conversa no terminal com um modelo do Ollama")
    sp.add_argument("--modelo", "-m", help="modelo do Ollama (padrão: ollama.modelo do minerva.yaml)")
    sp.add_argument("--host", help="URL do Ollama (padrão: ollama.host, OLLAMA_HOST ou http://localhost:11434)")
    sp.add_argument("--contexto", type=int, help="janela de contexto em tokens (padrão: ollama.contexto ou 8192)")
    sp.add_argument("--sem-pensar", action="store_true", help="desliga o raciocínio de modelos como qwen3 (mais rápido)")
    sp.add_argument("--log", action="store_true", help="registra chamadas (sem texto) em .minerva/logs/")
    sp = add("serve", cmd_serve, "servidor MCP (stdio); o cliente é quem executa")
    sp.add_argument("--log", action="store_true", help="registra chamadas (sem texto) em .minerva/logs/")

    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args.fn(args)
