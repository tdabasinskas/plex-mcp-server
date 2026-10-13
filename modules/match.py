import json
from mcp.types import ToolAnnotations  # type: ignore
from modules import mcp, connect_to_plex
from modules.resolve import resolve_media

# Media types that support metadata-agent matching (Video + Audio subclasses).
MATCHABLE_TYPES = ['movie', 'show', 'season', 'episode', 'artist', 'album', 'track']


def _resolve_media(plex, media_title, media_id, library_name, libtype=None):
    """Resolve a single matchable media item by id or title.

    Thin wrapper over the shared resolver that narrows the accepted types to
    those a metadata agent can match against.
    """
    return resolve_media(plex, media_title, media_id, library_name, libtype,
                         allowed_types=MATCHABLE_TYPES)


def _agent_from_guid(guid):
    """Infer a human-readable metadata agent name from an item's guid scheme."""
    if not guid:
        return None
    if guid.startswith('plex://'):
        return 'Plex'
    if guid.startswith('local://'):
        return 'None (unmatched / local)'
    if guid.startswith('com.plexapp.agents.'):
        # e.g. com.plexapp.agents.imdb://tt0111161?lang=en -> imdb (legacy agent)
        agent = guid[len('com.plexapp.agents.'):].split('://', 1)[0]
        return f'{agent} (legacy agent)'
    return guid.split('://', 1)[0]


def _external_guids(item):
    """Return the item's external IDs (imdb/tmdb/tvdb) as a list of strings."""
    guids = []
    for g in getattr(item, 'guids', []) or []:
        gid = getattr(g, 'id', None)
        if gid:
            guids.append(gid)
    return guids


def _serialize_candidate(result):
    """Serialize a plexapi SearchResult into a plain dict."""
    return {
        "guid": getattr(result, 'guid', None),
        "name": getattr(result, 'name', None),
        "year": getattr(result, 'year', None),
        "score": getattr(result, 'score', None),
        "lang": getattr(result, 'lang', None),
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def media_get_match(media_title: str = None, media_id: int = None, library_name: str = None,
                          libtype: str = None,
                          search_title: str = None, search_year: int = None,
                          search_agent: str = None) -> str:
    """Show what a media item is currently matched to, plus candidate matches it could be (re)matched to.

    Reports the item's current match (guid, inferred metadata agent, and external
    IDs such as imdb/tmdb/tvdb) alongside the list of candidate matches returned by
    the Plex metadata agent - the same candidates shown in Plex's "Fix Match"
    dialog. Feed a candidate's ``guid`` to ``media_fix_match`` to apply it.

    Args:
        media_title: Title of the media (optional if media_id is provided)
        media_id: Plex rating key to directly fetch the item (optional if media_title is provided)
        library_name: Optional library name to limit search to when using media_title
        libtype: Optional content type to limit search to (movie, show, season, episode,
            artist, album, track)
        search_title: Optional title to search candidates for, instead of the item's own title
        search_year: Optional year to refine the candidate search
        search_agent: Optional metadata agent identifier to search with (defaults to the library's agent)
    """
    try:
        plex = connect_to_plex()

        item, error = _resolve_media(plex, media_title, media_id, library_name, libtype)
        if error is not None:
            return error

        if not hasattr(item, 'matches'):
            return json.dumps({
                "error": f"Media type '{getattr(item, 'type', 'unknown')}' does not support matching."
            }, indent=4)

        guid = getattr(item, 'guid', None)
        result = {
            "id": getattr(item, 'ratingKey', None),
            "title": getattr(item, 'title', None),
            "type": getattr(item, 'type', None),
            "current": {
                "guid": guid,
                "agent": _agent_from_guid(guid),
                "external_ids": _external_guids(item),
                "year": getattr(item, 'year', None),
            },
        }

        # Candidate matches from the agent. This performs a live agent lookup, so
        # surface failures as a field rather than failing the whole call.
        match_kwargs = {}
        if search_agent:
            match_kwargs['agent'] = search_agent
        if search_title:
            match_kwargs['title'] = search_title
        if search_year:
            match_kwargs['year'] = search_year
        try:
            candidates = item.matches(**match_kwargs)
            result["candidates"] = [_serialize_candidate(c) for c in candidates]
        except Exception as e:
            result["candidates"] = []
            result["candidates_error"] = str(e)

        return json.dumps(result, indent=4)

    except Exception as e:
        return json.dumps({"error": f"Error getting match info: {str(e)}"}, indent=4)


@mcp.tool()
async def media_fix_match(media_title: str = None, media_id: int = None, library_name: str = None,
                          libtype: str = None,
                          guid: str = None, auto: bool = False,
                          search_agent: str = None) -> str:
    """(Re)match a media item to a specific candidate, or auto-match to Plex's top pick.

    Provide ``guid`` (taken from a candidate returned by ``media_get_match``) to
    apply a specific match, or set ``auto=True`` to accept the metadata agent's
    highest-scoring candidate. This changes the item's identity and re-pulls its
    metadata from the agent.

    Args:
        media_title: Title of the media (optional if media_id is provided)
        media_id: Plex rating key to directly fetch the item (optional if media_title is provided)
        library_name: Optional library name to limit search to when using media_title
        libtype: Optional content type to limit search to (movie, show, season, episode,
            artist, album, track)
        guid: The guid of the candidate match to apply (from media_get_match candidates)
        auto: If True, auto-match to the agent's top candidate instead of a specific guid
        search_agent: Optional metadata agent identifier to match with (defaults to the library's agent)
    """
    try:
        plex = connect_to_plex()

        if not guid and not auto:
            return json.dumps({
                "error": "Provide 'guid' (from media_get_match candidates) or set auto=True."
            }, indent=4)

        item, error = _resolve_media(plex, media_title, media_id, library_name, libtype)
        if error is not None:
            return error

        if not hasattr(item, 'fixMatch'):
            return json.dumps({
                "error": f"Media type '{getattr(item, 'type', 'unknown')}' does not support matching."
            }, indent=4)

        previous_guid = getattr(item, 'guid', None)

        if auto:
            try:
                item.fixMatch(auto=True, agent=search_agent)
            except Exception as e:
                return json.dumps({"error": f"Auto-match failed: {str(e)}"}, indent=4)
        else:
            # Resolve the SearchResult whose guid matches, so fixMatch gets a real
            # candidate object rather than a hand-built one.
            try:
                candidates = item.matches(agent=search_agent) if search_agent else item.matches()
            except Exception as e:
                return json.dumps({"error": f"Could not retrieve candidate matches: {str(e)}"}, indent=4)

            chosen = next((c for c in candidates if getattr(c, 'guid', None) == guid), None)
            if chosen is None:
                available = [getattr(c, 'guid', None) for c in candidates]
                return json.dumps({
                    "error": f"No candidate found with guid '{guid}'.",
                    "available_guids": available,
                }, indent=4)

            try:
                item.fixMatch(searchResult=chosen)
            except Exception as e:
                return json.dumps({"error": f"Fix match failed: {str(e)}"}, indent=4)

        # Reload to reflect the new match.
        try:
            item.reload()
        except Exception:
            pass

        new_guid = getattr(item, 'guid', None)
        return json.dumps({
            "matched": True,
            "id": getattr(item, 'ratingKey', None),
            "title": getattr(item, 'title', None),
            "previous_guid": previous_guid,
            "new_guid": new_guid,
            "agent": _agent_from_guid(new_guid),
            "external_ids": _external_guids(item),
        }, indent=4)

    except Exception as e:
        return json.dumps({"error": f"Error fixing match: {str(e)}"}, indent=4)


@mcp.tool()
async def media_unmatch(media_title: str = None, media_id: int = None, library_name: str = None,
                        libtype: str = None) -> str:
    """Remove the current metadata match from a media item, leaving it unmatched.

    Args:
        media_title: Title of the media (optional if media_id is provided)
        media_id: Plex rating key to directly fetch the item (optional if media_title is provided)
        library_name: Optional library name to limit search to when using media_title
        libtype: Optional content type to limit search to (movie, show, season, episode,
            artist, album, track)
    """
    try:
        plex = connect_to_plex()

        item, error = _resolve_media(plex, media_title, media_id, library_name, libtype)
        if error is not None:
            return error

        if not hasattr(item, 'unmatch'):
            return json.dumps({
                "error": f"Media type '{getattr(item, 'type', 'unknown')}' does not support matching."
            }, indent=4)

        previous_guid = getattr(item, 'guid', None)
        title = getattr(item, 'title', None)
        rating_key = getattr(item, 'ratingKey', None)

        try:
            item.unmatch()
        except Exception as e:
            return json.dumps({"error": f"Unmatch failed: {str(e)}"}, indent=4)

        return json.dumps({
            "unmatched": True,
            "id": rating_key,
            "title": title,
            "previous_guid": previous_guid,
        }, indent=4)

    except Exception as e:
        return json.dumps({"error": f"Error unmatching media: {str(e)}"}, indent=4)
