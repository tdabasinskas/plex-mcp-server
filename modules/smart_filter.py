"""Reading back the saved filter of a smart playlist or smart collection.

The filter is stored on the server as a search URI. plexapi parses it into a
dict, but that translation is lossy in one direction that matters: Plex's URL
form and plexapi's filter-dict form spell the same operator differently (see
``library_get_smart_filter_options``). Reporting both the parsed dict and the
raw URI lets a caller verify what was actually saved rather than trusting the
reconstruction.
"""

from collections import deque
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

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

    # Parse with our own reader rather than plexapi's. It agrees with plexapi on
    # everything plexapi can read, survives the groups plexapi dies on, and drops
    # the empty-group artefacts plexapi leaves behind ({"and": []}) - so the
    # parsed structure matches what the raw string actually means.
    try:
        parsed, pruned = _parse_tolerantly(raw)
        result["smartFilter"] = parsed
        if pruned:
            result["smartFilterNote"] = (
                "The saved filter contained a group holding no criteria. An empty group "
                "constrains nothing, so it was left out of smartFilter and the filter's meaning "
                "is unchanged. smartFilterRaw is exactly as Plex stored it."
            )
    except Exception as e:
        result["smartFilter"] = {
            "error": f"Could not parse the saved filter: {type(e).__name__}: {e}",
        }

    return result


def _parse_tolerantly(raw):
    """Parse a filter URI, returning ``(parsed, pruned_an_empty_group)``.

    plexapi's ``_parseFilterGroups`` ends with ``currentFiltersStack.pop()``, which
    raises IndexError whenever a group finishes having collected nothing. Two
    things cause that, and Plex writes both: an empty ``push``/``pop`` pair, and a
    reserved key (``sort``, ``limit``, ``type``) landing inside a group, which
    breaks out of the loop before anything is added. A group holding nothing
    constrains nothing, so yielding an empty result for it - and letting the
    parent skip it - preserves the filter's meaning exactly.

    Otherwise this mirrors plexapi's parser, so anything it can read reads the same.
    """
    content = urlsplit(unquote(raw))
    feed = deque()
    for key, value in parse_qsl(content.query):
        # Move the = sign onto the key when the operator is ==, as plexapi does.
        if value.startswith("="):
            key, value = f"{key}=", value[1:]
        feed.append((key, value))

    pruned = []
    return _parse_feed(feed, pruned), bool(pruned)


# The query keys plexapi handles itself rather than treating as filter clauses.
SPECIAL_KEYS = {'type', 'sort'}
INTEGER_KEYS = {'includeGuids', 'limit'}
AS_IS_KEYS = {'group', 'having'}
RESERVED_KEYS = SPECIAL_KEYS | INTEGER_KEYS | AS_IS_KEYS


def _parse_feed(feed, pruned=None):
    """Mirror of plexapi's ``_parseQueryFeed`` over an already-built feed."""
    from plexapi import utils as plexapi_utils

    parsed = {}
    while feed:
        key, value = feed.popleft()
        if key in INTEGER_KEYS:
            parsed[key] = int(value)
        elif key in AS_IS_KEYS:
            parsed[key] = value
        elif key == 'type':
            parsed['libtype'] = plexapi_utils.reverseSearchType(value)
        elif key == 'sort':
            parsed['sort'] = value.split(',')
        else:
            feed.appendleft((key, value))
            group = _parse_groups(feed, set(RESERVED_KEYS) | {'pop'}, pruned)
            if not group:
                continue  # nothing in it; don't fold an empty dict into the result
            if 'filters' in parsed:
                parsed['filters'] = {'and': [parsed['filters'], group]}
            else:
                parsed['filters'] = group
    return parsed


def _parse_groups(feed, return_on, pruned=None):
    """Mirror of plexapi's ``_parseFilterGroups``, but empty groups yield {} not IndexError."""
    stack = []
    operator = None

    while feed:
        key, value = feed.popleft()
        if key == 'push':
            nested = _parse_groups(feed, return_on, pruned)
            if nested:
                stack.append(nested)
            elif pruned is not None:
                # A group that held nothing adds nothing; dropping it keeps the
                # filter's meaning and keeps {} out of the parent's clause list.
                pruned.append(True)
        elif key in return_on:
            if key != 'pop':
                feed.appendleft((key, value))
            break
        elif key in ('and', 'or'):
            if operator and operator != key:
                raise ValueError(
                    'cannot have different logical operators for the same filter group')
            operator = key
        else:
            stack.append({key: value})

    # A group holding nothing is reported as nothing, whether or not it carried an
    # operator. Returning {'and': []} would be truthy and survive the parent's
    # skip, leaving artefacts like {"and": [{}, {"and": []}]} in the output.
    if not stack:
        return {}
    if not operator and len(stack) > 1:
        operator = 'and'
    if operator:
        return {operator: stack}
    return stack.pop()


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


def _query_is_decoded(query):
    """True when a query string's separators are literal rather than encoded.

    A real query is a series of ``key=value`` pairs, so every '&'-separated
    segment contains a literal '='. When the body is still percent-encoded the
    whole thing is one segment with no '=' in it at all. This can't misfire on a
    value that legitimately contains %26 or %3D, because the surrounding
    segments still carry their own literal '='.
    """
    segments = [seg for seg in (query or '').split('&') if seg]
    return bool(segments) and all('=' in seg for seg in segments)


def _with_literal_query(raw):
    """Return the URI with its query in splittable form.

    Plex hands back ``content`` at varying levels of encoding, and finding the
    query means decoding until it splits. But when the whole URI is encoded once
    uniformly, that same decode also unescapes the *values* - a having clause
    stored as ``min%28...%29`` comes back as ``min(...)``. Writing that back
    literally is fatal: Plex cannot parse a having clause with raw parentheses
    and silently drops the entire filter, matching the whole library.

    So every segment written back is normalized to one level of encoding
    regardless of how it arrived. See ``_canonical_segment``.
    """
    for _ in range(4):
        head, sep, query = raw.partition('?')
        if sep and _query_is_decoded(query):
            return raw
        unquoted = unquote(raw)
        if unquoted == raw:
            return raw
        raw = unquoted
    return raw


def _canonical_segment(segment):
    """Normalize one ``key=value`` pair to exactly one level of encoding.

    Decode fully, then encode once. Applied to every segment whatever shape the
    saved URI arrived in, so the result is the same string either way - which is
    what the explicit-filters path produces through urlencode, and what Plex
    accepts. Splitting has already happened, so decoding a value here cannot
    disturb the separators.

    ``quote`` leaves alphanumerics and ``_.-~`` alone, so ``track.label`` passes
    through untouched while ``min(...)`` becomes ``min%28...%29`` and an operator
    suffix like ``userRating>>`` becomes ``userRating%3E%3E``.
    """
    key, sep, value = segment.partition('=')
    if not sep:
        return quote(unquote(key), safe='')
    return quote(unquote(key), safe='') + '=' + quote(unquote(value), safe='')


# Query keys that affect presentation rather than what the item matches.
# group and having are NOT here: they change the result set.
PRESENTATION_KEYS = {'sort', 'limit', 'type', 'includeGuids'}


def _criteria_segments(raw):
    """The query segments that decide what an item matches, sort/limit/type aside.

    Compared before and after a write to prove an edit didn't quietly widen the
    filter. Fully decoded first, so two spellings of the same criterion compare
    equal - the comparison is about meaning, not encoding.
    """
    query = urlsplit(_with_literal_query(raw)).query
    return sorted(unquote(seg) for seg in (query or '').split('&')
                  if seg and seg.split('=', 1)[0] not in PRESENTATION_KEYS)


def _saved_params(raw, wanted):
    """Read named top-level query params straight out of the saved URI."""
    query = urlsplit(_with_literal_query(raw)).query
    found = {}
    for segment in (query or '').split('&'):
        if '=' not in segment:
            continue
        key, value = segment.split('=', 1)
        if key in wanted and key not in found:
            found[key] = value
    return found


def _verify_updates(uri, updates):
    """Confirm each requested parameter landed exactly once with its new value.

    Cheap insurance against the failure this replaced: an edit that reports
    success while changing nothing. Checked on the URI we built, so it costs no
    extra request.
    """
    query = urlsplit(uri).query
    segments = [seg for seg in (query or '').split('&') if '=' in seg]
    for key, value in updates.items():
        matches = [seg.split('=', 1)[1] for seg in segments if seg.split('=', 1)[0] == key]
        if len(matches) != 1:
            return f"'{key}' appears {len(matches)} times in the rebuilt filter, expected exactly once"
        if unquote(matches[0]) != str(value):
            return f"'{key}' is {unquote(matches[0])!r} in the rebuilt filter, expected {str(value)!r}"
    return None


def _replace_query_params(raw, updates):
    """Return ``raw`` with the named query params replaced, every other segment byte-identical.

    Rewriting the string rather than re-encoding a parsed structure is what lets a
    sort-only edit preserve filter clauses exactly - including ones no parser can
    read. Only keys present in ``updates`` are touched.
    """
    scheme_split = urlsplit(_with_literal_query(raw))
    segments = scheme_split.query.split('&') if scheme_split.query else []

    out, replaced = [], set()
    for segment in segments:
        key = segment.split('=', 1)[0]
        if key in updates:
            if key not in replaced:
                out.append(f'{key}={quote(str(updates[key]), safe="")}')
                replaced.add(key)
            continue  # drop any later duplicate of a key we replaced
        # Finding the query may have unescaped the values; normalizing every
        # segment puts exactly one level of encoding back, whatever arrived.
        out.append(_canonical_segment(segment))

    for key, value in updates.items():
        if key not in replaced:
            out.append(f'{key}={quote(str(value), safe="")}')

    return urlunsplit(scheme_split._replace(query='&'.join(out)))


def _item_count(obj):
    """How many items the item currently holds, or None if the server won't say.

    A playlist reports leafCount, a collection childCount. This is the only
    invariant that survives an encoding bug: a filter can be spelled two ways
    that compare equal as text while Plex accepts one and silently discards the
    other, and the count is what tells them apart.
    """
    for attr in ('leafCount', 'childCount'):
        value = getattr(obj, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _stored_content(obj):
    """Re-read the item's filter URI from the server, or None if it can't be read."""
    try:
        obj.reload()
    except Exception:
        pass
    return getattr(obj, 'content', None)


def _confirm_write(obj, original_raw, expected_criteria, expected_count=None):
    """Check what Plex actually stored, and undo the write if the criteria changed.

    Reporting the filter we *intended* to save proves nothing - a wipe reports a
    healthy-looking diff right up until you count the items. This compares the
    criteria the server came back with against the ones that were meant to
    survive, and restores the previous URI if they don't match.

    Returns ``(stored_raw, error)``.
    """
    stored = _stored_content(obj)
    if not stored:
        return None, (
            "The edit was sent, but the saved filter could not be read back to confirm it. "
            "Check the item before relying on this change."
        )

    actual = _criteria_segments(stored)
    actual_count = _item_count(obj)
    count_changed = (expected_count is not None and actual_count is not None
                     and actual_count != expected_count)

    if actual == expected_criteria and not count_changed:
        return stored, None

    if count_changed:
        reason = (f"it now holds {actual_count} items instead of {expected_count}. The filter "
                  f"reads the same, so Plex rejected how it was written rather than what it says")
    else:
        reason = (f"{len(expected_criteria)} filter criteria before, {len(actual)} after")

    # The write changed what the item matches. Put the original back.
    restored = False
    try:
        key = f"{obj.key}/items{utils.joinArgs({'uri': original_raw})}"
        obj._server.query(key, method=obj._server._session.put)
        restored_raw = _stored_content(obj) or ''
        restored = (_criteria_segments(restored_raw) == expected_criteria
                    and (expected_count is None or _item_count(obj) in (None, expected_count)))
    except Exception:
        restored = False

    return stored, (
        f"The edit changed what this item matches, which was not intended: {reason}. "
        + ("The previous filter has been restored." if restored else
           "RESTORING THE PREVIOUS FILTER FAILED - the item is left with the wrong filter. "
           f"Its previous definition was: {unquote(original_raw)}")
    )


def update_smart_filter(obj, filters=None, sort=None, limit=None, libtype=None,
                        allow_empty_filter=False):
    """Update a smart playlist's or collection's saved search, preserving what wasn't passed.

    plexapi's ``updateFilters`` rebuilds the search URI from its arguments alone,
    so anything omitted is silently dropped - a sort-only edit erases the filters
    and the item becomes the whole library.

    When ``filters`` isn't being changed, this rewrites only the parameters that
    are, leaving every filter clause in the saved URI byte-identical. Nothing is
    round-tripped through a parser, so a filter no parser can read is still
    editable - which matters, because Plex writes filters plexapi cannot parse.

    Note this merges at the parameter level, not within ``filters``: passing
    ``filters`` replaces the whole filter set, it does not merge clause by clause.

    Returns ``(before, after, error)`` - the definitions either side of the edit,
    so a caller can see exactly what changed.
    """
    raw = getattr(obj, 'content', None)
    if not raw:
        return None, None, (
            "Refusing to edit: the server returned no filter definition for this item, "
            "so there is nothing to preserve and an edit would replace it blindly."
        )

    # Read the current definition for reporting only. A filter that can't be
    # parsed is still perfectly editable, so a failure here must not block.
    before, parse_error = current_definition(obj, raw)
    if before is None:
        before = {"unparsed": True, "raw": unquote(raw), "reason": parse_error}

    if filters is None:
        # Preserve the saved filter clauses verbatim; change only what was asked
        # for. No emptiness check here: the criteria aren't being touched, so this
        # path cannot make an item match more than it already does. Checking
        # anyway only ever produces false refusals - a grouped filter keeps its
        # condition in `having=`, which no clause count can recognise.
        updates = {}
        if sort is not None:
            updates['sort'] = ','.join(sort) if isinstance(sort, list) else sort
        if limit is not None:
            updates['limit'] = limit
        if libtype is not None:
            updates['type'] = utils.searchType(libtype)
        if not updates:
            return before, before, None  # nothing asked for; don't write

        new_uri = _replace_query_params(raw, updates)

        # Never report success for an edit that didn't take. Appending instead of
        # replacing, then claiming it worked, is the failure this guards.
        mismatch = _verify_updates(new_uri, updates)
        if mismatch:
            return before, None, (
                f"Refusing to save: the rebuilt filter doesn't match what was asked for - "
                f"{mismatch}. Nothing was written."
            )

        # This path must not change what the item matches. Prove it before writing.
        criteria = _criteria_segments(raw)
        count_before = _item_count(obj)
        if _criteria_segments(new_uri) != criteria:
            return before, None, (
                "Refusing to save: rebuilding the filter to change the sort would have altered "
                "its criteria. Nothing was written."
            )

        try:
            key = f"{obj.key}/items{utils.joinArgs({'uri': new_uri})}"
            obj._server.query(key, method=obj._server._session.put)
        except Exception as e:
            return before, None, f"Could not save the filter: {type(e).__name__}: {e}"

        # And prove it again against what the server actually stored - including
        # the item count, which is what catches a filter Plex silently discarded.
        stored, error = _confirm_write(obj, raw, criteria, expected_count=count_before)
        if error:
            return before, None, error

        parsed, _ = _parse_tolerantly(stored)
        return before, parsed, None

    # Filters are being replaced, so the saved clauses are going anyway. Take the
    # parameters not being changed from the raw query rather than the parse, so
    # this path doesn't depend on the parser either.
    saved = _saved_params(raw, ('sort', 'limit', 'type'))

    after = {
        "filters": filters,
        "sort": sort if sort is not None else (unquote(saved['sort']).split(',') if 'sort' in saved else None),
        "limit": limit if limit is not None else (int(saved['limit']) if 'limit' in saved else None),
        "libtype": libtype if libtype is not None else (
            utils.reverseSearchType(saved['type']) if 'type' in saved else None),
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

    # Criteria are meant to change here, so they can't be compared to the old
    # ones - but a request for criteria that stores none is still a wipe.
    stored, error = _confirm_write(obj, raw, _criteria_segments(uri))
    if error:
        return before, None, error

    parsed, _ = _parse_tolerantly(stored)
    return before, parsed, None
