"""Reading and editing the tag collections on a media item.

Plex hangs ten kinds of tag off media - genre, style, mood, label and the rest -
but which ones apply is sparse and depends on the item's type: a track has moods
but no styles, a movie has writers but no moods. Rather than a parameter per
type (twenty of them, most invalid for any given item), the edit tool takes a
dict keyed by tag type and this module resolves it against what the item
actually supports.
"""

# tag type -> (add method, remove method, attribute holding the current values).
# similarArtist is the one that doesn't follow the pattern: it reads back as
# .similar, not .similarArtists.
TAG_TYPES = {
    'collection':    ('addCollection', 'removeCollection', 'collections'),
    'country':       ('addCountry', 'removeCountry', 'countries'),
    'director':      ('addDirector', 'removeDirector', 'directors'),
    'genre':         ('addGenre', 'removeGenre', 'genres'),
    'label':         ('addLabel', 'removeLabel', 'labels'),
    'mood':          ('addMood', 'removeMood', 'moods'),
    'producer':      ('addProducer', 'removeProducer', 'producers'),
    'similarArtist': ('addSimilarArtist', 'removeSimilarArtist', 'similar'),
    'style':         ('addStyle', 'removeStyle', 'styles'),
    'writer':        ('addWriter', 'removeWriter', 'writers'),
}

# How a tag type is named in a read-back response: the plural attribute name.
READ_KEYS = {key: attr for key, (_, _, attr) in TAG_TYPES.items()}


def _canonical(key):
    """Resolve a caller's tag-type name, tolerating case and underscores.

    'similar_artist', 'similarartist' and 'SimilarArtist' all mean the same
    thing; a caller shouldn't have to guess plexapi's camelCase.
    """
    if not isinstance(key, str):
        return None
    wanted = key.replace('_', '').replace('-', '').rstrip('s').lower()
    for canonical in TAG_TYPES:
        if canonical.rstrip('s').lower() == wanted:
            return canonical
    return None


def supported_tag_types(item):
    """The tag types this item actually accepts, as a sorted list."""
    return sorted(key for key, (add, _, _) in TAG_TYPES.items() if hasattr(item, add))


def read_tags(item):
    """Every tag collection the item carries, as ``{plural_name: [values]}``.

    Empty collections are omitted, so the response stays readable, but a type
    the item supports and has nothing in simply doesn't appear - which is the
    same as it being empty.
    """
    out = {}
    for key, (_, _, attr) in TAG_TYPES.items():
        values = [t.tag for t in (getattr(item, attr, None) or []) if getattr(t, 'tag', None)]
        if values:
            out[READ_KEYS[key]] = values
    return out


def _as_list(values):
    """Accept a single tag or a list of them."""
    if values is None:
        return []
    if isinstance(values, (list, tuple, set)):
        return [v for v in values if v is not None]
    return [values]


def apply_tags(item, add_tags=None, remove_tags=None):
    """Apply tag additions and removals to an item.

    Returns ``(changes, error)``. ``changes`` is a list of human-readable
    descriptions; ``error`` is a message string when the request names a tag
    type the item doesn't support or an edit fails, in which case earlier
    changes have already been applied.
    """
    changes = []

    for request, adding in ((add_tags, True), (remove_tags, False)):
        if not request:
            continue
        if not isinstance(request, dict):
            return changes, (
                f"{'add_tags' if adding else 'remove_tags'} must be a dict keyed by tag type, "
                f"e.g. {{\"genre\": [\"Rap\"], \"mood\": [\"Aggressive\"]}}."
            )

        for raw_key, values in request.items():
            key = _canonical(raw_key)
            if key is None:
                return changes, (
                    f"Unknown tag type '{raw_key}'. Valid types: {', '.join(sorted(TAG_TYPES))}."
                )

            add_method, remove_method, attr = TAG_TYPES[key]
            method_name = add_method if adding else remove_method
            if not hasattr(item, method_name):
                return changes, (
                    f"A {getattr(item, 'type', 'item')} has no '{key}' tag. "
                    f"A {getattr(item, 'type', 'item')} supports: {', '.join(supported_tag_types(item))}."
                )

            wanted = _as_list(values)
            if not wanted:
                continue

            # Compare against what's already there so a no-op stays a no-op and
            # the reported changes reflect what actually moved.
            current = {t.tag.lower(): t for t in (getattr(item, attr, None) or [])
                       if getattr(t, 'tag', None)}

            for value in wanted:
                present = str(value).lower() in current
                if adding == present:
                    continue
                try:
                    if adding:
                        getattr(item, add_method)(value)
                        current[str(value).lower()] = value
                        changes.append(f"added {key} '{value}'")
                    else:
                        getattr(item, remove_method)(current.pop(str(value).lower()))
                        changes.append(f"removed {key} '{value}'")
                except Exception as e:
                    verb = 'adding' if adding else 'removing'
                    return changes, f"Error {verb} {key} '{value}': {str(e)}"

    return changes, None
