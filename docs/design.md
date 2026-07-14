# Design document — Blast-radius agent over a three-layer knowledge graph



Target: Gitea self-hosted at commit daf581fa · PR under analysis: go-gitea/gitea#37045#37045 · Graph: Neo4j 5 · All numbers in this document are measured from committed runs, not estimates.

---

## 1. Executive summary and the chosen vertical slice

This system crawls a live web application, ingests its product documentation, indexes a real pull request, joins all three in a Neo4j graph, and emits a blast-radius report a QA lead can act on without reading code.

The brief is explicit that 16 hours cannot fund equal depth everywhere. I chose one **deep vertical slice**: three issue-tracking user flows in a self-hosted Gitea, one documentation section, one real PR — and invested the reclaimed depth in the properties that make the output *trustworthy* rather than broad:

- **Version fidelity.** The crawled UI is produced by exactly the code that is indexed. Gitea is built from source at the PR's base SHA (`daf581fa`) and crawled locally. Every record carries `source_revision`.
- **Provenance on every claim.** Each report sentence traces to graph paths of typed records with stable content-addressed IDs; every LLM decision is logged with its rationale; every requirement carries a verbatim quote from the docs snapshot.
- **Honest uncertainty.** Links carry confidence with a documented combination rule and a three-band review policy; changes that cannot be mapped to UI appear in an explicit "Not mapped" section; requirements that *should* be visible but were not observed become scoped `AbsenceObservation` records, not silent nulls.

Measured end state: 14 screens / 523 UI elements / 3 flows crawled; 46 changed code symbols from the real 21-file PR; 116 evidence-carrying UI↔code links; a 7-finding blast-radius report whose highest-severity finding correctly identifies the issue-creation form and flow; and an evaluation harness in which the system scores 1.0 link precision and 1.0 link recall against a hand-labeled gold set.

## 2. Target, PR, flows, and scope cuts

Full details are frozen in [`docs/scope.md`](scope.md); the decisions that matter:

**Why Gitea.** The assignment's own examples (Amazon, GitHub) are traps: their deployed code is closed, so the Code layer cannot be honestly mapped. The viable class is an open-source web app whose deployment you control. Gitea additionally offers server-rendered Go templates whose locale keys resolve to visible strings — a deterministic bridge between DOM and code — and it runs from a single binary on SQLite, so demo state is wiped and re-seeded byte-identically between runs.

**Why PR #37045** ("Refactor issue sidebar and fix various problems", merged 2026-03-31, 21 files). It spans every stratum we index — Go models, web handlers, server templates (including the site-wide navbar), frontend TypeScript — and its blast radius overlaps two of our three crawled flows while leaving the third (login) as a precision control. The analysis is framed pre-merge: crawl and index at the base SHA, predict what the PR endangers.

**Flows.** F1 sign-in (control), F2 create an issue, F3 open an issue and subscribe to notifications. F2/F3 are directly hit by the PR; F1 is touched only through the shared navbar.

**Cuts (Part B prompt 9 — declared, not hidden):**

| Cut                                                              | Why                                                                                              | Consequence                                                                               |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| One app, one docs section (3 pages), one PR                      | Fidelity beats breadth in 16h                                                                    | Absence claims are scoped to the ingested section only                                    |
| Regex/text heuristics instead of tree-sitter AST                 | AST costs setup time; heuristics + confidence caps are honest                                    | Symbol spans can be slightly off; capped confidence, never auto-accept on structure alone |
| No human review*queue file*                                    | The three-band policy exists and is enforced; the replayable decisions file did not make the cut | `needs_review` links are consumed as "pending" downstream; reviewing them is manual     |
| No LLM prose in the report                                       | Deterministic template = zero hallucination risk in the deliverable a QA lead reads              | Report language is plainer than an LLM could write — an acceptable trade                 |
| Single browser/viewport, anonymous+one demo user, English locale | Repeatability                                                                                    | Coverage claims are scoped accordingly                                                    |
| CSS/Markdown changes indexed at file level only                  | No symbol model for them                                                                         | They appear as explicit unmapped entries in the report                                    |
| No run-manifest module                                           | Run directories + stable IDs + committed fixtures cover reproducibility for this scope           | Replay is by CLI arguments, not by manifest file                                          |

## 3. Architecture and agent decomposition (Part B prompt 5)

Seven stages, each reading and writing versioned Pydantic contracts (`src/blast_agent/contracts/`) with `extra="forbid"` and content-addressed IDs (`stable_id(kind, *natural_key)` — SHA-256 over normalized natural keys, so identical observations get identical IDs across runs):

```
scope.md ──► crawl ──► ScreenState/UIElement/Interaction/UserFlow ─┐
         ──► ingest ──► Requirement (with SourceSpan) ─────────────┼─► linking ─► TraceLink ─► Neo4j ─► blast-radius ─► report.md
         ──► code-index ──► CodeSymbol/PullRequestChange ──────────┘                    ▲
                                                                        AbsenceObservation
```

The contracts were frozen first (hour 1) and every stage was developed and tested against fixtures before real data existed. That is also why the stages compose: the graph loader and the evaluator do not care whether records came from a live crawl or a fixture.

**Where the boundaries are and why.** Each boundary is a place where evidence changes type: browser observations → typed records; prose → requirements with quotes; diff → symbols with line spans; records → scored links; links → graph; graph → findings. Persisting at every boundary means any stage can be re-run, cached, or replaced (including by a human) without re-running upstream stages.

**The crawler is an agent, not a macro.** Its loop is: observe (extract screen + elements) → generate candidate actions → *select* → execute → detect state change → repeat. Selection is the only stochastic step: an LLM receives the goal, current route/title, the numbered non-blocked candidates, and the recent trajectory, and returns an action index **with a rationale that is logged** to `decisions.jsonl`. A real logged example from run `run-m3-llm`:

> *"To open issue number 1 in demo/demo-repo, I first need to navigate to the repository. Candidate 6 is a link to demo/demo-repo."*

Everything around the selection is deterministic: candidate generation, the safety filter (host allowlist, route allow/deny lists, destructive-keyword blocking), deduplication, budget enforcement (≤15 actions/flow, ≤80/run, wall-clock deadline), execution, and state identity. The two failure modes the brief warns about are both addressed structurally: it is not a recorded macro (the LLM genuinely chooses from live observations; the decision log proves it), and it is not a prompt chain dressed up as an agent (the LLM cannot execute, cannot bypass safety, cannot invent fill values — a fixed `FILL_VALUES` map owns credentials and form text).

**Deterministic fallback, honestly labeled.** A scripted recipe policy (`FallbackPolicy`) can complete all three flows with zero LLM calls. It exists for demos, evaluation baselines, and LLM outages — and the system engages it automatically mid-run if the LLM becomes unavailable, labeling every such decision `source: deterministic` with an `llm-unavailable-fallback` rationale prefix. It is a safety net, not the agent, and `UserFlow.discovery_source` records which policy actually drove each flow.

## 4. Deterministic vs. LLM-driven (Part B prompt 5, continued)

| Stage                                                  | Deterministic            | LLM                    | Rationale                                                              |
| ------------------------------------------------------ | ------------------------ | ---------------------- | ---------------------------------------------------------------------- |
| Crawl — candidates, safety, dedup, budgets, execution | ✅                       | —                     | Safety and reproducibility must not depend on model behavior           |
| Crawl — next-action selection                         | fallback                 | ✅ (logged rationale)  | Judgment under an open action space is the LLM's comparative advantage |
| Docs — snapshot, segmentation, offsets                | ✅                       | —                     | Provenance must be exact                                               |
| Docs — requirement extraction                         | validation               | ✅ (structured output) | Turning prose into atomic testable statements is judgment              |
| Code/PR indexing                                       | ✅ (heuristics, labeled) | —                     | Diff and symbol facts should never be "creative"                       |
| Linking + confidence                                   | ✅                       | —                     | Auditable signals beat opaque similarity at this scale                 |
| Graph load, absence                                    | ✅                       | —                     | Idempotency requirement                                                |
| Blast-radius traversal, severity                       | ✅                       | —                     | The core claim of the system must be reproducible                      |
| Report rendering                                       | ✅ (Jinja2)              | —                     | Zero-hallucination deliverable                                         |

Two guardrails on every LLM output: **schema-validated structured output** (Gemini `responseSchema`; unparseable → typed error, never partial acceptance) and **evidence gating** — an extracted requirement is discarded as a recorded *reject* unless its `source_quote` appears verbatim (whitespace/case-normalized) in the source segment. Hallucinated requirements do not merely score low; they cannot enter the dataset.

All LLM responses are cached by content hash (`data/cache/llm/`), which makes reruns free, offline-replayable, and — during this build — resilient to a genuinely erratic free-tier quota: ingestion progress is monotonic across retries because completed segments are never re-billed.

**Provider adapter, measured.** The LLM layer is a two-provider adapter (Gemini and Anthropic, selected by env) behind one `generate_json(prompt, schema)` interface, and the build produced a concrete model-quality datapoint: with a small model (Haiku-class) driving the crawl policy, two of three flows completed and the third exposed two real harness bugs (an answer-before-reasoning schema ordering, and unlogged stop decisions — both fixed); with a mid-tier model (Sonnet-class), **all three flows completed autonomously, 13/13 decisions LLM-sourced** (run `run-m3-showcase-final`). Requirement extraction ran on the small model: 40 requirements from 22 segments with **zero verbatim-quote rejects**. Policy quality scales with model choice; the architecture doesn't change.

## 5. Graph schema, example query, and the absence model (Part B prompt 6)

**Nodes:** `Requirement`, `Screen`, `UIElement`, `Interaction`, `UserFlow`, `CodeFile`, `CodeSymbol`, `PullRequest`, `Change`, `CrawlRun`, `AbsenceObservation` — each mirroring one contract, each MERGE-keyed on its stable ID (uniqueness constraints in `graph/schema.py`; loading the same run twice changes zero counts, verified in integration tests).

**Edges:** `(Screen)-[:CONTAINS]->(UIElement)`, `(Screen)-[:TRANSITIONS_TO]->(Screen)`, `(Interaction)-[:USES]->(UIElement)`, `(UserFlow)-[:HAS_STEP {order}]->(Interaction)`, `(Screen)-[:OBSERVED_IN]->(CrawlRun)`, `(CodeFile)-[:DECLARES]->(CodeSymbol)`, `(PullRequest)-[:CHANGES]->(Change)-[:TOUCHES]->(CodeSymbol)`, and the cross-layer link edges — `(UIElement)-[:RENDERED_BY]->(CodeSymbol)`, `(Screen|UIElement)-[:HANDLED_BY]->(CodeSymbol)`, `(Requirement)-[:IMPLEMENTED_BY]->(UIElement|Screen)` — every link edge carrying `{confidence, method, evidence[], review_status, link_id}` so no cross-layer hop is ever opaque.

**The query the schema is justified against** (the system's core question — "what does this PR endanger, and how sure are we?"):

```cypher
MATCH (pr:PullRequest {number: $pr})-[:CHANGES]->(ch:Change)-[:TOUCHES]->(sym:CodeSymbol)
OPTIONAL MATCH (el:UIElement)-[r:RENDERED_BY|HANDLED_BY]->(sym)
  WHERE r.review_status IN ['auto_accepted','needs_review']
OPTIONAL MATCH (sc:Screen)-[:CONTAINS]->(el)
OPTIONAL MATCH (flow:UserFlow)-[:HAS_STEP]->(:Interaction)-[:USES]->(el)
OPTIONAL MATCH (req:Requirement)-[ri:IMPLEMENTED_BY]->(el)
  WHERE ri.review_status IN ['auto_accepted','needs_review']
RETURN ch, sym, el, sc, flow, req, r.confidence
```

One traversal reaches all three layers with confidence available at each hop — that is the property the schema was designed for, and why link metadata lives on edges rather than in side tables.

**Absence is a record, not a missing edge.** A missing `IMPLEMENTED_BY` edge cannot distinguish "searched and not found" from "never looked". So when a requirement has no accepted or review-pending link after linking, the system writes:

```
(Requirement)-[:HAS_ABSENCE]->(AbsenceObservation {search_scope, expected_evidence[], confidence, explanation})
                -[:ASSESSED_IN]->(CrawlRun)
```

The observation names *what was searched* (this run's screens, elements, and links), *what evidence was expected* (the requirement's acceptance clues), and a confidence — making the claim time-bound and falsifiable: a later, deeper crawl can find the feature without rewriting history, because the old observation stays attached to the old run. The docs sources were deliberately chosen to exercise this: organization-wide labels and issue-template autofill are documented behaviors that our crawl scope genuinely cannot observe, so the gold set *requires* the system to report them absent rather than hallucinate coverage.

## 6. Trace links, confidence, ambiguity, and the human threshold (Part B prompt 7)

**Candidate generation is anchor-first.** Code symbols carry mined UI anchors: template locale keys resolved to English strings (`locale:repo.issues.create` → `text:Create Issue`), href literals, CSS ids, route registrations. Each anchor type is an independent matcher against crawl records with a fixed weight: `href-exact` 0.70, `route-exact` 0.75, `text-exact` 0.65, `css-id` 0.55, and weaker requirement-clue signals (0.30–0.60).

**Confidence combination respects evidence identity.** Signals are first deduplicated by their underlying evidence string — two heuristics that both fire on the string "Create Issue" count once, at the max weight — then combined by noisy-or (`1 − Π(1 − wᵢ)`). This directly implements the rule that confidence must not rise merely because several heuristics reuse the same evidence, and it is unit-tested.

**Three outcomes, one threshold that means something:**

- `>= 0.85` **and** at least one strong anchor kind → `auto_accepted`;
- `0.55–0.84`, or ≥0.85 without a strong anchor → `needs_review` — *this is where the system stops and asks a human*;
- `< 0.55` → `unresolved` (retained as a candidate, usable as absence evidence, never traversed).

The real run is instructive: all 116 UI↔code links landed in `needs_review`, because most carry a single signal (98 `text-exact`, 13 `css-id`, 5 two-signal at 0.84). The system is *designed* to refuse auto-acceptance on single-heuristic evidence — precision 1.0 against the gold set's forbidden links shows the abstention is doing its job, and the report consumes `needs_review` links with their confidence displayed rather than pretending certainty. When the agent cannot map something at all — the PR's Go model/handler changes, its CSS files — those become the report's "Not mapped to UI" section with per-file reasons, never forced links.

The same abstention logic covers the other ambiguity direction (PRD feature not found in the UI): that is exactly the `AbsenceObservation` path of §5.

## 7. Blast-radius algorithm and report design

Traversal is the Cypher of §5, restricted to confidence-qualified edges. Findings aggregate per changed symbol; severity is a documented deterministic rule: **high** = an affected user flow exists and the best supporting edge is ≥0.8; **medium** = affected UI elements exist; **low** = symbol changed but weak mapping. Finding confidence is the max supporting-edge confidence, displayed as a percentage. Every finding stores its full paths (`change → symbol → element → screen → flow` IDs), and every path is persisted as an `ImpactFinding` record.

The report (Jinja2, `templates/blast_radius.md.j2`) is ordered for a QA reader: what changed → executive summary → impacts by risk → flows to re-test → requirements at risk → **not mapped to UI** → run identifiers. Presentation rules learned from reviewing the first real render: element names deduplicated with counts ("Notifications (12 places)"), names whitespace-sanitized and truncated, evidence capped at five paths with a pointer to the full records. The measured report for PR #37045: 7 findings (1 high, 6 medium), 14 explicitly unmapped changes. The high finding — the new-issue form's Title/Create Issue elements and the create-issue flow at 84% — is what a human reviewer of this PR would name first.

## 8. Evaluation, the gold set, and the 100-run question (Part B prompt 8)

**Ground truth.** A hand-labeled gold set (`tests/fixtures/goldens/gold_set.json`, authored independently of system output, provenance-stamped): 5 must-extract requirements, 5 must-exist links, 2 must-NOT-exist links, required impact routes/flows/unmapped files, 2 expected absences, and thresholds.

**Measured results** (deterministic pipeline, run `run-m3-nollm-4` + docs run `run-m4-docs`): link must-not precision **1.0**, link recall **1.0** (5/5), impact checks **pass** (both required routes, both required flows, CSS files correctly unmapped, ≥3 findings), requirement recall **0.8**, both expected absences detected. `blast-agent eval` exits non-zero on any threshold failure, so evaluation can gate CI.

**Fresh-checkout reproduction.** The entire README walkthrough was rehearsed from a clean `git clone` into an empty Neo4j database: Gitea rebuilt at the pin, all three flows crawled LLM-autonomously, 61 requirements extracted (0 quote rejects), and the eval passed every active check (requirement recall 1.0 on that run). The rehearsal surfaced and fixed three reviewer-blocking gaps (missing provider env docs, gitignored snapshots now restored from committed fixtures, an output-token ceiling) — which is the point of rehearsing.

**"If we ran it 100 times, which runs were correct?"** Correctness is defined *before* measuring:

1. **Hard constraints per run** — zero must-not-link violations; zero report claims without a recorded graph path (structurally guaranteed: the renderer can only print findings that carry paths); all required gold entities recovered.
2. **Stage separation** — deterministic stages (linking, graph, traversal, report) must replay byte-stably from fixed inputs; content-addressed IDs make drift detectable as ID churn. Only the two LLM stages may vary.
3. **Distributional metrics across the 100 runs** — pairwise Jaccard similarity of discovered route sets, link triples, and impact signatures (`stability.py` implements this for N runs); report min/mean, and the abstention rate (share of links landing in `needs_review`). A run is *correct* if it satisfies (1); the *system* is stable if (3) stays above the threshold (0.9 gold-set default).
4. **Separating model noise from environment drift** — frozen fixtures + the LLM cache distinguish the two: cached replays isolate environment; uncached runs with fixed inputs isolate the model.

The two policies bound the stability spectrum empirically: the deterministic fallback gives a reproducible floor (three consecutive full runs produced identical flow outcomes during this build), while LLM-driven runs are measured against it.

## 9. Failure modes, safety, and limitations

Observed during this build (not hypothetical): free-tier LLM quota collapsing mid-crawl — absorbed by three designed layers (client-side call spacing, long-backoff retries, per-step fallback with labeled provenance; the run completed and said so honestly). State-identity churn from relative timestamps ("1 minute ago") defeating naive screen dedup — fixed by keying action dedup on URL path per flow, a bug only visible because every decision is logged. Locator ambiguity (navbar "Sign In" vs. submit button) — fixed by role-scoped, exact-name-first resolution.

Known limitations: heuristic symbol spans (no AST); `HANDLED_BY` links sparse because route registrations live outside the PR's changed files; requirement extraction quality bounded by three docs pages; a single seeded demo state; no visual regression signal (screenshots are evidence only); the free-tier LLM makes live runs slow (mitigated by cache + fallback, and swappable for a paid key by one env var).

Safety: the crawler runs against a local instance under an allowlist; destructive-keyword and route-prefix blocking are deterministic; external links are recorded as evidence but never followed; the LLM never generates form input; no real credentials exist anywhere in the system.

## 10. With another week (Part B prompt 10)

1. **Close the review loop and harden mapping evaluation.** A replayable `review-decisions.yaml` consumed by linking (human verdicts on `needs_review` links survive reruns), a 30–50-item labeled link set beyond the current gold five, and per-band precision/recall curves to tune the 0.85/0.55 thresholds empirically. Highest value because trust in links is what every downstream claim rests on — and the current 116-link review queue is the visible bottleneck.
2. **Route↔template↔handler resolution at the pinned SHA.** Index Gitea's route registrations and template-render calls once (not only changed files), giving dense `HANDLED_BY` edges — this converts most of the report's "Not mapped to UI" Go entries into real findings, the largest single recall gap.
3. **Incremental multi-PR graph.** Versioned upserts keyed by (entity, revision) so consecutive PRs update one living graph; blast-radius over a PR *series* plus crawl-diffing between base and head builds — turning the prototype into the continuously-updated intelligence layer the product story implies.

## Appendix: system-generated artifacts backing this document

- `data/runs/run-m3-nollm-4/` — crawl records, decision log, screenshots (deterministic full pass).
- `data/runs/run-m3-llm/decisions.jsonl` — LLM-policy decisions with rationales.
- `data/runs/code-index/records/` — 46 symbols, 21 changes from PR #37045.
- `data/runs/run-m3-nollm-4/report/blast-radius.md` — the committed sample report.
- `blast-agent eval` output — gold-set verdict (link P 1.0 / R 1.0, impact pass).
