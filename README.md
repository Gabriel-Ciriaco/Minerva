<div align="center">
	<h1>Minerva</h1>
	<p><strong>Transforme os slides, PDFs e livros da sua disciplina na memória oficial do seu agente de IA.</strong></p>
</div>

---

Estudar com IA muitas vezes significa lidar com alucinações confiantes: modelos inventam métodos, confundem anotações e não dizem de onde tiraram as informações. Além disso, a maioria das soluções para estudo prende você a interfaces fechadas ou chatbots passivos, limitados apenas a responder perguntas em uma caixinha de texto.

O **Minerva** resolve isso na raiz. Ele atua como uma ponte ultrarrápida, leve e 100% offline entre o acervo da sua disciplina (slides PPTX, apostilas em PDF, livros e resumos) e o seu agente de IA via **MCP (Model Context Protocol)**.

O resultado é um **agente de IA tradicional com memória cirúrgica**:

* **Muito além de um simples chat**: O Minerva não é uma caixinha de texto isolada de perguntas e respostas. Ele conecta o conhecimento da disciplina diretamente ao seu agente de desenvolvimento (Antigravity, Claude Code ou Codex CLI) ou a um modelo local no Ollama. Isso permite que o modelo use skills, escreva e depure código, crie diagramas ou resolva listas práticas — sempre ancorado estritamente nas convenções e teorias dos materiais do seu professor.
* **Citações exatas e sem estourar contexto**: Em vez de despejar arquivos inteiros e queimar tokens à toa, o Minerva entrega trechos curtos com **arquivo e página exata** (`[aula05.pdf p.10]`). O agente continua sendo o assistente potente que você já usa no dia a dia, mas com a certeza absoluta da fonte de cada resposta.

---

### Destaques

* **Citações com precisão cirúrgica**: Cada afirmação vem carimbada com `[arquivo p.X]`. Se algo não consta nos seus materiais, o agente avisa claramente ou sinaliza como `[Conhecimento geral]`.
* **Agente completo em ação**: Não fica restrito a resumos passivos. Seu agente usa o acervo da disciplina como base de verdade enquanto codifica, resolve exercícios, executa scripts e aciona ferramentas.
* **Local e privativo**: O índice (SQLite + FTS5) reside dentro da própria pasta da disciplina, sem telemetria nem chamadas de rede. Com o `minerva chat` e o Ollama, nada sai da sua máquina; com um agente na nuvem, saem só os trechos que ele lê pelas ferramentas.
* **Suporte inteligente a PDF, PPTX e Markdown**: Remove cabeçalhos e rodapés repetitivos, mapeia a página física para a impressa (`p.125 (impressa 109)`) e avisa sobre arquivos digitalizados sem OCR.
* **Indexação incremental e veloz**: O `ingest` recalcula apenas arquivos modificados (via hash) e notifica o agente caso a pasta tenha sido alterada após a indexação.
* **Econômico em tokens**: Três ferramentas enxutas (`search`, `outline`, `read`) com teto de caracteres e orçamento por pergunta para o agente não queimar a janela de contexto.
* **Setup instantâneo**: Com `minerva connect antigravity`, `claude-code` ou `codex`, as regras de estudo e o servidor MCP são configurados diretamente na pasta da disciplina, sem alterar suas configurações globais.
* **Memória do aluno**: Um `MEMORIA.md` curto guarda suas convenções, decisões da disciplina e onde você parou. O agente só grava uma linha depois que você confirma.
* **Modelo local**: `minerva chat` conversa no terminal com um modelo do Ollama usando as mesmas ferramentas, sem nenhum outro programa.

> **Construído sobre padrões abertos**: O Minerva opera como um servidor **MCP (Model Context Protocol)** padrão via stdio, pronto para ser conectado a qualquer cliente ou LLM. O fluxo de conexão assistida (`minerva connect`) foi validado em uso real no **Antigravity** (Windows / Python 3.11+); Claude Code, Codex CLI e o chat com Ollama têm testes automatizados e ainda aguardam validação com os clientes reais.

---

### Instalação

Requer Python 3.11 ou mais novo.

```powershell
git clone https://github.com/Gabriel-Ciriaco/Minerva.git
cd Minerva
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

O comando `minerva` fica em `.venv\Scripts\minerva.exe`. Use esse caminho completo ou ative o ambiente antes (`.\.venv\Scripts\Activate.ps1`).

---

### Uso

#### 1. Indexar e conectar

Na pasta da disciplina (a mesma que você abre no seu agente):

```powershell
cd C:\caminho\para\minha-disciplina
minerva init                    # cria minerva.yaml, MEMORIA.md e .minerva/
minerva ingest                  # indexa; rode de novo sempre que mudar os materiais
minerva connect antigravity     # ou claude-code, ou codex (veja a tabela abaixo)
```

Deixe o código do Minerva fora dessa pasta e, se ela tiver mais do que materiais (exercícios, anotações), use `fontes:` no `minerva.yaml` para indexar só os materiais.

| Cliente | Comando | O que é escrito na pasta | Depois |
| :--- | :--- | :--- | :--- |
| Antigravity | `minerva connect antigravity` | `.agents/mcp_config.json`, `.agents/AGENTS.md` | Recarregue o Antigravity (ou reabra a pasta) |
| Claude Code | `minerva connect claude-code` | `.mcp.json`, `CLAUDE.md` | Abra `claude` na pasta e aprove o servidor `minerva`; confira com `/mcp` |
| Codex CLI | `minerva connect codex` | `.codex/config.toml`, `AGENTS.md` | Abra `codex` na pasta e marque-a como confiável; sem isso o Codex ignora o `.codex/config.toml` |
| Outro cliente MCP | `minerva connect outro` | nada | Mostra a entrada do servidor e as regras para você colar |

Todos também criam o `MEMORIA.md`, se ele não existir. Nada é escrito fora da pasta da disciplina, e rodar de novo só atualiza o bloco do Minerva. Versões recentes do Antigravity também podem ler o `AGENTS.md` da raiz: com ele e o Codex conectados na mesma pasta, as regras podem chegar duas vezes, o que só custa alguns tokens.

#### 2. Perguntar

```text
Você:    O que a aula 05 cobre? Depois me explique o slide 10.
Agente:  outline("aula05.pdf") → read([...])
         ### O que os materiais dizem
         Métricas orientadas ao tamanho: Produtividade = KLOC / pessoas-mês [aula05.pdf p.10] ...
         ### [Conhecimento geral]
         ...
```

#### 3. Chat com modelo local (Ollama)

Sem agente nenhum: o `minerva chat` conversa no terminal com um modelo do Ollama e usa as mesmas ferramentas `search`, `outline` e `read`, com os mesmos limites. Com o Ollama em Docker:

```powershell
docker run -d --name ollama -p 11434:11434 -v ollama:/root/.ollama ollama/ollama
docker exec -it ollama ollama pull qwen3:8b
minerva chat --modelo qwen3:8b       # /sair encerra
```

- O modelo precisa suportar ferramentas (*tools*), como qwen3 ou llama3.1. Modelos pequenos erram mais nas chamadas; o chat devolve o erro ao modelo para ele corrigir.
- Para não repetir o modelo, use `ollama: {modelo: qwen3:8b}` no `minerva.yaml`. O endereço segue `--host`, depois `ollama.host`, depois `OLLAMA_HOST`, depois `http://localhost:11434`.
- `--sem-pensar` desliga o raciocínio de modelos como o qwen3, o que deixa as respostas mais rápidas. A janela de contexto padrão é de 8192 tokens (`--contexto` muda).
- Para gravar algo no `MEMORIA.md`, o modelo propõe uma linha e o chat pergunta `Gravar? [s/N]` antes de escrever.

#### 4. Memória (`MEMORIA.md`)

Arquivo curto na raiz da pasta, com quatro seções: Convenções, Decisões da disciplina, Andamento e Dificuldades. O agente lê no início da conversa e, ao concluir algo relevante, propõe uma linha; só grava se você disser sim. Você pode editar o arquivo à vontade. Ele fica fora do índice, e o `minerva doctor` avisa quando passa de ~2 KB, porque vai inteiro em toda conversa.

#### 5. Outros comandos

| Comando | Para quê |
| :--- | :--- |
| `minerva search termos` | Testar a busca no terminal (mesmo JSON que o agente recebe) |
| `minerva outline [arquivo]` | Listar as fontes, ou as páginas de uma fonte |
| `minerva doctor` | Verificar Python, índice, arquivos sem texto, memória, clientes conectados e Ollama |
| `minerva ingest --rebuild` | Reconstruir o índice do zero |
| `minerva connect <cliente> --log` | Registrar as chamadas do agente (sem o texto) em `.minerva/logs/` |
| `minerva serve` | O servidor MCP; quem executa é o cliente |

#### 6. Rodar os testes

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Os testes usam um corpus sintético em `tests/corpus/` (gerado por `tests/generate_corpus.py`): PDF textual, PDF com tabela, PPTX, Markdown com código e um PDF só de imagens. O chat é testado contra um Ollama falso; não é preciso ter o Ollama instalado.

---

### Configuração (`minerva.yaml`, opcional)

```yaml
disciplina: Cálculo I          # aparece no título das regras do agente
fontes: [materiais/]            # só isto entra no índice; sem a chave, o workspace inteiro
tipos:                          # "material" tem prioridade na busca; "livro" vira "ver também"
  livros/: livro
  "slides/apostila_longa.pdf": material
ignorar: [rascunhos/]
ollama:                         # só para o minerva chat
  modelo: qwen3:8b
```

Sem configuração, documentos com 200 páginas ou mais são tratados como livros. Ficam fora do índice pastas ocultas (`.git`, `.agents`, `.codex`, `.minerva`) e arquivos de agente (`AGENTS.md`, `CLAUDE.md`, `MEMORIA.md`...).

Use `fontes` quando o workspace tiver mais coisas além dos materiais (exercícios resolvidos, código, anotações): assim só os materiais entram na busca. O `ignorar` continua valendo dentro das fontes. Formatos lidos: PDF, PPTX e Markdown; os demais arquivos aparecem resumidos numa linha do `ingest`.

#### PDFs escaneados

PDFs sem camada de texto (status `sem_texto`) e imagens (`imagem_sem_ocr`) aparecem no `outline`, mas a busca não os alcança. Antes de indexar, procure uma versão digital do material ou aplique OCR uma vez, fora do Minerva, por exemplo com o [OCRmyPDF](https://ocrmypdf.readthedocs.io/) (`ocrmypdf -l por arquivo.pdf arquivo.pdf`). O OCR costuma errar fórmulas e símbolos; confira os trechos citados.

---

### Privacidade e git

`.minerva/` (índice e logs) contém texto extraído dos seus materiais. Se a pasta da disciplina for um repositório git, adicione ao `.gitignore`:

```gitignore
.minerva/
```

`minerva doctor` avisa se encontrar materiais ou o índice versionados.

---

### Como funciona

Indexação, ferramentas MCP, orçamento por pergunta e regras do agente estão em [docs/COMO_FUNCIONA.md](docs/COMO_FUNCIONA.md).

---

### Estrutura do projeto

```text
.
├── src/minerva/
│   ├── cli.py                  # Comandos: init, ingest, serve, search, outline, read, connect, chat, doctor
│   ├── config.py               # Leitura e validação do minerva.yaml
│   ├── extract.py              # Extração de PDF, PPTX e Markdown; limpeza e página impressa
│   ├── index.py                # Índice SQLite/FTS5 persistente e incremental
│   ├── search.py               # search, outline, read e orçamento por pergunta
│   ├── server.py               # Servidor MCP (stdio, somente leitura)
│   ├── connect.py              # Configuração de Antigravity, Claude Code e Codex dentro da pasta
│   ├── chat.py                 # minerva chat: Ollama + as mesmas ferramentas, no mesmo processo
│   └── templates/              # AGENTS.md (regras do tutor) e MEMORIA.md (modelo da memória)
├── tests/                      # Suíte pytest e corpus sintético
├── docs/COMO_FUNCIONA.md       # Funcionamento interno
├── AI_REPORT.md                # AI Transparency & Methodology Report (English)
└── RELATORIO_IA.md             # Relatório de Transparência e Metodologia de IA (Português)
```

---

### Transparência no uso de IA

O Minerva foi desenvolvido com IA generativa como par de programação, em ciclos de plano, revisão, implementação e teste no Antigravity. O relatório descreve o que foi feito pelo autor, o que foi assistido e os problemas encontrados e corrigidos em cada rodada.

Leia em [Português (RELATORIO_IA.md)](RELATORIO_IA.md) ou em [English (AI_REPORT.md)](AI_REPORT.md).

---

## Autor ✨

<table>
	<tr>
		<td align="center">
			<a href="https://github.com/Gabriel-Ciriaco">
				<img src="https://avatars.githubusercontent.com/u/66225865" width="100px;" alt=""/>
				<br>
				<sub>
					<b>Gabriel C. de Carvalho</b>
				</sub>
			</a>
		</td>
	</tr>
</table>
