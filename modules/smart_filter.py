"""Reading back the saved filter of a smart playlist or smart collection.

The filter is stored on the server as a search URI. plexapi parses it into a
dict, but that translation is lossy in one direction that matters: Plex's URL
form and plexapi's filter-dict form spell the same operator differently (see
``library_get_smart_filter_options``). Reporting both the parsed dict and the
raw URI lets a caller verify what was actually saved rather than trusting the
reconstruction.
"""

from collections import deque
from urllib.parse import parse_qsl, unquote, urlsplit

from plexapi import utils  # type: ignore


def describe_smart_filter(obj, raw_content=None):
    """Build the ``smartFilter`` / ``smartFilterRaw`` fields for a smart playlist or collection.

    Returns a dict to merge into a response. ``smartFilter`` is always present,
    carrying an ``error`` object when the filter can't be read - a caller must be
    able to tell "this item has no filter" from "we failed to read it", which a
    missing key cannot express.

    Args:
        obj: A smart Playlist or Collection.
        raw_content: The item's ``content`` URI, captured before any reload().
            A reload can return a representation that omits ``content``, and once
            the attribute is empty the filter is unrecoverable from the object.
            Pass the value read before reloading and it survives regardless.
    """
    raw = raw_content or getattr(obj, 'content', None)

    if not raw:
        return {
            "smartFilterRaw": None,
            "smartFilter": {
                "error": "The server returned no filter definition (content is empty) for this smart item."
            },
        }

    result = {"smartFilterRaw": unquote(raw)}

    # _parseFilters takes the content explicitly, so it works off the URI we
    # captured rather than whatever state the object is in now.
    try:
        result["smartFilter"] = obj._parseFilters(raw)
        return result
    except Exception as e:
        first_error = f"{type(e).__name__}: {e}"

    # plexapi's parser can't represent an empty filter group and dies on one
    # with "IndexError: pop from empty list". Plex will save such a group, and
    # it matches nothing by definition, so dropping it can't change which items
    # the filter selects. Retry without them rather than lose the whole filter.
    try:
        result["smartFilter"] = _parse_without_empty_groups(obj, raw)
        result["smartFilterNote"] = (
            "The saved filter contained an empty group (a push/pop pair with nothing between it), "
            "which plexapi's parser cannot represent. The empty group was ignored - it matches "
            "nothing, so the filter's meaning is unchanged. smartFilterRaw is exactly as Plex stored it."
        )
    except Exception as e:
        result["smartFilter"] = {
            "error": f"Could not parse the saved filter: {first_error}",
            "retry_error": f"{type(e).__name__}: {e}",
        }

    return result


def _parse_without_empty_groups(obj, raw):
    """Parse a filter URI with empty push/pop groups removed.

    Mirrors plexapi's ``_parseFilters`` - which builds its feed internally and so
    gives no way to clean it - then hands the cleaned feed to the same parser.
    """
    content = urlsplit(unquote(raw))
    feed = deque()
    for key, value in parse_qsl(content.query):
        # Move the = sign onto the key when the operator is ==, as plexapi does.
        if value.startswith("="):
            key, value = f"{key}=", value[1:]
        feed.append((key, value))

    _drop_empty_groups(feed)
    return obj._parseQueryFeed(feed)


def _drop_empty_groups(feed):
    """Remove every ``push`` immediately followed by ``pop``, in place.

    Repeats until none remain, since removing an inner empty group can leave its
    parent empty in turn (push push pop pop -> push pop -> nothing).
    """
    removing = True
    while removing:
        removing = False
        for i in range(len(feed) - 1):
            if feed[i][0] == "push" and feed[i + 1][0] == "pop":
                del feed[i]
                del feed[i]
                removing = True
                break
    return feed


def current_definition(obj, raw_content=None):
    """Read a smart item's saved search as ``(definition, error)``.

    ``definition`` is the parsed dict - ``libtype``, ``sort``, ``limit``,
    ``filters`` - in the same shape the edit tools accept, so it can be fed
    straight back. ``error`` is a message when it can't be read.
    """
    described = describe_smart_filter(obj, raw_content)
    definition = described.get("smartFilter")
    if not isinstance(definition, dict) or "error" in definition:
        message = (definition or {}).get("error", "the filter could not be read")
        return None, (
            f"Refusing to edit: the current filter must be read first so the parts you "
            f"don't change are preserved, but {message}"
        )
    return definition, None


def update_smart_filter(obj, filters=None, sort=None, limit=None, libtype=None,
                        allow_empty_filter=False):
    """Update a smart playlist's or collection's saved search, preserving what wasn't passed.

    plexapi's ``updateFilters`` rebuilds the search URI from its arguments alone,
    so anything omitted is silently dropped - a sort-only edit erases the filters
    and the item becomes the whole library. Read the current definition first and
    fall back to it per parameter, so omitting something leaves it alone.

    Note this merges at the parameter level, not within ``filters``: passing
    ``filters`` replaces the whole filter set, it does not merge clause by clause.

    Returns ``(before, after, error)`` - the definitions either side of the edit,
    so a caller can see exactly what changed.
    """
    raw_content = getattr(obj, 'content', None)

    before, error = current_definition(obj, raw_content)
    if error:
        return None, None, error

    after = {
        "filters": before.get("filters") if filters is None else filters,
        "sort": before.get("sort") if sort is None else sort,
        "limit": before.get("limit") if limit is None else limit,
        "libtype": before.get("libtype") if libtype is None else libtype,
    }

    # An empty filter set matches the entire library. That is almost never what
    # someone editing a curated filter means, and it is unrecoverable once saved,
    # so it takes an explicit opt-in.
    if not after["filters"] and not allow_empty_filter:
        return before, None, (
            "Refusing to save a smart filter with no criteria: it would match the entire "
            "library and replace the current definition irrecoverably. Pass the filters you "
            "want, or set allow_empty_filter=true if an unfiltered item is genuinely intended."
        )

    try:
        section = obj.section()
        # Build and PUT the search key the way plexapi's updateFilters does.
        # Doing it here rather than calling updateFilters is what lets libtype be
        # preserved: Playlist.updateFilters hardcodes it to the section's default,
        # so a smart playlist created with a different libtype silently loses it.
        search_key = section._buildSearchKey(
            sort=after["sort"], libtype=after["libtype"],
            limit=after["limit"], filters=after["filters"])
        uri = f'{obj._server._uriRoot()}{search_key}'
        key = f"{obj.key}/items{utils.joinArgs({'uri': uri})}"
        obj._server.query(key, method=obj._server._session.put)
    except Exception as e:
        return before, None, f"Could not save the filter: {type(e).__name__}: {e}"

    return before, after, None
