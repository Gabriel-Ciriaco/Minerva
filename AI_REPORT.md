> 🌐 **Language / Idioma:** **English** | [Versão em Português (RELATORIO_IA.md)](RELATORIO_IA.md)

# Technical Report: Transparency and Use of Artificial Intelligence
**Project:** Minerva — MCP server for grounding AI agents in your course materials.  
**Repository:** `Gabriel-Ciriaco/Minerva`  
**AI tools:** Claude Code (Claude Opus) as pair-programmer; Antigravity as the test client  

---

## 1. Integrity Declaration and Methodology

This document gives a transparent account of how Generative AI was used to build Minerva. The AI assistant worked as a **pair-programmer and technical consultant**; it did not receive an open-ended "build this" request.

Work moved in short, evidence-driven loops: **plan → independent review → implement → test in the real client → measure → adjust**. Every phase had a written plan, a written review and a decision document, and each claim was tagged by where its evidence came from (`[executed]`, `[inspected]`, `[documented]`). Those working documents are kept outside the public repository because they reference private course material.

---

## 2. Original Work by the Author

1. **Product vision:** a tutor that answers only from the student's own slides and PDFs, with page citations, runs locally, and plugs into an agent the student already uses, without a hosted server or an upload of the course.
2. **Market check and first plan:** a survey of existing open-source projects (agent specs, Google Classroom MCP servers, monolithic RAG tutors) to find where Minerva adds value, followed by five plan iterations (v1–v5) that narrowed the scope to a single instrumented local core.
3. **Real-world evaluation set:** the author wrote the student questions used to judge behavior (exam dates, "the professor's style" for a diagram, a vaguely remembered pattern name, inspection tables, a summary of a given lecture) and kept part of them private as a holdout.
4. **Testing in the real client:** the author ran every Antigravity round (v2–v5) by hand, one question at a time, and pasted the full transcripts back for analysis.
5. **Decisions and constraints:** privacy first (nothing global outside the course folder, nothing course-specific in the public repository), accepting shorter answers in exchange for bounded cost, and when to stop tuning and move to the colleague test.

---

## 3. Diagnostics and AI-Assisted Corrections

The rounds in Antigravity exposed agent behaviors that unit tests could not show. Each fix below came with a test.

### 3.1. Agent reading the server's own code
* **Problem (v2):** the source list was paginated; to see the rest, the agent opened `server.py` and `mcp_config.json` directly and opened an exam image outside the tools.
* **Resolution:** the source list got its own size ceiling (one page for ~50 sources), and the agent rules now forbid touching files outside the Minerva tools.

### 3.2. `outline` without references
* **Problem (Phase 0 review):** `outline` returned page titles but no `ref`, forcing an extra `search` before every `read`.
* **Resolution:** `outline` returns a `ref` per page; `read` accepts up to 3 refs, neighbors and an `offset` for continuation, under a ceiling on the whole response. Summarizing one lecture dropped from ~27 to 9 calls.

### 3.3. Sweeping whole documents
* **Problem (v3):** for "the professor's style", the agent read ~50 pages of one lecture, 3 at a time: 44 calls and ~23.6k tokens of tool output.
* **Resolution:** a per-question budget (`QuestionBudget`): after 12 pages of the same document, `read` returns `LEITURA_EXCESSIVA`, except for pages returned by `search` or already read.

### 3.4. Searching for what does not exist
* **Problem (v4):** asked what the professor "said we do wrong", the agent ran 17 searches (including the bare word "errado") and fetched the source list 4 times: 34 calls.
* **Resolution:** from the 15th call, every response carries a `limite` warning; a repeated source list returns only a short note; a rule states that classroom remarks are rarely in the materials.

### 3.5. Fabricated "general knowledge"
* **Problem (v3):** under `[Conhecimento geral]`, the agent claimed what the professor "demands" from students, and stated an inferred year as fact.
* **Resolution:** general knowledge must be about the subject only, never about the professor or class, and deductions must be labeled as such.

### 3.6. Overclaimed results
* **Problem:** an early Phase 0 decision document was marked "Completed and Approved" while some items had not been measured or implemented.
* **Resolution:** it was rewritten with evidence tags and an explicit "closed with caveats" status. Token figures are reported as estimates of tool output, not model usage.

---

## 4. Measured Effect

Tool calls and estimated tokens returned by the tools (1 token ≈ 4 characters), per question:

| Question | v3 | v4 | v5 |
| :--- | :---: | :---: | :---: |
| Professor's style for the collaboration diagram | 44 / ~23.6k | not run | **14 / ~7.3k** |
| Pattern name ("model view something") | 16 / ~8.1k | 34 / ~16.2k | **9 / ~4.1k** |
| Inspection (PBR) table | 22 / ~10.6k | **15 / ~6.9k** | — |

The v5 answer on the diagram omitted points the v3 answer covered. Whether the page budget alone caused it requires a controlled comparison.

---

## 5. What Was NOT Done by AI

* **No unreviewed code:** each change was proposed, explained and accepted by the author before moving on; the author reviewed the analysis of every test round.
* **No invented evaluation:** questions, transcripts and judgments of answer usefulness came from the author's real use.
* **No publication without consent:** commits, history rewrites and pushes were decided by the author.

---

## 6. Responsibility Matrix

| Component / Task | Author Role | AI Assistant Role |
| :--- | :--- | :--- |
| **Vision and scope** | Problem, audience, privacy constraints, plan iterations. | Market survey support, plan drafting and critique. |
| **Phase 0 prototypes** | Choice of what to measure; acceptance of results. | Extractor/FTS5/MCP benchmarks and prototype code. |
| **Package (`src/minerva`)** | Requirements, review and acceptance. | Implementation of index, extraction, tools, CLI and `connect`. |
| **Agent rules (`AGENTS.md`)** | Expected tutor behavior (citations, abstention). | Wording and successive corrections from test logs. |
| **Real-client testing** | Running Antigravity rounds, questions, transcripts. | Log analysis, per-question metrics, diagnosis. |
| **Tests (`tests/`)** | Acceptance. | Test suite and synthetic corpus. |
| **Repository hygiene** | Decision to strip course-specific content and plans. | Neutral corpus, public/private ignore split, docs. |

---

## 7. Critical Reflection and Key Learnings

1. **The agent is part of the system.** Correct tools were not enough; most problems were agent behaviors (sweeping, insisting, inventing) visible only in real transcripts.
2. **Limits in the server beat instructions.** A rule in `AGENTS.md` alone did not stop the agent from sweeping documents; a server-side budget did.
3. **Measure before believing.** Logging each call (tool, arguments, size, time, never text) turned impressions into per-question numbers and exposed regressions such as the 34-call v4 round.
4. **Cost and coverage trade off.** Cutting tool output by roughly 50–70% shortened some answers; the page budget stays provisional until tested on new questions.
