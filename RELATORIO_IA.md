> 🌐 **Language / Idioma:** **Português (Brasil)** | [English Version (AI_REPORT.md)](AI_REPORT.md)

# Relatório Técnico de Transparência e Uso de Inteligência Artificial
**Projeto:** Minerva — servidor MCP para fundamentar agentes de IA nos materiais da sua disciplina.  
**Repositório:** `Gabriel-Ciriaco/Minerva`  
**Ferramentas de IA:** Claude Code (Claude Opus) como par de programação; Antigravity como cliente de teste  

---

## 1. Declaração de Integridade e Metodologia

Este documento descreve com transparência como a IA Generativa foi usada para construir o Minerva. O assistente de IA atuou como **par de programação e consultor técnico**; não recebeu um pedido genérico de "construa isto".

O trabalho avançou em ciclos curtos guiados por evidência: **plano → revisão independente → implementação → teste no cliente real → medição → ajuste**. Cada fase teve um plano escrito, uma revisão escrita e um documento de decisão, e cada afirmação foi marcada pela origem da evidência (`[executado]`, `[inspecionado]`, `[documentado]`). Esses documentos de trabalho ficam fora do repositório público porque citam materiais privados da disciplina.

---

## 2. Trabalho Original do Autor

1. **Visão do produto:** um tutor que responde só a partir dos slides e PDFs do próprio aluno, com citação de página, roda localmente e se conecta a um agente que o aluno já usa, sem servidor hospedado nem envio da disciplina.
2. **Levantamento e primeiro plano:** pesquisa de projetos open-source existentes (especificações de agentes, servidores MCP do Google Classroom, tutores RAG monolíticos) para achar onde o Minerva agrega, seguida de cinco versões do plano (v1–v5) que reduziram o escopo a um núcleo local instrumentado.
3. **Conjunto de avaliação real:** o autor escreveu as perguntas de aluno usadas para julgar o comportamento (data de prova, "o estilo do professor" para um diagrama, um padrão lembrado vagamente, tabelas de inspeção, resumo de uma aula) e manteve parte delas privada, como holdout.
4. **Teste no cliente real:** o autor rodou à mão cada rodada no Antigravity (v2–v5), uma pergunta por vez, e trouxe as transcrições completas para análise.
5. **Decisões e restrições:** privacidade em primeiro lugar (nada global fora da pasta da disciplina, nada específico da disciplina no repositório público), aceitar respostas mais curtas em troca de custo controlado e decidir quando parar de ajustar e partir para o teste com um colega.

---

## 3. Diagnósticos e Correções Assistidas por IA

As rodadas no Antigravity revelaram comportamentos do agente que testes unitários não mostravam. Cada correção abaixo veio com teste.

### 3.1. Agente lendo o código do próprio servidor
* **Problema (v2):** a lista de fontes era paginada; para ver o resto, o agente abriu `server.py` e `mcp_config.json` diretamente e abriu a imagem de uma prova fora das ferramentas.
* **Solução:** a lista de fontes ganhou teto próprio (uma página para ~50 fontes), e as regras do agente proíbem mexer em arquivos fora das ferramentas do Minerva.

### 3.2. `outline` sem referências
* **Problema (revisão da Fase 0):** o `outline` devolvia títulos de página, mas não `ref`, obrigando um `search` extra antes de cada `read`.
* **Solução:** o `outline` devolve um `ref` por página; o `read` aceita até 3 refs, vizinhos e `offset` para continuação, com teto sobre a resposta inteira. Resumir uma aula caiu de ~27 para 9 chamadas.

### 3.3. Varredura de documentos inteiros
* **Problema (v3):** para "o estilo do professor", o agente leu ~50 páginas de uma aula, de 3 em 3: 44 chamadas e ~23,6 mil tokens de saída das ferramentas.
* **Solução:** um orçamento por pergunta (`QuestionBudget`): depois de 12 páginas do mesmo documento, o `read` devolve `LEITURA_EXCESSIVA`, exceto para páginas trazidas por `search` ou já lidas.

### 3.4. Buscar o que não existe
* **Problema (v4):** perguntado sobre o que o professor "disse que fazemos errado", o agente fez 17 buscas (inclusive a palavra solta "errado") e pediu a lista de fontes 4 vezes: 34 chamadas.
* **Solução:** a partir da 15ª chamada, toda resposta traz o aviso `limite`; a lista de fontes repetida volta só como nota curta; uma regra diz que falas de aula raramente estão nos materiais.

### 3.5. "Conhecimento geral" inventado
* **Problema (v3):** em `[Conhecimento geral]`, o agente afirmou o que o professor "cobra" dos alunos e apresentou um ano deduzido como fato.
* **Solução:** o conhecimento geral fala só do assunto, nunca do professor ou da turma, e deduções são marcadas como dedução.

### 3.6. Resultados exagerados
* **Problema:** uma primeira versão do documento de decisão da Fase 0 estava marcada como "Concluído e Aprovado", com itens não medidos nem implementados.
* **Solução:** foi reescrito com marcação de evidência e o status explícito "encerrada com ressalvas". Os números de tokens são apresentados como estimativa da saída das ferramentas, não como uso do modelo.

---

## 4. Efeito Medido

Chamadas de ferramenta e tokens estimados devolvidos pelas ferramentas (1 token ≈ 4 caracteres), por pergunta:

| Pergunta | v3 | v4 | v5 |
| :--- | :---: | :---: | :---: |
| Estilo do professor no diagrama de colaboração | 44 / ~23,6k | não rodada | **14 / ~7,3k** |
| Nome do padrão ("model view algo") | 16 / ~8,1k | 34 / ~16,2k | **9 / ~4,1k** |
| Tabela da inspeção (PBR) | 22 / ~10,6k | **15 / ~6,9k** | — |

A resposta da v5 sobre o diagrama omitiu pontos que a da v3 cobria. Saber se o orçamento de páginas sozinho causou isso exige uma comparação controlada.

---

## 5. O que NÃO Foi Feito pela IA

* **Nenhum código sem revisão:** cada mudança foi proposta, explicada e aceita pelo autor antes de seguir; o autor revisou a análise de cada rodada de teste.
* **Nenhuma avaliação inventada:** perguntas, transcrições e o julgamento da utilidade das respostas vieram do uso real do autor.
* **Nenhuma publicação sem consentimento:** commits, reescrita de histórico e pushes foram decididos pelo autor.

---

## 6. Matriz de Responsabilidades

| Componente / Tarefa | Papel do Autor | Papel do Assistente de IA |
| :--- | :--- | :--- |
| **Visão e escopo** | Problema, público, restrições de privacidade, versões do plano. | Apoio ao levantamento, redação e crítica dos planos. |
| **Protótipos da Fase 0** | Escolha do que medir; aceitação dos resultados. | Benchmarks de extratores/FTS5/MCP e código dos protótipos. |
| **Pacote (`src/minerva`)** | Requisitos, revisão e aceitação. | Implementação do índice, extração, ferramentas, CLI e `connect`. |
| **Regras do agente (`AGENTS.md`)** | Comportamento esperado do tutor (citações, abstenção). | Redação e correções sucessivas a partir dos logs de teste. |
| **Teste no cliente real** | Rodadas no Antigravity, perguntas, transcrições. | Análise dos logs, métricas por pergunta, diagnóstico. |
| **Testes (`tests/`)** | Aceitação. | Suíte de testes e corpus sintético. |
| **Higiene do repositório** | Decisão de retirar conteúdo da disciplina e planos. | Corpus neutro, separação de ignores público/privado, documentação. |

---

## 7. Reflexão Crítica e Aprendizados

1. **O agente faz parte do sistema.** Ferramentas corretas não bastaram; a maioria dos problemas foi comportamento do agente (varrer, insistir, inventar), visível só nas transcrições reais.
2. **Limite no servidor vale mais que instrução.** Uma regra no `AGENTS.md` sozinha não impediu a varredura de documentos; um orçamento no servidor impediu.
3. **Medir antes de acreditar.** Registrar cada chamada (ferramenta, argumentos, tamanho, tempo, nunca o texto) transformou impressões em números por pergunta e expôs regressões como a rodada v4 de 34 chamadas.
4. **Custo e cobertura se equilibram.** Cortar a saída das ferramentas em cerca de 50–70% encurtou algumas respostas; o orçamento de páginas segue provisório até ser testado com perguntas novas.
