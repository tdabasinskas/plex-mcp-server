"""Shared resolution of a single media item by rating key or title.

Every media tool needs the same thing: turn whatever the caller supplied - a
rating key, or a title plus optional library - into one Plex object, and say
something useful when that isn't possible. Keeping it here means the tools
disambiguate consistently and gain ``media_id`` support in one place.
"""

import json
from plexapi.exceptions import NotFound  # type: ignore

# Media types a caller can act on. Excludes collections, playlists and the
# people/tag hubs that hub search also returns.
MEDIA_TYPES = ['movie', 'show', 'season', 'episode', 'artist', 'album', 'track']


# What a title's surrounding context is called, per content type. A track and
# its album and artist can all share one title; these are what tell them apart.
CONTEXT_LABELS = {
    'track':   {'parentTitle': 'album',  'grandparentTitle': 'artist'},
    'album':   {'parentTitle': 'artist'},
    'episode': {'parentTitle': 'season', 'grandparentTitle': 'show'},
    'season':  {'parentTitle': 'show'},
}

# Types whose index is a meaningful position (track number, episode number).
INDEXED_TYPES = ('track', 'episode', 'season')


def describe_item(item):
    """Summarize an item enough for a caller to pick it out of a list of near-identical titles.

    A bare title/type/id triple is useless for music, where an artist, an album
    and a dozen tracks can share a name. Include whatever context the item
    carries so the caller can tell them apart and come back with a ``media_id``.
    """
    item_type = getattr(item, 'type', 'unknown')
    entry = {
        "title": getattr(item, 'title', 'Unknown'),
        "id": getattr(item, 'ratingKey', None),
        "type": item_type,
    }

    if getattr(item, 'year', None) is not None:
        entry["year"] = item.year
    if getattr(item, 'librarySectionTitle', None):
        entry["library"] = item.librarySectionTitle

    for attr, label in CONTEXT_LABELS.get(item_type, {}).items():
        value = getattr(item, attr, None)
        if value:
            entry[label] = value

    if item_type in INDEXED_TYPES and getattr(item, 'index', None) is not None:
        entry["index"] = item.index

    return entry


def resolve_media(plex, media_title=None, media_id=None, library_name=None,
                  libtype=None, allowed_types=None):
    """Resolve a single media item by id or title.

    Returns ``(item, error)``. On success ``item`` is the Plex object and ``error``
    is None. Otherwise ``item`` is None and ``error`` is a JSON string ready to
    return to the caller - either an error object, or, when the title matches
    several items, a disambiguation list whose entries carry the ``id`` needed to
    call back unambiguously.

    Args:
        plex: A connected PlexServer.
        media_title: Title to search for. Ignored when media_id is given.
        media_id: Plex rating key. Takes precedence over media_title.
        library_name: Restrict a title search to this library section.
        libtype: Restrict a title search to one content type (track, album,
            artist, movie, show, season, episode). The cheapest way to avoid
            disambiguation entirely.
        allowed_types: Item types to accept (defaults to MEDIA_TYPES).
    """
    allowed = MEDIA_TYPES if allowed_types is None else allowed_types

    if media_id is None and not media_title:
        return None, json.dumps({"error": "Either media_id or media_title must be provided."}, indent=4)

    # Direct fetch by rating key - no ambiguity to resolve.
    if media_id is not None:
        try:
            return plex.fetchItem(media_id), None
        except Exception as e:
            return None, json.dumps({"error": f"Could not find media with ID {media_id}. Error: {str(e)}"}, indent=4)

    # Title search. plex.search is hub search: fuzzy, spell-corrected, and it
    # spans every content type, so tracks and albums come back alongside
    # artists. Scope it with sectionId rather than switching to the library
    # filter API, which takes different kwargs entirely.
    search_args = {}
    if library_name:
        try:
            section = plex.library.section(library_name)
        except NotFound:
            return None, json.dumps({"error": f"Library '{library_name}' not found"}, indent=4)
        search_args['sectionId'] = section.key
    if libtype:
        search_args['mediatype'] = libtype

    try:
        results = plex.search(query=media_title, **search_args)
    except Exception as e:
        return None, json.dumps({"error": f"Error searching for '{media_title}': {str(e)}"}, indent=4)

    valid = [item for item in (results or []) if getattr(item, 'type', None) in allowed]

    if not valid:
        scope = f" in library '{library_name}'" if library_name else ""
        of_type = f" of type '{libtype}'" if libtype else ""
        return None, json.dumps(
            {"error": f"No media found matching '{media_title}'{of_type}{scope}."}, indent=4)

    if len(valid) > 1:
        return None, json.dumps([describe_item(item) for item in valid], indent=4)

    return valid[0], None
