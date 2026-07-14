# Fresh-machine setup

Everything needed to run blast-agent on a brand-new desktop, from zero to
`SMOKE OK`. Total time ≈ 30–40 minutes, most of it waiting on builds and
downloads. Linux (Ubuntu 22.04/24.04) commands shown; macOS/Windows notes at
the end.

## 1. System tools (one-time)

```bash
# Build tools + git/curl
sudo apt update
sudo apt install -y build-essential git curl

# uv (Python package/env manager) — official installer, not apt
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"   # or open a new shell so `uv` is on PATH

# Go — Ubuntu's apt package is recent enough; the pinned toolchain for the
# actual build (1.26.1) is auto-downloaded on first use (GOTOOLCHAIN=auto)
sudo apt install -y golang-go

# Node >= 22.6 and pnpm >= 10 — do NOT use Ubuntu's apt `nodejs` package,
# it ships 18.x/20.x and fails the Gitea build (see Gotchas below). Use nvm:
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source "$HOME/.nvm/nvm.sh"
nvm install 22
npm install -g pnpm@10
```

Version floor: Python ≥ 3.12 (uv fetches its own if missing), Go ≥ 1.25
(auto-downloads the exact pinned toolchain on first build), Node ≥ 22.6,
pnpm ≥ 10.

## 2. Neo4j — pick ONE path

### Path A — Docker (easiest on a fresh machine)

```bash
# Docker Engine, if not already installed
curl -fsSL https://get.docker.com | sudo sh

# Let your user run docker without sudo (needs a new shell/group session)
sudo usermod -aG docker "$USER"
newgrp docker    # applies the group change in this shell now; a full
                  # logout/login also works and is more permanent

# from the repo root
docker compose up -d neo4j
```

The compose file takes the password from the `NEO4J_PASSWORD` environment
variable, defaulting to `blastagent-dev`. Whatever value ends up in effect,
put the **same value** in `.env` (step 3). If you skip the group step, every
`docker compose ...` command needs a `sudo` prefix instead.

### Path B — native Neo4j via apt

```bash
curl -fsSL https://debian.neo4j.com/neotechnology.gpg.key \
  | sudo gpg --dearmor -o /usr/share/keyrings/neo4j.gpg
echo 'deb [signed-by=/usr/share/keyrings/neo4j.gpg] https://debian.neo4j.com stable 5' \
  | sudo tee /etc/apt/sources.list.d/neo4j.list
sudo apt update
sudo apt install -y neo4j

# IMPORTANT: set the password BEFORE the first start
sudo neo4j-admin dbms set-initial-password 'your-chosen-password'
sudo systemctl enable --now neo4j
```

Order matters: once Neo4j has started once, `set-initial-password` stops
working. If you got the order wrong, log in at http://localhost:7474 with the
default `neo4j` / `neo4j` and change the password when prompted (or run
`ALTER CURRENT USER SET PASSWORD FROM 'neo4j' TO '...'` against the `system`
database).

## 3. The project

```bash
git clone <repo-url> && cd <repo>
uv sync
uv run playwright install chromium     # ~100 MB browser download

cp .env.example .env
```

Then edit `.env` and fill in:

| Key                   | Value                                                                |
| --------------------- | -------------------------------------------------------------------- |
| `ANTHROPIC_API_KEY` | your key (prepaid credits; preferred provider)                       |
| `ANTHROPIC_MODEL`   | `claude-sonnet-5` (recommended) or `claude-haiku-4-5` (cheapest) |
| `NEO4J_PASSWORD`    | the password chosen in step 2                                        |
| `GEMINI_API_KEY`    | optional fallback provider                                           |

`.env.example` already sets `ANTHROPIC_MODEL=claude-sonnet-5`, so a plain
`cp .env.example .env` gets this right by default — the failure mode to avoid
is hand-editing `.env` (or reusing an older one) with that line missing; see
Gotchas.

`.env` is gitignored — keep it that way, and keep it off screen-shares.

## 4. Build and seed the target app

```bash
bash scripts/bootstrap_gitea.sh   # clone + build Gitea at the pinned SHA (~5–10 min first time)
bash scripts/reset_demo.sh        # start + deterministically seed; prints SEEDED OK
```

`reset_demo.sh` can be re-run at any time to restore a byte-identical demo
state. `bootstrap_gitea.sh` is idempotent and only rebuilds when needed
(`--force` to rebuild anyway).

## 5. Verify

```bash
bash scripts/smoke_test.sh        # unit tests → app health check → integration tests → SMOKE OK
```

From here, the full pipeline is the end-to-end walkthrough in the
[README](../README.md#end-to-end-walkthrough) (`crawl` → `ingest-docs` →
`index-code` → `link` → `load-graph` → `analyze-pr` → `eval`). A bare clone
works: the docs snapshots and the PR diff restore themselves from committed
fixtures on first use.

## Gotchas

- Ports **3000** (Gitea) and **7474/7687** (Neo4j) must be free.
- **Docker permission denied.** `docker compose up` failing with `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`
  means your user isn't in the `docker` group yet — run the `usermod`/`newgrp`
  commands in step 2, or prefix commands with `sudo` as a one-off.
- **Node from apt is too old.** Gitea's build requires Node **≥ 22.6** (its
  Makefile passes `--experimental-strip-types` via `NODE_OPTIONS`), and
  Ubuntu/Debian `apt` ships 18.x/20.x, which fails with
  `node: --experimental-strip-types is not allowed in NODE_OPTIONS`. Use nvm
  (step 1) or the NodeSource repo instead of the distro package.
- **`ANTHROPIC_MODEL` silently defaults to Haiku if unset.** The code falls
  back to `claude-haiku-4-5` when `.env` doesn't set `ANTHROPIC_MODEL` — this
  is easy to hit if you hand-roll `.env` instead of copying `.env.example`.
  It's not a hard failure, but it measurably degrades output: crawl flows can
  give up mid-navigation instead of completing, and documentation-requirement
  extraction recall can drop well under the 0.8 eval threshold. Always
  confirm `ANTHROPIC_MODEL=claude-sonnet-5` is actually set before trusting a
  bad-looking `eval` result.
- The LLM response cache (`data/cache/llm/`) is gitignored, so a new machine
  re-pays the ~22 ingestion calls on its first `ingest-docs` (≈ $0.25 on
  Sonnet-class models). Reruns after that are free and offline.
- The first `bootstrap_gitea.sh` downloads the Go toolchain and pnpm packages;
  subsequent builds reuse shared caches and are much faster.
- If Playwright complains about missing system libraries, run
  `uv run playwright install-deps chromium`.

## macOS notes

```bash
xcode-select --install
brew install uv go node
npm install -g pnpm@10
```

Neo4j: `brew install neo4j`, then `neo4j-admin dbms set-initial-password 'your-chosen-password'` **before** `brew services start neo4j` (same
ordering caveat as the Linux apt path above). Everything from step 3 onward
is identical to the Linux instructions.

## Windows notes

Use WSL2 and follow the Linux (Ubuntu) path above — the scripts assume a
Unix shell and won't run directly in PowerShell/cmd.
