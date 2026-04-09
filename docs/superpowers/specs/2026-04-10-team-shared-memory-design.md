# Team Shared Memory Design

## Overview

Add team-shared memory to MemPalace via a two-layer architecture: **private layer** (local, unchanged) + **team layer** (remote server). Individual data stays on the user's machine; shared knowledge lives on a team server. AI tools see a unified view through the existing MCP interface.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  AI (Claude / GPT / etc.)                           │
│  Calls MCP tools — unaware of private/team split    │
└────────────────────┬────────────────────────────────┘
                     │ MCP (stdio)
┌────────────────────▼────────────────────────────────┐
│  Local MCP Server  (modified mcp_server.py)         │
│                                                     │
│  ┌─────────────┐    ┌──────────────┐                │
│  │ LocalClient │    │ TeamClient   │                │
│  │ (unchanged) │    │ (new, HTTP)  │                │
│  └──────┬──────┘    └──────┬───────┘                │
│         │                  │                        │
│  ┌──────▼──────────────────▼───────┐                │
│  │ Router + Result Merger (new)    │                │
│  └─────────────────────────────────┘                │
└────────┬───────────────────┬────────────────────────┘
         │                   │ HTTPS + API Key
┌────────▼────────┐  ┌───────▼──────────────────────┐
│  Local Palace    │  │  Team Server (new)            │
│  ~/.mempalace/   │  │  FastAPI + uvicorn            │
│  - ChromaDB      │  │  - Auth middleware (API Key)  │
│  - SQLite KG     │  │  - Permission check (wing)   │
│  - WAL           │  │  - ChromaDB (HttpClient)     │
│  (unchanged)     │  │  - KG (SQLite, v1)           │
└─────────────────┘  │  - WAL (with user_id)         │
                     └──────────────────────────────┘
```

### Key Principles

- Local palace code has zero changes. All existing tests continue to pass.
- MCP Server gains a routing layer that decides: local, remote, or both.
- AI-facing tool signatures are unchanged. Results gain a `layer` field.
- No `team` config = behavior identical to today.

## Team Server API

### Authentication

All requests carry `X-API-Key` header. Server looks up `user_id` + permissions from the key's SHA-256 hash.

### Endpoints

```
POST   /api/v1/search              Search team layer
POST   /api/v1/drawers             Add drawer (publish or direct write)
PATCH  /api/v1/drawers/{id}        Update drawer (requires `If-Match: <version>` header)
DELETE /api/v1/drawers/{id}        Delete drawer (requires `If-Match: <version>` header)
GET    /api/v1/wings               List wings (filtered by permission)
GET    /api/v1/wings/{wing}/rooms  List rooms within a wing
GET    /api/v1/taxonomy            Full wing -> room -> count tree
GET    /api/v1/drawers              List drawers (filter by published_by, wing, room)
GET    /api/v1/drawers/{id}        Get single drawer with full metadata
GET    /api/v1/health              Health check (no auth required)
GET    /api/v1/status              Team layer overview + server version (auth required)

POST   /api/v1/kg/query            Knowledge graph query
POST   /api/v1/kg/add              Add triple
POST   /api/v1/kg/invalidate       Invalidate triple
GET    /api/v1/kg/timeline/{entity} Entity timeline
```

### Permission Model

```json
{
  "users": {
    "sha256_of_key_1": {
      "user_id": "andy",
      "role": "admin",
      "wings": { "read": "*", "write": "*" }
    },
    "sha256_of_key_2": {
      "user_id": "kai",
      "role": "member",
      "wings": {
        "read": ["wing_frontend", "wing_shared", "wing_backend"],
        "write": ["wing_frontend", "wing_shared"]
      }
    }
  }
}
```

- `admin`: Read/write all wings + delete any drawer + manage users.
- `member`: Read/write per wing independently configured. Can only delete own drawers.
- Every request is checked: user has access to target wing? No -> 403.

### Drawer Metadata Extension

Team layer drawers carry additional metadata:

- `published_by`: User ID of publisher.
- `published_at`: ISO timestamp.
- `source_type`: `"publish"` (from personal layer) or `"direct"` (written directly).
- `origin`: (publish only) `{ "local_id": "<original_drawer_id>", "user_id": "<publisher>" }`. Links team drawer back to its local source.
- `version`: Integer, starts at 1, incremented on each update. Used for optimistic concurrency — write requests must include `If-Match: <version>`, server returns 409 Conflict on mismatch.

Local drawers that have been published gain a `published_as` field:

- `published_as`: `{ "team_id": "<team_drawer_id>", "published_at": "<ISO timestamp>" }`. Enables forward tracking and stale detection — if local content is newer than `published_at`, the user can be prompted to re-publish.

## Local MCP Server Routing

### Configuration

```json
// ~/.mempalace/config.json — new "team" section
{
  "palace_path": "~/.mempalace/palace",
  "team": {
    "enabled": true,
    "server": "https://mempalace.team.example.com",
    "api_key": "ak_a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5",
    "timeout_seconds": 3
  }
}
```

No `team` field or `enabled: false` = current behavior, no changes.

### Routing Rules

| Operation | Route |
|---|---|
| `mempalace_search` | Parallel query local + remote, dedupe, merge via RRF |
| `mempalace_status` | Fetch both, label sources |
| `mempalace_list_wings` | Merge both, label `[local]` / `[team]` |
| `mempalace_list_rooms` | Route to layer based on wing source |
| `mempalace_add_drawer` | Always writes to local. Use `mempalace_publish` to push to team |
| `mempalace_delete_drawer` | Route by drawer ID prefix (`local_` / `team_`, no prefix = local). If drawer has `published_as`, warn user that team copy still exists |
| `mempalace_publish` | **New tool.** Read local drawer -> POST to remote |
| `mempalace_kg_*` | Route by `layer` parameter, default local |

### Publish Tool

```
mempalace_publish(drawer_id, target_wing=None, target_room=None)
```

- Reads drawer content + metadata from local collection.
- `target_wing` / `target_room` optionally override classification.
- **First publish**: POSTs to team API with `published_by` and `source_type: "publish"`. Stores `published_as` on local drawer. Returns team drawer ID.
- **Re-publish** (local drawer already has `published_as`): PATCHes the existing team drawer using `published_as.team_id` + `If-Match: <version>`. Updates content, metadata, and `published_at`. No duplicate team drawers created.
- On 409 Conflict (team drawer was edited by someone else since last publish): abort and report conflict to user with both versions.

### Search Merge Logic

```python
async def merged_search(query, wing=None, room=None, n_results=5):
    local_hits, team_hits = await asyncio.gather(
        search_local(query, wing, room, n_results * 2),
        search_team(query, wing, room, n_results * 2),
    )
    deduped = dedupe(local_hits, team_hits)  # origin link first, content_hash fallback
    merged = rrf_merge(deduped, k=60)
    for hit in merged:
        hit["layer"] = determine_layer(hit)  # "local", "team", or "both"
    return merged[:n_results]

def rrf_merge(deduped_hits, k=60):
    """Reciprocal Rank Fusion — merges by rank position, not raw similarity.
    Score = sum(1 / (k + rank)) across layers the hit appeared in."""
    scores = {}
    for layer_hits in [deduped_hits["local"], deduped_hits["team"]]:
        for rank, hit in enumerate(layer_hits):
            scores.setdefault(hit["id"], hit)
            scores[hit["id"]]["rrf_score"] = scores[hit["id"]].get("rrf_score", 0) + 1 / (k + rank)
    return sorted(scores.values(), key=lambda h: h["rrf_score"], reverse=True)
```

- **Reciprocal Rank Fusion (RRF)** instead of raw similarity comparison. Each hit is scored by `1 / (k + rank)` per layer, then summed. This is immune to score distribution differences between collections of different sizes. `k=60` is the standard constant from the original RRF paper.
- Dedupe by `origin` link first (team drawer's `origin.local_id` matches a local drawer), then fall back to `content_hash`. Matched pairs appear in both layers' rank lists, boosting their RRF score naturally.
- No layer preference weighting. Use `--layer` filter for explicit selection.

### Remote Failure Handling

- Local + remote queried in parallel.
- Remote timeout: configurable via `team.timeout_seconds` in config.json (default: 3).
- On timeout or error: return local results + `"team": "timeout"` or `"team": "unavailable"`.
- Never blocks user workflow.

## CLI Extensions

### Existing Commands — New `--layer` Flag

```bash
mempalace search "auth decision"                  # both layers (default)
mempalace search "auth decision" --layer local     # local only
mempalace search "auth decision" --layer team      # team only

mempalace mine ~/chats/ --mode convos              # writes local (default)
mempalace mine ~/meeting-notes/ --publish --wing shared     # mines to local, then publishes to team
```

### New Commands

```bash
# Publish
mempalace publish <drawer_id>
mempalace publish <drawer_id> --wing new_wing --room new_room
mempalace publish --wing auth-migration --room decisions   # batch by filter (see below)

# Team configuration
mempalace team init          # Interactive setup: server URL + API key
mempalace team status        # Connection status + permissions
mempalace team whoami        # Current user + accessible wings

# Server management (admin)
mempalace team serve                              # Start team server
mempalace team serve --port 8900 --host 0.0.0.0
mempalace team add-user --id kai --role member --read-wings frontend,shared,backend --write-wings frontend,shared
# → generates and prints API key: ak_a3f8b2c1... (shown once, never stored in plaintext)
mempalace team remove-user --id kai
mempalace team rotate-key --id kai   # generates new key, old key valid for 24h grace period
```

**Batch publish error handling**: Batch publish (`--wing`/`--room` filter) processes drawers individually. No all-or-nothing transaction. On completion, reports a summary: `published: N, skipped (already up-to-date): N, failed: N` with per-drawer error details for failures (e.g., 409 conflict, 403 permission denied). User can re-run to retry failed items.

## Data Isolation & Storage

### Local Layer (unchanged)

```
~/.mempalace/
  ├── config.json              # New "team" section added
  ├── palace/
  │   ├── chroma.sqlite3       # ChromaDB local storage (unchanged)
  │   └── ...
  ├── knowledge_graph.sqlite3  # Local KG (unchanged)
  └── wal/
      └── write_log.jsonl      # Local WAL (unchanged)
```

### Team Server

```
/var/mempalace-team/
  ├── team_config.json         # Users + permissions
  ├── palace/
  │   └── chroma/              # ChromaDB data (HttpClient mode)
  ├── knowledge_graph.sqlite3  # Team KG (SQLite v1, Postgres later)
  └── wal/
      └── write_log.jsonl      # Team WAL, each entry has user_id
```

### Drawer ID Design

Prefix-based to distinguish source and avoid collision:

- Local: `local_{content_hash}`
- Team: `team_{content_hash}`

Existing local drawers have no prefix — router treats no-prefix as local (backward compatible).

Cross-layer tracking uses `origin` / `published_as` metadata (see Drawer Metadata Extension), not ID matching. This keeps IDs simple while maintaining a reliable bidirectional link between local and team copies.

### Knowledge Graph Isolation

Two independent KG instances, not merged:

- Local KG = personal understanding, exploratory triples.
- Team KG = consensus facts, confirmed decisions.
- Search can query both, results labeled by source with `"kg_layer": "local"` or `"kg_layer": "team"`. Local triples should be treated as personal/exploratory; team triples as team consensus. AI tools should surface this distinction to the user when presenting KG results.
- Publish does NOT auto-sync KG triples. Explicit command required:

```bash
mempalace publish --kg --subject "Maya" --predicate "completed" --object "auth-migration"
```

## Security & Deployment

### API Key Management

- Format: `ak_{random_32chars}` (e.g., `ak_a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5`). Key does not contain user_id — identity is resolved server-side from the key's SHA-256 hash, avoiding user identity leakage if the key is exposed.
- Server stores SHA-256 hash of key, never plaintext.
- Local `config.json` file permission `0600` (existing chmod logic in config.py).
- API key can also be provided via `MEMPALACE_TEAM_API_KEY` environment variable (takes precedence over config.json). Recommended for CI/shared machines to avoid key in config file.
- **Key rotation**: `team rotate-key` generates a new key for a user. Old key enters a 24-hour grace period (both keys are valid), then expires. Server stores both hashes during the grace window. This allows clients to update without downtime.

### Transport Security

- v1 requires HTTPS. HTTP rejected except `localhost` for development.
- TeamClient validates URL scheme before sending requests.

### Server Security

- Every request: validate API Key -> resolve user_id -> check wing permission.
- Write operations logged to WAL: `who, what, when, from_ip`.
- Rate limit: 60 requests per minute per key (v1).

### Deployment

```bash
# Simple deployment
pip install mempalace
mempalace team serve --port 8900

# Production (reverse proxy + TLS)
# Nginx/Caddy in front for HTTPS termination
mempalace team serve --host 127.0.0.1 --port 8900
```

Single-process FastAPI with uvicorn. No containerization or clustering in v1. SQLite concurrent write limits are acceptable for small teams (<20 people). Switch to Postgres for larger teams.

### Backup

All team server data is file-level: ChromaDB (SQLite-backed), KG (SQLite), WAL (append-only JSONL). Copy the directory to back up. No dump required.

## Migration & Compatibility

### Zero Impact on Existing Users

- No `team` config = identical behavior to today.
- Existing drawers have no ID prefix = treated as local, no migration needed.
- MCP tool signatures unchanged. Results gain optional `layer` field.
- Existing CLI commands without `--layer` work as before.

### Version Compatibility

- API versioned at `/api/v1/`. Future upgrades won't break old clients.
- On startup, TeamClient calls `GET /api/v1/status` for server version.
- Version mismatch = warning to upgrade, not hard failure.

## Constraints & Future Work

### v1 Constraints

- Single embedding model (ChromaDB default) across both layers.
- SQLite for team KG (switch to Postgres for >20 users).
- API Key auth only (OAuth/SSO deferred). Supports env var `MEMPALACE_TEAM_API_KEY` as alternative to config file.
- No automatic sync rules (publish is always explicit). `mine` writes local first, `--publish` flag triggers publish as a second step.
- User management via `team_config.json` + convenience CLI commands.
- Optimistic concurrency via `version` + `If-Match` header. No distributed locking.

### Future Considerations

- **OAuth/SSO** for enterprise teams.
- **Postgres** for team KG at scale.
- **Auto-sync rules** (e.g., all `hall_facts` auto-publish) once trust model is proven.
- **Conflict detection** across layers when `fact_checker.py` is wired into KG.
- **Containerized deployment** (Docker image) for easier team server setup.
