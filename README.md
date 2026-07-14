# blast-agent — PR blast-radius over a three-layer knowledge graph

A working agent that (1) autonomously crawls a real web application, (2) ingests its product documentation into structured requirements, (3) builds a Neo4j graph connecting **requirements ↔ observed UI ↔ implementation code**, and (4) explains the blast radius of a real pull request in a report a QA lead can act on.

- **Target application:** [Gitea](https://github.com/go-gitea/gitea), self-hosted and built from source at the pinned revision `daf581fa892320f5d495b4073d6812b0ad8ddfc8` — so the crawled UI is provably produced by the indexed code.
- **Analyzed PR:** [go-gitea/gitea#37045](https://github.com/go-gitea/gitea/pull/37045) — "Refactor issue sidebar and fix various problems" (21 files).
- **Design document:** [`docs/design.md`](docs/design.md) · **Frozen scope:** [`docs/scope.md`](docs/scope.md) · **Sample report:** [`examples/sample-output/blast-radius.md`](examples/sample-output/blast-radius.md)

## Prerequisites

> Setting up a brand-new machine? [`docs/setup.md`](docs/setup.md) is the full from-zero checklist (system tools, both Neo4j paths, gotchas).

| Tool                                                  | Used for                                                  | Notes                                                                                                                                                                                                                                   |
| ----------------------------------------------------- | --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python ≥ 3.12 +[uv](https://docs.astral.sh/uv/)       | the agent itself                                          | `uv sync` installs everything                                                                                                                                                                                                         |
| Go ≥ 1.25 and Node ≥ 22.6 with pnpm ≥ 10           | building Gitea at the pinned SHA                          | Go auto-downloads the exact toolchain (Node < 22.6 fails:`--experimental-strip-types is not allowed in NODE_OPTIONS`)                                                                                                                 |
| Neo4j 5                                               | the knowledge graph                                       | `docker compose up -d neo4j` (Docker Engine via apt/get.docker.com) **or** native `apt install neo4j`. macOS: `brew install neo4j`. Windows: Docker Desktop with the WSL2 backend, run from inside your WSL2 Ubuntu shell. |
| An LLM API key (Anthropic preferred, Gemini fallback) | LLM stages (crawl action ranking, requirement extraction) | see`.env.example`                                                                                                                                                                                                                     |

```bash
uv sync
uv run playwright install chromium
cp .env.example .env       # then fill in ANTHROPIC_API_KEY (or GEMINI_API_KEY) and NEO4J_PASSWORD
```

## End-to-end walkthrough

```bash
# 1. Build the target app at the pinned SHA (one-time, ~5–10 min)
bash scripts/bootstrap_gitea.sh

# 2. Start + deterministically seed the demo instance (rerun anytime to reset)
bash scripts/reset_demo.sh          # serves http://localhost:3000

# 3. Crawl the three scoped user flows (LLM-driven; add --no-llm for the
#    deterministic fallback policy — completes all flows without an API key)
uv run blast-agent crawl --run-id my-run

# 4. Ingest the documentation snapshot into requirements (LLM, cached)
uv run blast-agent ingest-docs --run-id my-docs

# 5. Index the pull request (deterministic)
uv run blast-agent index-code

# 6. Generate cross-layer trace links with confidence bands
uv run blast-agent link --run-id my-run --docs-run-id my-docs

# 7. Load everything into Neo4j (idempotent) and record absence observations
uv run blast-agent load-graph --run-id my-run --docs-run-id my-docs

# 8. The deliverable: the blast-radius report for PR #37045
uv run blast-agent analyze-pr --run-id my-run --docs-run-id my-docs
# -> data/runs/my-run/report/blast-radius.md

# 9. Score the run against the hand-labeled gold set (exits non-zero on failure)
uv run blast-agent eval --run-id my-run --docs-run-id my-docs
```

`bash scripts/smoke_test.sh` runs the unit suite, checks the demo app, and runs the integration suite in one command.

## What each stage produces

Every stage writes versioned, schema-validated JSON records (Pydantic v2, `extra="forbid"`, content-addressed IDs) under `data/runs/<run-id>/records/`:

| Stage       | Records                                                     | Extra artifacts                                                                      |
| ----------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| crawl       | `screens`, `elements`, `interactions`, `flows`      | DOM snapshots, full-page screenshots,`decisions.jsonl` (per-step policy rationale) |
| ingest-docs | `requirements` (each with a verbatim source quote)        | LLM response cache in`data/cache/llm/`                                             |
| index-code  | `code_symbols`, `pr_changes`                            | immutable diff snapshot in`data/raw/code/`                                         |
| link        | `trace_links` (confidence, method, evidence, review band) |                                                                                      |
| load-graph  | `absences`                                                | the Neo4j graph itself                                                               |
| analyze-pr  | `impacts`                                                 | `report/blast-radius.md`                                                           |

## Offline / fixture mode

The public app or LLM being unavailable does not brick the pipeline:

- `--no-llm` crawls with the deterministic fallback policy (all three flows pass);
- LLM responses are cached by content hash — reruns and replays are free and offline;
- committed fixtures (`tests/fixtures/`) exercise every stage: the real PR diff, real docs snapshots, canonical contract records, and the hand-labeled gold set;
- `uv run pytest tests/unit -q` needs nothing external; `tests/integration` auto-skips any suite whose dependency (Gitea, Neo4j) is not running.

## Repository map

```
src/blast_agent/
  contracts/    frozen Pydantic models shared by every stage
  crawl/        Playwright extractor, state identity, agent loop, policies
  ingest/       docs snapshot loader, segmenter, LLM requirement extractor
  code_index/   PR diff parsing, symbol extraction, UI-anchor mining
  linking/      candidate generation + evidence-deduped confidence scoring
  graph/        Neo4j schema/constraints, idempotent writer, absence, queries
  reasoning/    deterministic blast-radius traversal + report renderer
  evals/        gold-set metrics, run-to-run stability, eval CLI
docs/           design.md, scope.md, plan.md, demo-script.md
scripts/        bootstrap_gitea.sh, reset_demo.sh, smoke_test.sh
templates/      blast_radius.md.j2
tests/          unit, integration, fixtures (incl. goldens/gold_set.json)
```

## Honest limitations (short version — §9 of the design doc has the full list)

Symbol extraction is regex-heuristic, not AST; `HANDLED_BY` coverage is sparse because route registrations live outside the PR's changed files; requirements come from three documentation pages; LLM stages degrade to a deterministic fallback policy rather than failing when the provider is rate-limited or unavailable. Every unmapped change and unobserved requirement is reported explicitly rather than silently dropped.
