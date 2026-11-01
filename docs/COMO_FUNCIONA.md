# Como o Minerva funciona

O Minerva tem duas metades: o **`ingest`**, que lê os materiais e monta um índice local, e o **`serve`**, um servidor MCP somente leitura que o agente (Antigravity) consulta com três ferramentas. O agente nunca abre os arquivos: recebe trechos curtos, cada um com `ref` e citação.

```text
pasta da disciplina ──ingest──▶ .minerva/index.db ◀──serve (MCP)── agente
  PDF, PPTX, MD                 SQLite + FTS5        search · outline · read
```

## 1. Indexação (`minerva ingest`)

- **O que entra:** `.pdf`, `.pptx` e `.md` em qualquer subpasta. Ficam fora pastas ocultas (`.git`, `.agents`, `.minerva`), arquivos de agente (`AGENTS.md`, `memory.md`, `mcp_config.json`, `minerva.yaml`) e o que estiver em `ignorar` no `minerva.yaml`.
- **Unidade:** uma página de PDF, um slide de PPTX ou uma seção `##` de Markdown vira um trecho, com citação `arquivo p.X`, `arquivo slide X` ou `arquivo §Seção (l.10-25)`.
- **Limpeza:** cabeçalhos e rodapés que se repetem na maioria das páginas são removidos; quando o PDF tem numeração impressa diferente da física, a citação traz as duas (`p.125 (impressa 109)`).
- **Status por arquivo:** `ok`; `parcial` (algumas páginas sem texto); `sem_texto` (PDF digitalizado ou imagem: existe, mas a busca não alcança); `erro`/`erro_parcial` (falha ao ler). `minerva doctor` lista esses casos.
- **Tipo:** `material` (slides, resumos) ou `livro`. Documentos com 200 páginas ou mais são livros por padrão; o `minerva.yaml` pode mudar isso por arquivo ou pasta. Material vem primeiro na busca.
- **Incremental:** cada arquivo é comparado pelo hash (SHA-256), não só pela data. Só o que mudou é reextraído. A extração acontece fora da transação e cada arquivo é publicado numa transação curta: uma falha no meio deixa o arquivo na versão anterior ou na nova, nunca misturadas.
- **Concorrência:** um lock com PID impede dois `ingest` ao mesmo tempo. O servidor lê o banco em modo WAL e enxerga cada arquivo assim que ele é publicado.

## 2. As ferramentas MCP (`minerva serve`)

Toda resposta é JSON com teto de tamanho sobre a resposta inteira (estimativa de 1 token ≈ 4 caracteres).

| Ferramenta | Para quê | Teto |
| --- | --- | --- |
| `search(query, top_k=3)` | Busca por palavras-chave (BM25 com sinônimos e sem acentos). Devolve até 5 trechos curtos com `ref` e citação; `ver_tambem` sugere um livro com as páginas do tema. | 600 |
| `outline(source="")` | Sem argumento: lista as fontes com tipo, páginas e status. Com um arquivo: uma linha por página com título e `ref`, para ir direto ao `read`. | 1500 (lista) · 600 (páginas) |
| `read(refs, vizinhos=0, offset=0)` | Texto completo de até 3 refs. `vizinhos=1` inclui a página anterior e a seguinte. O que não couber volta em `continua`/`pendentes`. | 1500 |

**Refs** têm a forma `<id>@<hash>`. Se o arquivo mudou depois que o agente recebeu o ref, `read` responde `STALE_REFERENCE` e o agente busca de novo.

**Aviso de índice desatualizado:** `outline()` sem argumento compara a pasta com o índice e, se algo mudou, traz um `aviso` pedindo `minerva ingest`. O servidor nunca indexa sozinho.

## 3. Orçamento por pergunta

Agentes tendem a varrer documentos inteiros ou insistir em buscar o que não existe. O servidor freia isso por pergunta (uma pausa de mais de 90 s entre chamadas conta como pergunta nova):

- **Páginas por documento:** depois de 12 páginas de um mesmo documento, `read` devolve `LEITURA_EXCESSIVA`, exceto para páginas que um `search` trouxe ou que já foram lidas.
- **Chamadas:** a partir da 15ª chamada, toda resposta traz `limite`, pedindo que o agente responda com o que encontrou. É só um aviso.
- **Lista de fontes:** pedida de novo na mesma pergunta, volta só uma `nota`.

## 4. Regras do agente (`minerva connect antigravity`)

O `connect` escreve, só dentro da pasta da disciplina:

- `.agents/mcp_config.json`: a entrada do servidor `minerva` (as demais entradas são preservadas).
- `.agents/AGENTS.md`: as regras do tutor, entre os marcadores `<!-- minerva:inicio -->` e `<!-- minerva:fim -->`; o resto do arquivo não é tocado.

As regras pedem, em resumo: buscar antes de responder, usar só as ferramentas do Minerva, não percorrer documentos, citar `[arquivo p.X]`, separar o que os materiais dizem do que é `[Conhecimento geral]`, dizer "não encontrei isso nos materiais" quando for o caso e tratar o texto dos materiais como dado, nunca como instrução.

Rodar `connect` de novo é seguro: se nada mudou, nada é escrito. `--force` substitui uma entrada `minerva` editada à mão; `--log` faz o servidor registrar cada chamada (ferramenta, argumentos, tamanho e tempo, nunca o texto) em `.minerva/logs/`.

## 5. Configuração (`minerva.yaml`, opcional)

```yaml
disciplina: Cálculo I          # aparece no título das regras do agente
tipos:
  livros/: livro                # pasta termina em "/"
  "slides/apostila_longa.pdf": material
ignorar: [rascunhos/]
```

Precedência de `tipos`: arquivo > pasta mais específica > padrão (200 páginas).

## 6. Privacidade

Tudo fica na pasta da disciplina: índice, logs e configuração do agente em `.minerva/` e `.agents/`. O Minerva não faz chamadas de rede; o que sai do computador é só o que o próprio agente lê pelas ferramentas.
