# Frozen scope — target, PR, flows, cuts

Status: **frozen 2026-07-14**. Every artifact in this repository refers to the
application, revision, documentation, and pull request pinned below. Changing
any of these requires updating this file first.

## Target application

| Item                                 | Value                                                                                                                 |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| Application                          | Gitea (self-hosted Git service)                                                                                       |
| Repository                           | https://github.com/go-gitea/gitea                                                                                     |
| Pinned revision (crawl + code index) | `daf581fa892320f5d495b4073d6812b0ad8ddfc8` (base of PR #37045, main branch, 2026-03)                                |
| Hosting                              | Self-hosted locally, built from source at the pinned SHA (`TAGS=sqlite`), SQLite backend, `http://localhost:3000` |
| Toolchain at pin                     | Go 1.26.1 (auto-downloaded via GOTOOLCHAIN), Node ≥ 22.6, pnpm ≥ 10                                                 |

Why Gitea: the deployed UI is produced by exactly the code we index (built
from the pinned SHA); server-rendered Go templates give strong deterministic
UI↔code anchors (template paths, locale keys, CSS ids/classes, route
registrations in `routers/web/`); it runs with zero external services; and it
has real, well-labeled PR history. Self-hosting removes crawl/ToS risk and
makes state resettable (delete the SQLite db + re-seed).

## Pull request under analysis

| Item         | Value                                                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------------------------------------ |
| PR           | [go-gitea/gitea#37045](https://github.com/go-gitea/gitea/pull/37045) — "Refactor issue sidebar and fix various problems" |
| Merged       | 2026-03-31                                                                                                               |
| Base SHA     | `daf581fa892320f5d495b4073d6812b0ad8ddfc8`                                                                             |
| Head SHA     | `e7095e0957a6b46273c2c21afff3450543cb8257` (fork `wxiaoguang/gitea`)                                                 |
| Merge commit | `6ca557371882871ab994b51df204942b45b5cf3b`                                                                             |
| Size         | 21 files, +314/−176                                                                                                     |

Why this PR: it spans all three code strata we index — Go models
(`models/issues/issue_project.go`, `models/project/column.go`), web handlers
(`routers/web/repo/issue_new.go`, `issue_page_meta.go`), server templates
(issue new form, issue view sidebar, watching, **site-wide navbar**), and
frontend TS (`repo-issue-sidebar*.ts`). Its effects are directly visible in
the crawled flows below, and the navbar change gives a nice cross-cutting
impact example. The analysis is framed **pre-merge**: the app is crawled and
indexed at the *base* SHA, and the system predicts what the PR puts at risk.

## Product documentation source

- Primary: Gitea official docs, **Issues & Pull Requests** section for the
  1.27 line (matches the pinned main-branch revision):

  - https://docs.gitea.com/1.27/usage/issues-prs/labels
  - https://docs.gitea.com/1.27/usage/issues-prs/issue-pull-request-templates
  - https://docs.gitea.com/1.27/usage/issues-prs/automatically-linked-references

  (The `issues-prs` index page was dropped after snapshotting: it is a thin
  category card list with no testable statements. The three chosen pages span
  covered / partially observable / not-observable-in-scope behavior, which
  exercises the absence model with real material.)
- Snapshot policy: pages are fetched once, stored immutably under
  `data/raw/docs/`, and all requirement extraction runs against the snapshot,
  never the live site.

## Selected user flows (crawl targets)

1. **F1 — Sign in**: landing page → sign-in form → authenticated dashboard.
   Mostly a control flow; only the navbar templates from the PR touch it.
2. **F2 — Create an issue**: repo home → issue list → "New Issue" → fill
   title/body → set sidebar metadata (label, milestone, assignee) → submit.
   Directly hit by the PR (new form, sidebar, handlers).
3. **F3 — Triage an existing issue**: issue list → open issue → sidebar
   interactions (add/remove label, watch/unwatch subscription). Directly hit
   by the PR (view sidebar, watching template, sidebar TS).

Seed state (created deterministically before each crawl by a reset script):
one demo user, one org, one repository with 2–3 issues, 2 labels, 1 milestone.

## Crawl boundaries

- Allowed host: `localhost:3000` only. Allowed route prefixes: `/`,
  `/user/login`, `/user/logout`, `/{demo-org}/{demo-repo}/**`, `/issues`,
  `/notifications`.
- Prohibited: `/admin/**`, `/user/settings/**`, any repo settings/deletion,
  migrations, webhooks, releases, wiki edits, any non-demo account.
- Budgets: ≤ 80 actions, ≤ 8 transitions deep, ≤ 15 minutes, one browser
  (Chromium), one viewport (1440×900), English locale only.
- Credentials: local demo account only; never a real account.

## Code-index scope

Only: the 21 files changed by PR #37045, plus the route registrations,
templates, and locale entries reachable from flows F1–F3. No whole-repo
indexing.

## Explicit cuts (defended in docs/design.md)

- One app, one docs section, one PR — no generality across targets.
- No authenticated-state variety (single demo user), no OAuth, no 2FA.
- No visual-diff/screenshot ML; screenshots are evidence, not features.
- Frontend TS is indexed by import/selector heuristics, not a JS bundler
  graph; confidence is capped accordingly.
- No graph UI, no distributed execution, no self-healing selectors, no CI
  deployment of the target app.
- Requirements come from the issues-PRs docs section only; Gitea has far more
  documentation than we ingest, and absence claims are scoped to this section.

## Known risks

- Building Gitea at the pinned SHA needs Go 1.26.1 (auto-toolchain) and pnpm;
  first build is slow (~minutes). Mitigation: build once, cache the binary,
  commit nothing generated.
- Docker is absent on the dev machine: Neo4j runs by using Docker or native-apt path, as described in [`docs/setup.md`](setup0.md#2-neo4j--pick-one-path); the repo still ships `docker-compose.yml` for reviewers, and the
  README documents both paths.
- LLM calls require an API key (`ANTHROPIC_API_KEY`); all LLM stages must be
  cacheable and replayable from fixtures so the pipeline runs offline.
