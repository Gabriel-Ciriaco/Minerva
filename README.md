<div align="center">
	<h1>Minerva</h1>
	<p><strong>Transforme os slides, PDFs e livros da sua disciplina na memória oficial do seu agente de IA.</strong></p>
</div>

---

Estudar com IA muitas vezes significa lidar com alucinações confiantes: modelos inventam métodos, confundem anotações e não dizem de onde tiraram as informações. Além disso, a maioria das soluções para estudo prende você a interfaces fechadas ou chatbots passivos, limitados apenas a responder perguntas em uma caixinha de texto.

O **Minerva** resolve isso na raiz. Ele atua como uma ponte ultrarrápida, leve e 100% offline entre o acervo da sua disciplina (slides PPTX, apostilas em PDF, livros e resumos) e o seu agente de IA via **MCP (Model Context Protocol)**.

O resultado é um **agente de IA tradicional com memória cirúrgica**:

* **Muito além de um simples chat**: O Minerva não é uma caixinha de texto isolada de perguntas e respostas. Ele conecta o conhecimento da disciplina diretamente ao seu agente de desenvolvimento (atualmente com suporte de primeira classe no Antigravity no Protótipo 1). Isso permite que o modelo use skills, escreva e depure código, crie diagramas ou resolva listas práticas — sempre ancorado estritamente nas convenções e teorias dos materiais do seu professor.
* **Citações exatas e sem estourar contexto**: Em vez de despejar arquivos inteiros e queimar tokens à toa, o Minerva entrega trechos curtos com **arquivo e página exata** (`[aula05.pdf p.10]`). O agente continua sendo o assistente potente que você já usa no dia a dia, mas com a certeza absoluta da fonte de cada resposta.

---

### Destaques

* **Citações com precisão cirúrgica**: Cada afirmação vem carimbada com `[arquivo p.X]`. Se algo não consta nos seus materiais, o agente avisa claramente ou sinaliza como `[Conhecimento geral]`.
* **Agente completo em ação**: Não fica restrito a resumos passivos. Seu agente usa o acervo da disciplina como base de verdade enquanto codifica, resolve exercícios, executa scripts e aciona ferramentas.
* **100% offline e privativo**: Seus materiais e anotações nunca saem da sua máquina. O índice (SQLite + FTS5) reside dentro da própria pasta da disciplina, sem telemetria nem chamadas de rede.
* **Suporte inteligente a PDF, PPTX e Markdown**: Remove cabeçalhos e rodapés repetitivos, mapeia a página física para a impressa (`p.125 (impressa 109)`) e avisa sobre arquivos digitalizados sem OCR.
* **Indexação incremental e veloz**: O `ingest` recalcula apenas arquivos modificados (via hash) e notifica o agente caso a pasta tenha sido alterada após a indexação.
* **Econômico em tokens**: Três ferramentas enxutas (`search`, `outline`, `read`) com teto de caracteres e orçamento por pergunta para o agente não queimar a janela de contexto.
* **Setup instantâneo**: Com `minerva connect antigravity`, as regras de estudo e o servidor MCP são configurados diretamente na pasta da disciplina, sem alterar suas configurações globais.

> **Construído sobre padrões abertos**: O Minerva opera como um servidor **MCP (Model Context Protocol)** padrão via stdio, pronto para ser conectado a qualquer cliente ou LLM. No momento (Protótipo 1), seu fluxo de conexão assistida (`minerva connect`) e seus templates pedagógicos foram homologados e otimizados com suporte de primeira classe no **Antigravity** (Windows / Python 3.11+).

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

Na pasta da disciplina (a mesma que você abre no Antigravity):

```powershell
cd C:\caminho\para\minha-disciplina
minerva init                    # cria minerva.yaml (opcional) e .minerva/
minerva ingest                  # indexa; rode de novo sempre que mudar os materiais
minerva connect antigravity     # escreve .agents/mcp_config.json e .agents/AGENTS.md
```

Recarregue o Antigravity (ou reabra a pasta) e pergunte algo sobre a disciplina.

#### 2. Perguntar

```text
Você:    O que a aula 05 cobre? Depois me explique o slide 10.
Agente:  outline("aula05.pdf") → read([...])
         ### O que os materiais dizem
         Métricas orientadas ao tamanho: Produtividade = KLOC / pessoas-mês [aula05.pdf p.10] ...
         ### [Conhecimento geral]
         ...
```

#### 3. Outros comandos

| Comando | Para quê |
| :--- | :--- |
| `minerva search termos` | Testar a busca no terminal (mesmo JSON que o agente recebe) |
| `minerva outline [arquivo]` | Listar as fontes, ou as páginas de uma fonte |
| `minerva doctor` | Verificar Python, índice, arquivos sem texto e a conexão |
| `minerva ingest --rebuild` | Reconstruir o índice do zero |
| `minerva connect antigravity --log` | Registrar as chamadas do agente (sem o texto) em `.minerva/logs/` |
| `minerva serve` | O servidor MCP; quem executa é o Antigravity |

#### 4. Rodar os testes

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Os testes usam um corpus sintético em `tests/corpus/` (gerado por `tests/generate_corpus.py`): PDF textual, PDF com tabela, PPTX, Markdown com código e um PDF só de imagens.

---

### Configuração (`minerva.yaml`, opcional)

```yaml
disciplina: Cálculo I          # aparece no título das regras do agente
tipos:                          # "material" tem prioridade na busca; "livro" vira "ver também"
  livros/: livro
  "slides/apostila_longa.pdf": material
ignorar: [rascunhos/]
```

Sem configuração, documentos com 200 páginas ou mais são tratados como livros. Ficam fora do índice pastas ocultas (`.git`, `.agents`, `.minerva`) e arquivos de agente (`AGENTS.md`, `memory.md`...).

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
│   ├── cli.py                  # Comandos: init, ingest, serve, search, outline, read, connect, doctor
│   ├── config.py               # Leitura e validação do minerva.yaml
│   ├── extract.py              # Extração de PDF, PPTX e Markdown; limpeza e página impressa
│   ├── index.py                # Índice SQLite/FTS5 persistente e incremental
│   ├── search.py               # search, outline, read e orçamento por pergunta
│   ├── server.py               # Servidor MCP (stdio, somente leitura)
│   ├── connect.py              # Configuração do Antigravity em .agents/
│   └── templates/AGENTS.md     # Regras do tutor
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
