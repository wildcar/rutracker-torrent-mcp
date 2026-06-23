# Agent Instructions — rutracker-torrent-mcp

Primary entrypoint for any agent (Claude, Codex, DeepSeek, etc.) working **inside
this repo**. Read this first. This file is authoritative for repo-local work.

## Workspace

This repo is one of seven siblings in the **`movie_handler`** workspace. Cross-repo
architecture, end-to-end flows, hosts, and shared agreements live in `../AGENTS.md`
and `../AGENTS/SPEC.md`. When you reason about how the bot, the other MCP servers,
and watch-web fit together, read the root harness. When you touch code in *this*
repo, **this** file and `AGENTS/` are the source of truth.

## Project

**rutracker-torrent-mcp** (priority 4, port 8767) — an MCP server that searches
**rutracker.org** and fetches `.torrent` files / magnet links. rutracker has no
official API, so everything is HTML-scraped (`selectolax`) over a persisted,
authenticated cookie session. Four tools: `search_torrents`, `get_torrent_file`,
`get_magnet_link`, `get_topic_info`. Consumed by the Telegram bot; coordinates with
the rest of the system only through the composite `media_id` (`rt-<topic_id>`).

## Document Map

| File | Role |
|------|------|
| `AGENTS.md` | This entrypoint. Repo map, workflow, rules. |
| `CLAUDE.md` | Compatibility pointer to `AGENTS.md`. |
| `AGENTS/SPEC.md` | Repo functional + technical spec: tools, scrape strategy, models, structure. |
| `AGENTS/STATE.md` | Current snapshot: goal, now, next, open, deferred. Overwritten each iteration. |
| `AGENTS/HISTORY.md` | Append-only iteration log, newest first. |
| `AGENTS/MEMORY.md` | Durable repo-local facts not derivable from code/git/SPEC. |
| `AGENTS/ENV.md` | Repo-local env vars + run/verify; points to `../AGENTS/ENV.md` for hosts. |
| `README.md` | User-facing tool/env reference (kept). |
| `docs/adr/` | Architecture Decision Records (see `docs/adr/TEMPLATE.md`). |

## Environment

- OS / shell: Ubuntu 24.04 / `bash`, user `keeper` (passwordless sudo).
- Commit identity: `wildcar <wildcar@mail.ru>`.
- Remote: `github.com/wildcar/rutracker-torrent-mcp`. Default branch `main`.
- Secrets via env / `.env` only (`pydantic-settings`); never tool arguments.

## Startup Checklist

1. Read `AGENTS.md` (this file).
2. Read `AGENTS/SPEC.md` for the tool surface and scrape strategy.
3. Read `AGENTS/STATE.md` for the live snapshot.
4. Read top 3–5 entries in `AGENTS/HISTORY.md`.
5. Read `AGENTS/MEMORY.md` (durable repo facts).
6. Check `git status --short` before editing. Open `AGENTS/ENV.md` for env/run detail.

## Change Workflow

For every iteration that changes code or behavior:

1. If the tool contract changes — update `AGENTS/SPEC.md` first.
2. Make the changes.
3. Run `uv run pytest && uv run ruff check && uv run mypy src`.
4. Overwrite `AGENTS/STATE.md`; if the cross-repo picture shifted, also prepend a
   one-line entry to `../AGENTS/HISTORY.md`.
5. Prepend a new entry to `AGENTS/HISTORY.md`.
6. Commit and push after verification (see Project Rules).

### `AGENTS/HISTORY.md` entry format (≤5 lines, newest first)

```
## YYYY-MM-DD · <short iteration title>
- What: <one line — what changed>
- Why: <one line — reason / task>
- Files: <key paths, comma-separated>
- Next: <one line — what was planned right after>
```

## Memory

`AGENTS/MEMORY.md` is the single store of durable repo-local agent memory. Read it
at session start; append a short bullet when you learn a durable fact and commit it
with the related change. Durable facts/agreements → `MEMORY.md`; current snapshot →
`STATE.md`; iteration log → `HISTORY.md`. One bullet = one fact; convert relative
dates to absolute; don't record what's already in code, git, or SPEC/STATE/HISTORY.

## Language Rules

- Source code, technical docs, code comments: **English**.
- Conversation with the user: **Russian**. End-user UI text: **Russian**.
- Tool error messages are English (machine-facing across the MCP boundary).

## Project Rules

- **Structured error returns, not exceptions** across the MCP boundary. Every tool
  returns `…Response` with an optional `error: ToolError`; auth-path failures map to
  stable codes (`captcha_required`, `not_configured`, `login_failed`, `upstream_error`).
- **Pydantic models** for all tool I/O (`models.py`, `extra="forbid"`).
- **Secrets only via env vars**; `.env.example` ships placeholders. Never commit `.env`,
  `.cache/`, cookie jars, or `*.sqlite`.
- **Transport:** `stdio` for local dev; HTTP/SSE with Bearer `MCP_AUTH_TOKEN` networked.
- **Every commit passes `ruff` + `mypy --strict` + `pytest` locally before push.**
  Commit + push to `main` directly after verification — no feature branch, no asking.

## Stack & Commands

Python ≥ 3.11, `asyncio`, `curl_cffi` (Chrome TLS impersonation — stock httpx hangs
on rutracker's CDN), `selectolax`, `pydantic` + `pydantic-settings`, `structlog`,
`aiosqlite` (TTL cache). Deps via `uv`.

```bash
uv sync
uv run python -m rutracker_torrent_mcp.server            # run over stdio
uv run pytest && uv run ruff check && uv run mypy src
uv run pytest -m integration                             # opt-in, hits real rutracker.org
npx @modelcontextprotocol/inspector uv run python -m rutracker_torrent_mcp.server
```

## Code Style

`ruff` format + lint (line-length 100), `mypy --strict`. Match surrounding code:
comment density, naming, idiom.
