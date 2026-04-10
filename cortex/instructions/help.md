# Cortex

AI memory system. Store everything, find anything. Local, free, no API key.

---

## Slash Commands

| Command              | Description                    |
|----------------------|--------------------------------|
| /cortex:init      | Install and set up Cortex   |
| /cortex:search    | Search your memories           |
| /cortex:mine      | Mine projects and conversations|
| /cortex:status    | Palace overview and stats      |
| /cortex:help      | This help message              |

---

## MCP Tools (19)

### Palace (read)
- cortex_status -- Palace status and stats
- cortex_list_wings -- List all wings
- cortex_list_rooms -- List rooms in a wing
- cortex_get_taxonomy -- Get the full taxonomy tree
- cortex_search -- Search memories by query
- cortex_check_duplicate -- Check if a memory already exists
- cortex_get_aaak_spec -- Get the AAAK specification

### Palace (write)
- cortex_add_drawer -- Add a new memory (drawer)
- cortex_delete_drawer -- Delete a memory (drawer)

### Knowledge Graph
- cortex_kg_query -- Query the knowledge graph
- cortex_kg_add -- Add a knowledge graph entry
- cortex_kg_invalidate -- Invalidate a knowledge graph entry
- cortex_kg_timeline -- View knowledge graph timeline
- cortex_kg_stats -- Knowledge graph statistics

### Navigation
- cortex_traverse -- Traverse the palace structure
- cortex_find_tunnels -- Find cross-wing connections
- cortex_graph_stats -- Graph connectivity statistics

### Agent Diary
- cortex_diary_write -- Write a diary entry
- cortex_diary_read -- Read diary entries

---

## CLI Commands

    cortex init <dir>                  Initialize a new palace
    cortex mine <dir>                  Mine a project (default mode)
    cortex mine <dir> --mode convos    Mine conversation exports
    cortex search "query"              Search your memories
    cortex split <dir>                 Split large transcript files
    cortex wake-up                     Load palace into context
    cortex compress                    Compress palace storage
    cortex status                      Show palace status
    cortex repair                      Rebuild vector index
    cortex mcp                         Show MCP setup command
    cortex hook run                    Run hook logic (for harness integration)
    cortex instructions <name>         Output skill instructions

---

## Auto-Save Hooks

- Stop hook -- Automatically saves memories every 15 messages. Counts human
  messages in the session transcript (skipping command-messages). When the
  threshold is reached, blocks the AI with a save instruction. Uses
  ~/.cortex/hook_state/ to track save points per session. If
  stop_hook_active is true, passes through to prevent infinite loops.

- PreCompact hook -- Emergency save before context compaction. Always blocks
  with a comprehensive save instruction because compaction means the AI is
  about to lose detailed context.

Hooks read JSON from stdin and output JSON to stdout. They can be invoked via:

    echo '{"session_id":"abc","stop_hook_active":false,"transcript_path":"..."}' | cortex hook run --hook stop --harness claude-code

---

## Architecture

    Wings (projects/people)
      +-- Rooms (topics)
            +-- Closets (summaries)
                  +-- Drawers (verbatim memories)

    Halls connect rooms within a wing.
    Tunnels connect rooms across wings.

The palace is stored locally using ChromaDB for vector search and SQLite for
metadata. No cloud services or API keys required.

---

## Getting Started

1. /cortex:init -- Set up your palace
2. /cortex:mine -- Mine a project or conversation
3. /cortex:search -- Find what you stored
