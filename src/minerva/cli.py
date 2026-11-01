"""Linha de comando: init, ingest, search, outline, doctor, connect, serve."""
import argparse
import json
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
    counts = {}
    for r in rows:
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
    if issues:
        print(f"{issues} fonte(s) com status diferente de ok; veja `minerva outline` ou `minerva doctor`")


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
    try:
        config_mod.load(ws)
        report("OK", "minerva.yaml válido ou ausente (padrões)")
    except config_mod.ConfigError as exc:
        report("ERRO", str(exc))

    try:
        con = index.connect_ro(ws)
    except index.IndexUnavailable as exc:
        report("ERRO", str(exc))
        con = None
    if con:
        pending = index.pending_changes(con, ws)
        report("AVISO" if pending else "OK",
               f"{len(pending)} arquivo(s) mudaram desde o último ingest" if pending else "índice em dia")
        for path, status, stale in con.execute(
                "SELECT path, status, stale FROM sources WHERE status != 'ok' OR stale = 1 ORDER BY path"):
            report("AVISO", f"{path}: {'desatualizado (reextração falhou)' if stale else status}")
        sources = [p for (p,) in con.execute("SELECT path FROM sources")]
        con.close()
        tracked = _git_tracked(ws)
        if tracked is not None:
            leaked = sorted(set(sources) & tracked)
            leaked += sorted(p for p in tracked if p.startswith(f"{index.STATE_DIR}/"))
            report("AVISO" if leaked else "OK",
                   f"{len(leaked)} fonte(s) ou arquivo(s) do índice versionados no git: {', '.join(leaked[:5])}"
                   if leaked else "nenhuma fonte versionada no git")

    cfg_path = ws / connect_mod.AGENTS_DIR / "mcp_config.json"
    if not cfg_path.exists():
        report("AVISO", "Antigravity não conectado; rode `minerva connect antigravity`")
    else:
        try:
            entry = json.loads(cfg_path.read_text(encoding="utf-8"))["mcpServers"]["minerva"]
            cmd = Path(entry["command"])
            if not cmd.exists():
                report("ERRO", f"Python do mcp_config.json não existe ({cmd}); rode `minerva connect antigravity --force`")
            elif entry not in (connect_mod.server_entry(ws), connect_mod.server_entry(ws, log=True)):
                report("AVISO", "entrada minerva difere da gerada por este ambiente; "
                                "rode `minerva connect antigravity --force` se o .venv mudou")
            else:
                report("OK", f"{cfg_path} aponta para este Python e este workspace")
        except (json.JSONDecodeError, KeyError, TypeError):
            report("ERRO", f"{cfg_path} sem entrada minerva válida")
    sys.exit(1 if problems else 0)


def cmd_connect(args):
    ws = _ws(args)
    try:
        results = connect_mod.connect_antigravity(ws, force=args.force, log=args.log)
    except config_mod.ConfigError as exc:
        sys.exit(f"erro: {exc}")
    for state, msg in results:
        print(f"[{state}] {msg}")
    if any(s in ("conflito", "erro") for s, _ in results):
        sys.exit(1)
    if any(s == "escrito" for s, _ in results):
        print("Recarregue o Antigravity (ou reabra a pasta) e confira se o servidor `minerva` aparece "
              "nas ferramentas MCP.")


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
    sp = add("connect", cmd_connect, "conecta um cliente (só no .agents do workspace)")
    sp.add_argument("cliente", choices=["antigravity"])
    sp.add_argument("--force", action="store_true", help="substitui a entrada minerva divergente")
    sp.add_argument("--log", action="store_true", help="servidor registra chamadas (sem texto) em .minerva/logs/")
    sp = add("serve", cmd_serve, "servidor MCP (stdio); o cliente é quem executa")
    sp.add_argument("--log", action="store_true", help="registra chamadas (sem texto) em .minerva/logs/")

    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args.fn(args)
