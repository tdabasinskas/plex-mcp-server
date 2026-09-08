# Plex MCP Server

A powerful Model-Context-Protocol (MCP) server for interacting with Plex Media Server. It provides a standardized JSON-based interface for automation, AI agents (like Claude), and custom integrations.

## Features

- **Standardized API**: Unified JSON responses for all Plex operations.
- **Multiple Transports**: Supports `stdio`, `SSE` (Server-Sent Events), and stateless `streamable-http`.
- **Comprehensive Control**: Manage libraries, media, collections, playlists, clients, and users.
- **Remote Ready**: Built-in OAuth 2.1 support for integration with remote AI platforms like Claude.ai.
- **Admin Tools**: Access logs, monitor bandwidth, and run Butler tasks.

## Installation

### Option 1: Using uv (Recommended)

Run directly without installation:
```bash
uvx plex-mcp-server --transport stdio --plex-url http://your-server:32400 --plex-token your-token
```

### Option 2: Install via pip

```bash
pip install plex-mcp-server
```

### Option 3: Development / Source

```bash
git clone https://github.com/vladimir-tutin/plex-mcp-server.git
cd plex-mcp-server
pip install -e .
```

## Configuration

Set your Plex server URL and Token using one of these methods:

### 1. Command Line Arguments
```bash
plex-mcp-server --plex-url "http://192.168.1.10:32400" --plex-token "ABC123XYZ"
```

### 2. Environment Variables (.env)
Create a `.env` file in the current directory or `~/.config/plex-mcp-server/.env`:
```env
PLEX_URL=http://localhost:32400
PLEX_TOKEN=your-authentication-token
MCP_OAUTH_ENABLED=false
```
or with OAuth Enabled
```env
PLEX_URL=http://localhost:32400
PLEX_TOKEN=your-authentication-token
MCP_OAUTH_ENABLED=true
MCP_OAUTH_ISSUER=https://auth.example.com/application/o/plexmcp-oauth/
MCP_SERVER_URL=https://plexmcp.example.com
```

### 3. MCP Client Config
Example for Claude Desktop (`%APPDATA%/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "plex": {
      "command": "uvx",
      "args": [
        "plex-mcp-server",
        "--transport",
        "stdio",
        "--plex-url",
        "http://your-server:32400",
        "--plex-token",
        "your-token"
      ]
    }
  }
}
```
### 4. Transports (HTTP)

For remote/HTTP use, pick a transport with `--transport`:

- `--transport sse` — Server-Sent Events at `/sse` (+ `/messages/`). Stateful: the session is bound to a live SSE stream, which can wedge behind proxies/MCP gateways if that stream drops (e.g. after a server restart).
- `--transport streamable-http` — single `/mcp` endpoint, **stateless**. Each request is self-contained, so a server restart never leaves a gateway pinned to a dead session. Recommended when the server sits behind an MCP gateway.

```bash
plex-mcp-server --transport streamable-http --host 0.0.0.0 --port 8001
# MCP endpoint: http://<host>:8001/mcp
```

Both HTTP transports share the same OAuth configuration and discovery endpoints.

> **Behind a reverse proxy / MCP gateway:** the Streamable HTTP transport has DNS-rebinding (Host header) protection that, by default in the MCP SDK, only trusts `localhost` — so a gateway forwarding an external `Host` gets `421 Misdirected Request`. This server disables that browser-oriented check for proxied deployments. To keep it on with an explicit allowlist, set `MCP_ALLOWED_HOSTS` to a comma-separated list of hosts (e.g. `MCP_ALLOWED_HOSTS=mcp.example.com`); localhost is always included.

### 5. Claude Connector Installation

Go to https://claude.ai/settings/connectors and add a new connector with the following settings:
- Name: Plex MCP
- URL: https://plexmcp.example.com/sse (SSE) or https://plexmcp.example.com/mcp (streamable-http)
- Add OAuth Client ID and Client Secret if OAuth is enabled

<img width="516" height="515" alt="image" src="https://github.com/user-attachments/assets/7949a127-51a7-4c60-a121-511ee4a1f00d" />


## Command Reference

### Library Module
Tools for exploring and managing your Plex libraries.

| Command | Description | Parameters |
|---------|-------------|------------|
| `library_list` | Lists all available libraries. | None |
| `library_get_stats` | Gets statistics (count, size, types) for a library. | `library_name` |
| `library_refresh` | Triggers a metadata refresh for a library. | `library_name` |
| `library_scan` | Scans a library for new files. | `library_name` |
| `library_get_details` | Gets detailed information about a library. | `library_name` |
| `library_get_recently_added` | Lists recently added items in a library. | `library_name`, `limit: int` |
| `library_get_contents` | Lists all items in a library. | `library_name`, `limit: int` |
| `library_get_smart_filter_options` | Discover a library's filter fields, operators, and sort options per content type (and per-field values) for building smart playlists and smart collections. | `library_name`, `field`, `libtype` |

### Media Module
Tools for searching, inspecting, and editing specific media items.

Every tool below identifies its target the same way: by `media_id` (a Plex rating key) when you have one, or by `media_title` with optional `library_name` and `libtype` to narrow the search.

| Command | Description | Parameters |
|---------|-------------|------------|
| `media_search` | Search for media across all libraries. | `query`, `content_type` |
| `media_get_details` | Get comprehensive details for an item, including every tag it carries. | `media_title`, `media_id`, `library_name`, `libtype` |
| `media_edit_metadata` | Update an item's tags, summary, rating, or title. | `media_title`, `media_id`, `library_name`, `libtype`, `new_title`, `new_summary`, `new_rating`, `new_release_date`, `new_studio`, `add_tags`, `remove_tags`, `refresh` |
| `media_delete` | Remove an item from Plex. | `media_title`, `media_id`, `library_name`, `libtype` |
| `media_get_artwork` | Retrieve posters or background artwork. | `media_title`, `media_id`, `library_name`, `libtype`, `image_types`, `output_format`, `output_dir` |
| `media_set_artwork` | Set artwork from a local path or URL. | `media_title`, `media_id`, `library_name`, `libtype`, `art_type`, `filepath`, `url`, `lock` |
| `media_list_available_artwork` | List alternative artwork available for selection. | `media_title`, `media_id`, `library_name`, `libtype`, `art_type` |
| `media_get_match` | Show an item's current match (guid, agent, external IDs) and candidate matches to (re)match to. | `media_title`, `media_id`, `library_name`, `libtype`, `search_title`, `search_year`, `search_agent` |
| `media_fix_match` | (Re)match an item to a candidate `guid`, or `auto`-match to the agent's top pick. | `media_title`, `media_id`, `library_name`, `libtype`, `guid`, `auto`, `search_agent` |
| `media_unmatch` | Remove the current metadata match, leaving the item unmatched. | `media_title`, `media_id`, `library_name`, `libtype` |

> **Identifying an item.** When a title matches more than one item, these tools change nothing and return the list of candidates instead, each with the `id` to call back with. Music is where this bites: an artist, an album and a track can all share one title, so candidate entries carry `artist`, `album` and track `index` to tell them apart. Two ways to skip the round trip - pass `libtype` (`{"media_title": "Intro", "libtype": "track"}`) to search one content type, or pass a `media_id` you already have.

> **Tags.** Plex hangs ten kinds of tag off media, and `media_edit_metadata` edits them through one pair of parameters keyed by tag type rather than a parameter each:
>
> ```json
> {"media_id": 101,
>  "add_tags":    {"genre": ["Rap"], "style": ["Trap", "Cloud Rap"], "mood": ["Aggressive"]},
>  "remove_tags": {"label": ["needs-review"]}}
> ```
>
> Which types apply depends on the item — a track has moods but no styles, a movie has writers but no moods. `media_get_details` reports every tag an item carries plus an `editableTagTypes` list, so you can read, edit and re-read without guessing; naming a type the item doesn't support returns an error listing the ones it does. Tags already present are skipped rather than duplicated, and a single string works anywhere a list does. Use `library_get_smart_filter_options` with a `field` to list a tag type's valid values in a library.
>
> | | Movie | Show | Season | Episode | Artist | Album | Track |
> |---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
> | `collection` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
> | `country` | ✓ | | | | ✓ | | |
> | `director` | ✓ | | | ✓ | | | |
> | `genre` | ✓ | ✓ | | | ✓ | ✓ | ✓ |
> | `label` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
> | `mood` | | | | | ✓ | ✓ | ✓ |
> | `producer` | ✓ | | | | | | |
> | `similarArtist` | | | | | ✓ | | |
> | `style` | | | | | ✓ | ✓ | |
> | `writer` | ✓ | | | ✓ | | | |

> **`media_edit_metadata` and `refresh`.** Edited fields are locked, so Plex's metadata agent won't overwrite them. Re-running the agent afterwards is therefore optional and off by default; pass `refresh=true` if you want it. The response always reflects the saved values.

### Playlist Module
Manage your personal and shared playlists.

| Command | Description | Parameters |
|---------|-------------|------------|
| `playlist_list` | List all available playlists. | None |
| `playlist_get_contents` | List items in a playlist (paginated); for smart playlists also returns `smart`, the current `smartFilter` and `smartFilterRaw`. Use `include_items=false` to read just the filter. | `playlist_title`, `playlist_id`, `limit`, `offset`, `include_items` |
| `playlist_create` | Create a new playlist from items. | `title`, `items: List[str]` |
| `playlist_delete` | Delete a playlist. | `playlist_title`, `playlist_id` |
| `playlist_add_to` | Add media items to a playlist. | `playlist_title`, `items: List[str]`, `playlist_id` |
| `playlist_remove_from` | Remove specific items from a playlist. | `playlist_title`, `items: List[str]`, `playlist_id` |
| `playlist_edit` | Change playlist title or summary. | `playlist_title`, `new_title`, `new_summary`, `playlist_id` |
| `playlist_upload_poster` | Upload a custom poster image. | `playlist_title`, `image_path`, `playlist_id` |
| `playlist_copy_to_user` | Share/Copy a playlist to another user. | `playlist_title`, `username`, `playlist_id` |
| `playlist_create_smart` | Create a smart playlist that auto-populates from a library filter. | `playlist_title`, `library_name`, `filters: dict`, `sort`, `limit`, `libtype`, `summary` |
| `playlist_edit_smart_filters` | Update an existing smart playlist's filter definition. | `playlist_title`, `playlist_id`, `filters: dict`, `sort`, `limit` |

#### Smart playlists

Smart playlists are saved searches over a **single library** that Plex keeps auto-populated, rather than a fixed list of items. The typical flow:

1. Call `library_get_smart_filter_options` for the target library to see which fields you can filter/sort on and their operators. It reports fields grouped by content type (`libtypes`); call it again with a `field` (e.g. `genre`) to list that field's valid values.
2. Call `playlist_create_smart` with a `filters` dict, e.g. `{"genre": "Comedy", "year>>": 2000, "unwatched": true}`. Append an operator's `suffix` to a field name for comparisons (`year>>` means after that year).
3. Read the current definition anytime with `playlist_get_contents` — for a smart playlist it returns `smart: true`, a `smartFilter` object (`libtype`, `sort`, `limit`, `filters`) and `smartFilterRaw`. Items are paginated (`limit`/`offset`, with `totalItems`/`hasMore` in the response); pass `include_items=false` to fetch just the filter without enumerating a large playlist.
4. Adjust later with `playlist_edit_smart_filters`. Anything you don't pass is left alone, so a sort-only edit keeps the criteria. Passing `filters` replaces the whole filter set rather than merging clause by clause, so read it first if you mean to add to it; the response reports the definition before and after.

> **Note on `libtype`:** it defaults to the section's content type, which is `episode` for TV libraries and `track` for music. Set `libtype` to `show` or `artist` if you want whole shows/artists instead.

> **Operators: an empty suffix is a real operator.** `library_get_smart_filter_options` returns each operator as a `suffix` to append verbatim plus what it `means`. Plex's own URL form and the form these tools accept differ by one trailing `=`, so use the reported `suffix` rather than the operator you may have seen in a Plex filter URL. On a **string** field the empty suffix means *contains*, and `=` means *is*: `{"track.title": "Love Me Tender"}` also matches `Love Me Tender (Live)`, while `{"track.title=": "Love Me Tender"}` is an exact match. Reading a saved filter back returns this same form, so `track.title=` in a `smartFilter` is already the exact-match operator, not a weakened one.

> **Edits are confirmed against what Plex stored.** After a filter edit the tool re-reads the item and compares what the server actually saved against what was meant to survive. If the criteria changed when they shouldn't have, the previous filter is restored and the call reports an error rather than success — so `filter_after` describes the stored filter, not the intent, and can be trusted as a check. `python tests/test_smart_filters.py` covers this; it needs no test framework.

> **A smart filter with no criteria is refused.** `filters` is stored as one search URI, so saving an empty filter set doesn't leave the criteria alone — it matches the *entire library* and the previous definition is gone. The edit tools therefore preserve every parameter you omit, and refuse to save an empty filter set **when you pass one**; pass `allow_empty_filter=true` if an unfiltered playlist or collection is genuinely what you want. Omitting `filters` is never refused — the criteria aren't being touched, so the edit can't widen what the item matches. The same preservation covers `sort`, `limit` and `libtype` — the last of which plexapi's own `updateFilters` resets to the library default, silently changing a playlist built on albums into one built on tracks. When `filters` isn't being changed, the saved criteria are carried over **verbatim from the stored URI** rather than parsed and rebuilt, so a filter too complex for the reader to parse is still editable.

> **Verifying what was actually saved.** A readback returns the filter twice: `smartFilter` is the parsed form the create/edit tools accept, and `smartFilterRaw` is the URI as Plex stores it. The two spell operators differently by one trailing `=` — an exact title match reads `track.title=` in `smartFilter` and `track.title==` in `smartFilterRaw`, and they mean the same thing. `smartFilterRaw` is the ground truth if you want to confirm a write landed as intended. When the filter can't be read at all, `smartFilter` carries an `error` saying why instead of being omitted. Plex sometimes saves an empty filter group; it constrains nothing, so it is left out of `smartFilter` and a `smartFilterNote` says so — `smartFilterRaw` still shows exactly what Plex stored, so the two can be compared.

> **The filter vocabulary is broader than Plex's simple dropdown.** `library_get_smart_filter_options` reports the full `listFields` set the API actually validates against — so fields like `title` or `userRating` are available even though the basic Plex filter menu omits them. Fields are returned with a fully-qualified key per content type; to filter on a non-default type use the `libtype.field` form (e.g. `artist.title`, `track.userRating>>`). Because accepted filters are broader than advertised, **always check the returned `item_count` after creating** to confirm the filter actually matched something sensible.

> **Sort fields are limited by Plex.** Sorting is restricted to what each content type exposes (typically `titleSort`, `userRating`, `addedAt`, `lastViewedAt`, `viewCount`, `random`) — there is no `year` sort, so albums/movies can't be ordered chronologically. If the field you want isn't in `sorts`, sort by `titleSort` or accept the default order.

### Collection Module
Organize movies and shows into collections.

| Command | Description | Parameters |
|---------|-------------|------------|
| `collection_list` | List collections in a library; for smart collections also returns the current `smartFilter` definition. | `library_name` |
| `collection_create` | Create a new collection. | `library_name`, `title`, `items: List[str]` |
| `collection_add_to` | Add items to an existing collection. | `library_name`, `collection_title`, `items: List[str]`, `collection_id` |
| `collection_remove_from` | Remove items from a collection. | `library_name`, `collection_title`, `items: List[str]`, `collection_id` |
| `collection_edit` | Edit collection metadata and settings. | `collection_title`, `collection_id`, `library_name`, `new_title`, `new_sort_title`, `new_summary`, `new_content_rating`, `new_labels`, `add_labels`, `remove_labels`, `poster_path`, `poster_url`, `background_path`, `background_url`, `new_advanced_settings` |
| `collection_delete` | Delete a collection. | `collection_title`, `collection_id`, `library_name` |
| `collection_get_contents` | List a collection's items (paginated); for smart collections also returns the `smartFilter` and `smartFilterRaw`. Use `include_items=false` to read just the filter. | `collection_title`, `collection_id`, `library_name`, `limit`, `offset`, `include_items` |
| `collection_create_smart` | Create a smart collection that auto-populates from a library filter. | `collection_title`, `library_name`, `filters: dict`, `sort`, `limit`, `libtype`, `summary` |
| `collection_edit_smart_filters` | Update an existing smart collection's filter definition. | `collection_title`, `collection_id`, `library_name`, `filters: dict`, `sort`, `limit`, `libtype` |

#### Smart collections

Smart collections work exactly like smart playlists — a saved filter over a **single library** that Plex keeps auto-populated — and share the same filter vocabulary:

1. Call `library_get_smart_filter_options` for the target library to discover filter fields, operators, and sort options (add a `field` argument to list a field's valid values).
2. Call `collection_create_smart` with a `filters` dict, e.g. `{"genre": "Comedy", "year>>": 2000}`.
3. Read the current definition with `collection_get_contents` — it returns the collection's items (paginated via `limit`/`offset`, with `totalItems`/`hasMore`) plus, for a smart collection, a `smartFilter` object (`libtype`, `sort`, `limit`, `filters`); pass `include_items=false` to fetch just the filter. `collection_list` also surfaces `smartFilter` for a quick library-wide overview, but only `collection_get_contents` returns the actual items.
4. Adjust later with `collection_edit_smart_filters` (it overwrites the filter definition, so read it first if you want to build on the existing one).

> **Note:** `collection_list` only reports collections from movie and TV libraries, so a smart collection created in a music library won't appear there (though it is still created and readable via `collection_get_contents` by id).

### User Module
Information about the server owner and shared users.

| Command | Description | Parameters |
|---------|-------------|------------|
| `user_search_users` | Search for shared users. | `search_term` |
| `user_list_all_users` | List all users with types and IDs. | None |
| `user_get_info` | Detailed info for a specific user. | `username` |
| `user_get_on_deck` | Get "On Deck" items for a user. | `username` |
| `user_get_continue_watching` | Get partially watched items to resume. | `limit: int` |
| `user_get_watch_history` | Retrieve personal watch history. | `username`, `limit`, `content_type`, `user_id` |
| `user_get_statistics` | Watch progress and usage statistics. | `time_period`, `username` |

### Sessions Module
Monitor real-time server activity.

| Command | Description | Parameters |
|---------|-------------|------------|
| `sessions_get_active` | Get currently playing items and clients. | None |
| `sessions_get_media_playback_history` | History for a specific media item. | `media_title`, `library_name`, `media_id` |

### Server Module
Maintenance and administrative tools.

| Command | Description | Parameters |
|---------|-------------|------------|
| `server_get_plex_logs` | Retrieve lines from Plex logs. | `num_lines`, `log_type`, `start_line`, `list_files`, `search_term` |
| `server_get_info` | Basic server health and version info. | None |
| `server_get_bandwidth`| Bandwidth usage statistics. | `timespan`, `lan` |
| `server_get_current_resources` | CPU/Memory usage of the host/process. | None |
| `server_get_butler_tasks` | List scheduled maintenance tasks. | None |
| `server_get_alerts` | Listen for server notifications/alerts. | `timeout` |
| `server_run_butler_task` | Manually trigger a Butler task. | `task_name` |
| `server_empty_trash` | Empty trash for libraries. | `library_name` |
| `server_optimize_database` | Run database optimization. | None |
| `server_clean_bundles` | Clean up unused media bundles. | None |

### Client Module
Control playback and navigation on Plex clients.

| Command | Description | Parameters |
|---------|-------------|------------|
| `client_list` | List all available playback clients. | `include_details: bool`, `active_only: bool` |
| `client_get_details` | Detailed info for a client. | `client_name`, `client_id` |
| `client_get_timelines` | Current playback state/trackers. | `client_name`, `client_id` |
| `client_start_playback` | Start playing a media item on a client. | `media_title`, `client_name`, `rating_key`, `offset`, `library_name`, `use_external_player` |
| `client_control_playback` | Play, Pause, Stop, Seek, Skip. | `client_name`, `action`, `offset`, `client_id` |
| `client_navigate` | Send remote control navigation commands. | `client_name`, `command`, `client_id` |
| `client_set_streams` | Changes audio or subtitle tracks. | `client_name`, `audio_stream_id`, `subtitle_stream_id`, `client_id` |

## Remote Access & OAuth

The Plex MCP Server can be integrated with remote platforms like **Claude.ai** via SSE and optional OAuth 2.1. This allows you to talk to your MCP server directly from the Claude interface from anywhere.

### Enabling OAuth
1. Set `MCP_OAUTH_ENABLED=true` in your environment.
2. Configure `MCP_OAUTH_ISSUER` (e.g., your OAuth provider URL).
3. Set `MCP_SERVER_URL` to your public-facing URL.
4. Configure your client to use your OAuth provider Client ID and Secret

### Discovery Endpoints
When OAuth is active, the following standard endpoints are exposed:
- `/.well-known/oauth-protected-resource`
- `/.well-known/oauth-authorization-server`

## Response Formats

All tools return information in JSON format for consistent parsing.

### Success Example
```json
{
  "status": "success",
  "data": {
    "title": "Inception",
    "year": 2010,
    "rating": 8.8
  }
}
```

### Error Example
```json
{
  "status": "error",
  "message": "Library 'Missing' not found."
}
```

### Multiple Matches
If an operation finds multiple items with the same name, it returns a list of specific identifiers:
```json
[
  {
    "title": "The Office",
    "id": 123,
    "type": "show",
    "year": 2005
  },
  {
    "title": "The Office",
    "id": 456,
    "type": "show",
    "year": 1995
  }
]
```

## Troubleshooting OAuth

- **401 Unauthorized**: Ensure your `MCP_OAUTH_ISSUER` exactly matches the issuer URL in your identity provider (including trailing slashes).
- **Public URL**: `MCP_SERVER_URL` must be reachable by the client (e.g., plexmcp.example.com) and should use HTTPS.
- **Redirect URIs**: For Claude.ai, the redirect URI in your provider must be `https://claude.ai/api/mcp/auth_callback`.