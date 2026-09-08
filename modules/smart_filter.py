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


def describe_smart_filter(obj, raw_content=None):
    """Build the ``smartFilter`` / ``smartFilterRaw`` fields for a smart playlist or collection.

    Returns a dict to merge into a response. ``smartFilter`` is always present,
    carrying an ``error`` object when the filter can't be read - a caller must be
    able to tell "this item has no filter" from "we failed to read it", which a
    missing key cannot express.

    Args:
        obj: A smart Playlist or Collection.
        raw_content: The item's ``content`` URI, captured before any reload().
            A Playlist's key addresses its /items representation, which need not
            carry ``content``, so reloading can leave the attribute empty. Pass
            the value read before reloading and the filter survives it.
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
