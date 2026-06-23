# History

Newest first. Each entry ≤5 lines using the format defined in `AGENTS.md`.

---

## 2026-06-23 · Migrate to agent-template harness
- What: Added `AGENTS.md`, `CLAUDE.md` pointer, `AGENTS/{SPEC,STATE,HISTORY,MEMORY,ENV}.md`, `docs/adr/TEMPLATE.md`; folded `history.md`/`env.md`.
- Why: Adopt the standard workspace harness; keep repo-local context authoritative inside the repo.
- Files: `AGENTS.md`, `CLAUDE.md`, `AGENTS/*`, `docs/adr/TEMPLATE.md`; removed `history.md` (`env.md` absent).
- Next: Resume feature work under the new structure.

## 2026-04-26 · Anchor topic-page size parser on the «Размер» label
- What: Added `_SIZE_LABELED_RE`; `_parse_topic` now requires a `Размер:`/`Size:` label before the size token.
- Why: Whole-page `_SIZE_RE` matched stray `B`/`KB`/… tokens (CSS, scripts) → `size_bytes=5` for a 75 GB release.
- Files: `clients/rutracker.py`.
- Next: `_parse_search` untouched (already scopes to the size cell).

## 2026-04-26 · `get_topic_info(topic_id)` tool
- What: New `RutrackerClient.topic_info` + `TopicInfo`/`GetTopicInfoResponse` models + `get_topic_info_impl`; wired as 4th MCP tool.
- Why: Bot needs cheap topic title + forum context (no `.torrent`) when a user pastes a rutracker URL — feeds the composite media-id pipeline.
- Files: `clients/rutracker.py`, `models.py`, `tools.py`, `server.py`, `tests/fixtures/tracker_topic.html`.
- Next: Title required → `not_found`; same caching/auth-error shaping as the other tools.
