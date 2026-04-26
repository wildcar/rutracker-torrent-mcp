# history — rutracker-torrent-mcp

Reverse-chronological log of meaningful changes. Add an entry **before** the
work starts so future agents can see the intent even if a session is
interrupted; expand it with results once the change lands.

---

## 2026-04-26 — Anchor topic-page size parser on the «Размер» label

Live test on a real topic returned `size_bytes=5` for a 75 GB release —
`_SIZE_RE.search(html)` was matching anything that happened to end in
`B`/`KB`/`MB`/`GB`/`TB` somewhere on the page (CSS class names,
embedded scripts, byte-counter widgets). Added `_SIZE_LABELED_RE`
which only fires when the size token follows a `Размер:` / `Size:`
label, and pointed `_parse_topic` at it. `_parse_search` is unchanged —
it scopes the regex to the size cell already.

---

## 2026-04-26 — `get_topic_info(topic_id)` tool

**Why.** Bot needs to handle the case where a user pastes a rutracker topic
URL directly (cross-repo feature: composite media-id pipeline, kicks off
flow #6 mid-pipeline). For that the bot needs a cheap way to fetch *just*
the topic title + forum context, without pulling the .torrent. The existing
`get_torrent_file` returns a `Content-Disposition` filename which is a
sanitized-for-filesystem variant of the title — not ideal for matching
against `movie-metadata-mcp`.

**What.**
- New `RutrackerClient.topic_info(topic_id)` parses the same
  `viewtopic.php?t=…` page used by `magnet_link`. Selectors:
  `a#topic-title` / `h1.maintitle a` for the title; trailing
  `a[href*="viewforum.php?f="]` breadcrumb for forum_id/name; loose
  regex on the page body for size and upload date (best-effort, return
  null when not parseable).
- New `TopicInfo` / `GetTopicInfoResponse` Pydantic models. Title is
  required; missing title → `ToolError(code="not_found")`.
- New `get_topic_info_impl` tool with the same caching + auth-error
  shaping as the existing tools (cache TTL = search bucket; titles
  rarely change).
- Wired into `server.py` as the fourth MCP tool.
- Tests: parse a fixture topic-page (`tests/fixtures/tracker_topic.html`),
  reject `topic_id <= 0`, and surface a `not_found` error on an empty
  page.
