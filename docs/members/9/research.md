# Research: technical documentation generation (Member 9, written ahead of Sprint 9)

The documentation agent writes a README, API docs, architecture and code summaries from the **actual** repository,
and proves that every technical claim is grounded in the code. Each topic below ends with **→ plan**: what it means
for Sprint 9. A working prototype of the core (facts → grounded draft → grounding check) is in `samples/docgen/`.

## 1. Code summarization
- Classic summarization picked important identifiers and comments (Haiduc et al., 2010). Neural models learned
  from code–comment pairs (CodeSearchNet, Husain et al., 2019). LLMs now summarize well with a few project examples
  (Ahmed & Devanbu, 2022).
- Whole repositories do not fit in one prompt, so tools summarize **bottom-up**: function → file → module → repo
  (map-reduce). RepoAgent (Luo et al., 2024) also keeps summaries up to date when the code changes.
- Docstrings that already exist are better evidence than a model's guess.

**→ plan:**
- `summarize.py`: per-function summaries with `fast`, then module and repo summaries with `reasoner`.
- Each summary must cite the symbols it describes, and the citations are checked against the facts.
- Prefer the existing docstring when present.

## 2. Architecture extraction
- **Import and call graphs** come straight from the AST. Module clustering (Bunch, Mancoridis et al., 1998) groups
  modules that depend on each other.
- **C4 model** (Simon Brown): context → containers → components → code. Generated docs fit the component level.
- **Mermaid** diagrams are text, so they live in Markdown, diff cleanly and can be checked like any other claim.

**→ plan:**
- `architecture.py`: import graph → Mermaid component diagram (the prototype's `--mermaid` already does this) +
  clusters by top-level package.
- Every edge in the diagram must exist in the import graph (item 9.2 acceptance).

## 3. API documentation
- FastAPI produces an **OpenAPI** document (`app.openapi()`) from the code itself. That is the most reliable source
  for endpoints, parameters and models.
- Tools: Sphinx autodoc, mkdocs + mkdocstrings, pdoc: all generate reference docs from docstrings.

**→ plan:**
- `api_docs.py`: routes from the AST (works without importing the app) **and** from OpenAPI when the app can be
  imported safely (in the sandbox); OpenAPI → Markdown tables.
- Acceptance "endpoints = code endpoints" is checked by the grounding checker's ENDPOINT rule.

## 4. What a good README contains
- GitHub READMEs most often cover what the project is, how to install and run it, how to use it, and how to
  contribute (Prana et al., 2019). The Diátaxis framework (Procida) separates tutorials, how-to guides, reference
  and explanation.
- Common documentation problems are missing, outdated and incorrect content (Aghajani et al., 2019).

**→ plan:**
- `readme.py`: fixed sections (What, Run, Configuration, Endpoints, Code, Tests) filled from facts. The model writes
  only the prose (the prototype's `draft_readme.py` is grounded 80/80 by construction).
- Report sections (item 9.8) follow the `RequirementSet` deliverables list.

## 5. Accuracy: grounding and hallucination detection
- Models invent plausible details. Surveys of hallucination (Ji et al., 2023) separate claims that contradict the
  source from claims that have no source.
- **FActScore** (Min et al., 2023) splits text into atomic facts and checks each one: the same idea as a claim table.
- Code-specific hallucinations include **packages that do not exist** (Spracklen et al., 2025) and wrong APIs.
- In docs, the dangerous errors are concrete: a technology that is not used, an endpoint, flag or environment
  variable that does not exist, a wrong port, a command that fails.

**→ plan:**
- `grounding.py`, two layers:
  1. **Rules** for concrete claims, matched against the facts DB. The prototype catches 31/31 seeded false claims
     across 8 types with 0 false alarms on 63 correct claims.
  2. **A model** (claim → evidence from code → verdict) for behaviour claims ("nicknames are case-sensitive"). The
     prototype misses 3/3 of these, as expected.
- Ungrounded claims become issues for the M4 Refiner loop. The accuracy report lists each one with its reason.

## 6. Doc–code drift
- Comments and docs go stale when code changes. Code-comment inconsistencies are common and cause bugs (Wen et al.,
  2019). @tComment (Tan et al., 2012) checked comments against code automatically.
- Docs-as-code: keep docs in the repo, run checks in CI, and run code examples (doctest).

**→ plan:**
- `docs.update` is triggered by `code.completed`: re-extract facts, re-run the grounding check on the existing docs,
  and regenerate only the sections whose facts changed.
- Documented commands and snippets run in Member 8's sandbox (item 9.7).

## 7. Evaluating generated docs
- BLEU-style overlap scores track human judgement poorly for code summaries (Roy et al., 2021). Use task-based
  metrics instead.
- **Faithfulness** = grounded claims / all claims. **Coverage** = public symbols documented / public symbols (as
  tools such as interrogate measure for docstrings). **Seeded-error detection** rate per claim type.
- Plus a small human rubric (correct, complete, readable, useful) on 5 documents.

**→ plan:** item 9.12 reports all four. The prototype's seeded set is the start of the seeded-error part, but it
must be extended with documents a model wrote for unseen repos, because the rules were tuned on these seeds.

## 8. Platform docs and the one-command demo (items 9.15–9.20)
- Twelve-factor apps keep configuration in the environment, so the full config reference can be generated from
  the settings class.
- Docker Compose health checks (`depends_on: condition: service_healthy`) make "wait until healthy" reliable.
- A pre-flight check should say what is wrong *and* how to fix it.

**→ plan:**
- `make demo` = pre-flight (Ollama, model pulled, free RAM, free ports) → infra up → wait healthy → migrations →
  seed → API + agent host + frontend. `make demo-replay` does the same with Ollama stopped.
- **Finding from the prototype:** on our own backend the extractor finds 190 modules and 59 routes in 0.3 s, but
  only 5 environment variables. The platform reads settings through pydantic-settings (`HMAP_` prefix), so the
  real extractor must read `BaseSettings` fields + `env_prefix` before it can write the config reference (item 9.17).

## 9. Fitting on the laptop
- Facts-first generation keeps prompts small: the model writes prose around a few facts, not the whole repository.
- Per-function summaries suit `fast`; the architecture narrative suits `reasoner`.
- The extractor and the rule checker use no model at all, so the grounding gate costs nothing and works offline.

## References
Haiduc et al. 2010 (source code summarization) · Husain et al. 2019 (CodeSearchNet) · Ahmed & Devanbu 2022
(few-shot project-specific code summarization) · Luo et al. 2024 (RepoAgent) · Mancoridis et al. 1998 (Bunch
clustering) · Brown, the C4 model · OpenAPI Specification · Prana et al. 2019 (categorizing README content) ·
Procida, Diátaxis · Aghajani et al. 2019 (software documentation issues) · Ji et al. 2023 (hallucination survey) ·
Min et al. 2023 (FActScore) · Spracklen et al. 2025 (package hallucinations) · Wen et al. 2019 (code-comment
inconsistencies) · Tan et al. 2012 (@tComment) · Roy et al. 2021 (metrics for code summarization) · The Twelve-Factor
App.
