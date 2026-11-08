"""
Índice persistente e incremental em <workspace>/.minerva/index.db.

Por arquivo: hash sempre (mtime/tamanho não pulam a verificação), extração FORA da
transação e publicação numa transação curta. Uma falha no meio deixa cada arquivo na versão
anterior ou na nova, nunca misturadas. Leitores (o servidor) abrem o banco somente leitura,
em WAL, e enxergam cada arquivo publicado assim que a transação dele termina.
"""
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

from minerva import config as config_mod
from minerva.extract import (TOKENIZER, extract_file, infer_doc_type, is_candidate, is_supported,
                             pipeline_config)

SCHEMA_VERSION = "1"
STATE_DIR = ".minerva"
DB_NAME = "index.db"
LOCK_NAME = "ingest.lock"

SCHEMA = f"""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources (
    path TEXT PRIMARY KEY,          -- relativo ao workspace, posix
    sha256 TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    status TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    stale INTEGER NOT NULL DEFAULT 0,  -- 1: reextração falhou; versão antiga fora da busca
    report TEXT NOT NULL            -- números da extração, nunca texto
);
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL REFERENCES sources(path),
    seq INTEGER NOT NULL,
    ref TEXT NOT NULL UNIQUE,
    page INTEGER NOT NULL,
    cite TEXT NOT NULL,
    title TEXT NOT NULL,
    heading TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE INDEX chunks_source ON chunks(source, seq);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    title, heading, content, content='chunks', content_rowid='id', tokenize="{TOKENIZER}"
);
CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, title, heading, content) VALUES (new.id, new.title, new.heading, new.content);
END;
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, title, heading, content)
    VALUES ('delete', old.id, old.title, old.heading, old.content);
END;
"""


class IndexUnavailable(RuntimeError):
    """Índice ausente, incompatível ou ocupado. A mensagem diz o que fazer."""


def db_path(workspace):
    return Path(workspace) / STATE_DIR / DB_NAME


def make_ref(rel, seq, sha):
    """Ref curto e versionado: caminho, posição do trecho, hash do arquivo e pipeline."""
    from minerva.extract import PIPELINE_VERSION
    return f"{hashlib.md5(rel.encode()).hexdigest()[:6]}{seq}@{sha[:6]}{PIPELINE_VERSION}"


def ref_prefix(ref):
    """Parte do ref que identifica fonte e posição, sem a versão do conteúdo."""
    return ref.split("@", 1)[0]


# ---------------------------------------------------------------------------
# Abertura
# ---------------------------------------------------------------------------

def connect_ro(workspace):
    """Conexão somente leitura para buscas. Uma por chamada: sempre vê a última publicação."""
    path = db_path(workspace)
    if not path.exists():
        raise IndexUnavailable("índice não encontrado; rode `minerva ingest` na pasta da disciplina")
    con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, check_same_thread=False)
    row = con.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
    if not row or row[0] != SCHEMA_VERSION:
        con.close()
        raise IndexUnavailable("índice de outra versão do Minerva; rode `minerva ingest --rebuild`")
    return con


def _open_rw(workspace, rebuild=False):
    path = db_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not rebuild:
        con = sqlite3.connect(path)
        row = con.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone() \
            if con.execute("SELECT 1 FROM sqlite_master WHERE name = 'meta'").fetchone() else None
        if row and row[0] == SCHEMA_VERSION:
            return con
        con.close()
        raise IndexUnavailable("índice de outra versão do Minerva; rode `minerva ingest --rebuild`")
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    con.execute("INSERT INTO meta VALUES ('schema', ?)", (SCHEMA_VERSION,))
    con.commit()
    return con


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

def _pid_alive(pid):
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def ingest_lock(workspace):
    """Um `ingest` por vez. Lock de processo morto é retomado; de processo vivo, recusado."""
    path = Path(workspace) / STATE_DIR / LOCK_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                pid = int(path.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid and _pid_alive(pid):
                raise IndexUnavailable(f"outra ingestão em andamento (processo {pid})") from None
            path.unlink(missing_ok=True)  # órfão
    else:
        raise IndexUnavailable(f"não foi possível criar {path}")
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Varredura
# ---------------------------------------------------------------------------

def scan(workspace, cfg):
    """Fontes do workspace: ({caminho relativo posix: Path}, fora do workspace, formato não suportado).

    Lança OSError se alguma pasta não puder ser lida: uma varredura incompleta nunca pode
    ser tratada como exclusão dos arquivos que ela não viu.
    """
    root = Path(workspace).resolve()
    found, skipped, unsupported = {}, [], []

    def fail(exc):
        raise exc

    def consider(rel_parts, path):
        rel = "/".join(rel_parts)
        if not is_candidate(rel_parts, rel_parts[-1]) or cfg.ignored(rel):
            return
        if not is_supported(rel_parts[-1]):
            unsupported.append(rel)
            return
        if not path.resolve().is_relative_to(root):  # symlink/junction para fora do workspace
            skipped.append(rel)
            return
        found[rel] = path

    # Sem `fontes`, o workspace inteiro; com `fontes`, só as pastas e arquivos listados.
    for start in cfg.fontes or [""]:
        start_path = root / start.rstrip("/") if start else root
        if not start.endswith("/") and start:
            consider(tuple(start.split("/")), start_path)
            continue
        if not start_path.resolve().is_relative_to(root):
            skipped.append(start)
            continue
        for dirpath, dirnames, filenames in os.walk(start_path, onerror=fail):
            rel_dir = Path(dirpath).relative_to(root).parts
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                consider(rel_dir + (name,), Path(dirpath) / name)
    return found, skipped, unsupported


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Ingestão
# ---------------------------------------------------------------------------

def _signature(cfg):
    return json.dumps({**pipeline_config(), "config": cfg.signature()}, sort_keys=True)


def _publish(con, rel, st, sha, units, row, doc_type):
    with con:  # transação curta: só escrita, a extração já terminou
        con.execute("DELETE FROM chunks WHERE source = ?", (rel,))
        con.execute("INSERT OR REPLACE INTO sources VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                    (rel, sha, st.st_mtime, st.st_size, row["status"], doc_type,
                     json.dumps(row, ensure_ascii=False)))
        con.executemany(
            "INSERT INTO chunks (source, seq, ref, page, cite, title, heading, content) VALUES (?,?,?,?,?,?,?,?)",
            [(rel, seq, make_ref(rel, seq, sha), u["page"], u["cite"], u["title"], u["heading"], u["content"])
             for seq, u in enumerate(units, 1)])


def ingest(workspace, rebuild=False, progress=None):
    """Indexa o workspace. Retorna lista de linhas por arquivo (`file`, `acao`, números).

    `acao`: novo, alterado, igual, removido, falhou (versão antiga mantida fora da busca)
    ou ignorado (fora do workspace).
    """
    workspace = Path(workspace).resolve()
    cfg = config_mod.load(workspace)
    with ingest_lock(workspace):
        con = _open_rw(workspace, rebuild)
        try:
            return _ingest(con, workspace, cfg, progress or (lambda rel: None))
        finally:
            con.close()


def _ingest(con, workspace, cfg, progress):
    signature = _signature(cfg)
    old_sig = con.execute("SELECT value FROM meta WHERE key = 'signature'").fetchone()
    # Pipeline ou configuração mudaram: tudo é reextraído, arquivo por arquivo, sem apagar
    # antes. A assinatura nova só é gravada no fim; uma ingestão interrompida recomeça assim.
    force = bool(old_sig) and old_sig[0] != signature

    files, skipped, unsupported = scan(workspace, cfg)  # OSError aborta antes de qualquer remoção
    known = {r[0]: r for r in con.execute("SELECT path, sha256, stale FROM sources")}
    out = [{"file": rel, "acao": "ignorado", "motivo": "fora do workspace"} for rel in skipped]
    out += [{"file": rel, "acao": "ignorado", "motivo": "formato não suportado"} for rel in unsupported]

    for rel, path in files.items():
        progress(rel)
        try:
            st = path.stat()
            sha = _sha256(path)
        except OSError as exc:
            out.append(_failed(con, rel, known, f"erro: {type(exc).__name__}"))
            continue
        prev = known.get(rel)
        if prev and prev[1] == sha and not prev[2] and not force:
            with con:
                con.execute("UPDATE sources SET mtime = ?, size = ? WHERE path = ?", (st.st_mtime, st.st_size, rel))
            out.append({"file": rel, "acao": "igual", **_stored_report(con, rel)})
            continue
        units, row = extract_file(path)
        try:
            after = path.stat()
            changed = (after.st_mtime, after.st_size) != (st.st_mtime, st.st_size) or _sha256(path) != sha
        except OSError:
            changed = True
        if changed:
            out.append(_failed(con, rel, known, "alterado durante a extração; rode ingest de novo"))
            continue
        if row["status"].startswith("erro") and not units and prev:
            out.append(_failed(con, rel, known, row["status"]))
            continue
        doc_type = cfg.doc_type(rel) or infer_doc_type(row["pages"])
        row["doc_type"] = doc_type
        _publish(con, rel, st, sha, units, row, doc_type)
        out.append({"file": rel, "acao": "alterado" if prev else "novo", "trechos": len(units), **row})

    # A varredura terminou sem erro: o que ela não viu está ausente (ou foi ignorado).
    with con:
        for rel in set(known) - set(files):
            con.execute("DELETE FROM chunks WHERE source = ?", (rel,))
            con.execute("DELETE FROM sources WHERE path = ?", (rel,))
            out.append({"file": rel, "acao": "removido"})
        con.execute("INSERT OR REPLACE INTO meta VALUES ('signature', ?)", (signature,))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('disciplina', ?)", (cfg.disciplina,))
    return out


def _stored_report(con, rel):
    report, n = con.execute(
        "SELECT report, (SELECT count(*) FROM chunks WHERE source = path) FROM sources WHERE path = ?",
        (rel,)).fetchone()
    return {"trechos": n, **json.loads(report)}


def _failed(con, rel, known, reason):
    """Mantém a versão antiga (se houver) marcada como desatualizada e fora da busca."""
    with con:
        if rel in known:
            con.execute("UPDATE sources SET stale = 1 WHERE path = ?", (rel,))
    return {"file": rel, "acao": "falhou", "status": reason}


# ---------------------------------------------------------------------------
# Estado para o servidor e o doctor
# ---------------------------------------------------------------------------

def pending_changes(con, workspace):
    """Arquivos novos, alterados (por mtime/tamanho) ou removidos desde o último ingest.

    Verificação rápida, sem hash: serve só para avisar que é preciso rodar `minerva ingest`.
    """
    try:
        cfg = config_mod.load(workspace)
        files = scan(workspace, cfg)[0]
    except (OSError, config_mod.ConfigError):
        return ["(não foi possível verificar a pasta)"]
    known = {r[0]: (r[1], r[2]) for r in con.execute("SELECT path, mtime, size FROM sources")}
    changed = []
    for rel, path in files.items():
        st = path.stat()
        if known.get(rel) != (st.st_mtime, st.st_size):
            changed.append(rel)
    changed += sorted(set(known) - set(files))
    sig = con.execute("SELECT value FROM meta WHERE key = 'signature'").fetchone()
    if not sig or sig[0] != _signature(cfg):
        changed.insert(0, "(configuração ou versão do Minerva mudou)")
    return changed
