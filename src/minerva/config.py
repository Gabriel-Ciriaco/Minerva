"""Leitura do minerva.yaml (opcional) com padrões e validação."""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

CONFIG_NAME = "minerva.yaml"
DOC_TYPES = {"material", "livro"}
KEYS = {"disciplina", "fontes", "tipos", "ignorar", "ollama"}
OLLAMA_KEYS = {"modelo", "host", "contexto"}

TEMPLATE = """\
# Configuração do Minerva. Tudo é opcional; apague o que não usar.

# Nome da disciplina (aparece nas respostas do outline).
# disciplina: Cálculo I

# Pastas ou arquivos que entram no índice. Sem esta chave, todo o workspace é lido.
# Recomendado: aponte só para os materiais (exercícios e anotações suas ficam de fora).
# fontes: [materiais/]

# Tipo de cada fonte: "material" (slides, resumos; prioridade na busca) ou "livro".
# Padrão: documentos com 200 páginas ou mais são livros. Precedência: arquivo >
# pasta mais específica > padrão. Caminhos relativos a esta pasta; pasta termina em "/".
# tipos:
#   livros/: livro
#   "slides/apostila_longa.pdf": material

# Arquivos ou pastas fora do índice.
# ignorar: [rascunhos/]

# Modelo local para `minerva chat` (Ollama). Precisa suportar ferramentas (ex.: qwen3).
# host padrão: OLLAMA_HOST ou http://localhost:11434; contexto padrão: 8192 tokens.
# ollama:
#   modelo: qwen3:8b
"""


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    disciplina: str = ""
    tipos: dict = field(default_factory=dict)
    ignorar: list = field(default_factory=list)
    fontes: list = field(default_factory=list)
    ollama: dict = field(default_factory=dict)  # só o `minerva chat` usa; fora da assinatura

    def signature(self):
        """Muda quando a configuração muda o conteúdo do índice."""
        data = json.dumps({"tipos": self.tipos, "ignorar": self.ignorar, "fontes": self.fontes},
                          sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()[:12]

    def doc_type(self, rel):
        """Tipo configurado para o caminho relativo `rel` (posix), ou None para a heurística."""
        if rel in self.tipos:
            return self.tipos[rel]
        best = None
        for key, value in self.tipos.items():
            if key.endswith("/") and rel.startswith(key) and (best is None or len(key) > len(best[0])):
                best = (key, value)
        return best[1] if best else None

    def ignored(self, rel):
        return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in self.ignorar)


def _norm(path, what):
    if not isinstance(path, str) or not path.strip():
        raise ConfigError(f"{what}: caminho inválido {path!r}")
    p = path.strip().replace("\\", "/")
    folder = p.endswith("/")
    pure = PurePosixPath(p)
    if pure.is_absolute() or ".." in pure.parts:
        raise ConfigError(f"{what}: use caminho relativo dentro do workspace ({path!r})")
    return str(pure) + ("/" if folder else "")


def load(workspace):
    path = Path(workspace) / CONFIG_NAME
    if not path.exists():
        return Config()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{CONFIG_NAME} inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG_NAME} deve ser um mapa de chaves")
    unknown = set(data) - KEYS
    if unknown:
        raise ConfigError(f"{CONFIG_NAME}: chave desconhecida {sorted(unknown)}; válidas: {sorted(KEYS)}")
    disciplina = data.get("disciplina") or ""
    if not isinstance(disciplina, str):
        raise ConfigError("disciplina deve ser texto")
    tipos = data.get("tipos") or {}
    if not isinstance(tipos, dict):
        raise ConfigError("tipos deve ser um mapa caminho: tipo")
    norm_tipos = {}
    for key, value in tipos.items():
        if value not in DOC_TYPES:
            raise ConfigError(f"tipos: {key!r} tem tipo {value!r}; use {sorted(DOC_TYPES)}")
        norm_tipos[_norm(key, "tipos")] = value
    ignorar = data.get("ignorar") or []
    if not isinstance(ignorar, list):
        raise ConfigError("ignorar deve ser uma lista")
    fontes = data.get("fontes") or []
    if not isinstance(fontes, list):
        raise ConfigError("fontes deve ser uma lista")
    norm_fontes = []
    for p in fontes:
        rel = _norm(p, "fontes")
        if rel.rstrip("/") == ".":
            raise ConfigError("fontes: para ler o workspace inteiro, apague a chave fontes")
        target = Path(workspace) / rel.rstrip("/")
        if not target.exists():
            raise ConfigError(f"fontes: {p!r} não existe no workspace")
        if target.is_dir() and not rel.endswith("/"):
            rel += "/"
        elif not target.is_dir() and rel.endswith("/"):
            raise ConfigError(f"fontes: {p!r} termina em '/' mas é um arquivo")
        if rel not in norm_fontes:
            norm_fontes.append(rel)
    ollama = data.get("ollama") or {}
    if not isinstance(ollama, dict):
        raise ConfigError("ollama deve ser um mapa (modelo, host, contexto)")
    if set(ollama) - OLLAMA_KEYS:
        raise ConfigError(f"ollama: chave desconhecida {sorted(set(ollama) - OLLAMA_KEYS)}; "
                          f"válidas: {sorted(OLLAMA_KEYS)}")
    for key in ("modelo", "host"):
        if key in ollama and not (isinstance(ollama[key], str) and ollama[key].strip()):
            raise ConfigError(f"ollama.{key} deve ser texto")
    ctx = ollama.get("contexto")
    if ctx is not None and (not isinstance(ctx, int) or isinstance(ctx, bool) or ctx < 2048):
        raise ConfigError("ollama.contexto deve ser um número inteiro de tokens (mínimo 2048)")
    return Config(disciplina, norm_tipos, [_norm(p, "ignorar") for p in ignorar], sorted(norm_fontes),
                  dict(ollama))
