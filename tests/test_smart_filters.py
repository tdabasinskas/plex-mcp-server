"""Regression tests for smart-filter editing.

Run with ``python tests/test_smart_filters.py`` - no test framework required.

These exist because editing a smart filter has now broken three separate ways,
each of which silently changed what a playlist matched:

1. A sort-only edit cleared the filters, and the playlist became the whole library.
2. A sort-only edit silently did nothing, while reporting success.
3. A sort-only edit cleared the filters again, through a different encoding of the
   saved URI, while the response reported a healthy-looking filter.

All three would have been caught by one check: take a playlist with a filter, edit
only its sort, and assert what the server ends up holding still matches the same
things. That is what `test_sort_only_preserves_criteria` does, across every
encoding of the saved URI that Plex is known to hand back.

The fake server below deliberately *stores what it is sent and serves it back*.
Earlier fakes did not, which is how a write that reported success while saving
something else went unnoticed.
"""

import sys
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, unquote_plus, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plexapi.mixins.smart_filter import SmartFilterMixin  # type: ignore

from modules.smart_filter import (  # noqa: E402
    _criteria_segments,
    describe_smart_filter,
    update_smart_filter,
)

ROOT = 'server://abc/com.plexapp.plugins.library'
CURATED = 102
FULL_LIBRARY = 317338
PATH = ROOT + '/library/sections/3/all'

# Shaped like a real curated playlist: a label criterion, grouped, with a having
# clause - the combination that broke most often.
QUERY = ('type=10&track.label=709338&group=grandparentTitle'
         '&having=min%28album.originallyAvailableAt%29&sort=titleSort&limit=102')


def encodings_of(query):
    """Every form Plex has been observed to return `content` in.

    The last one is the dangerous one: encoded uniformly, so decoding far enough
    to find the query also unescapes the values.
    """
    return {
        'literal ?': PATH + '?' + query,
        'encoded ? (%3F)': PATH + quote('?' + query, safe=''),
        'literal ?, encoded body': PATH + '?' + quote(query, safe=''),
        'encoded uniformly': PATH + quote('?' + unquote(query), safe=''),
    }


class FakeSection:
    METADATA_TYPE = 'track'
    LIBTYPES = {'track': 10, 'album': 9, 'artist': 8}

    def __init__(self):
        self.calls = []

    def _buildSearchKey(self, sort=None, libtype=None, limit=None, filters=None, **kwargs):
        self.calls.append(dict(sort=sort, libtype=libtype, limit=limit, filters=filters))
        parts = []
        if libtype:
            parts.append(f'type={self.LIBTYPES.get(libtype, 10)}')

        def clauses(node, out):
            for key, value in (node or {}).items():
                if key in ('and', 'or'):
                    out.append('push=1')
                    for index, sub in enumerate(value):
                        if index:
                            out.append(f'{key}=1')
                        clauses(sub, out)
                    out.append('pop=1')
                else:
                    out.append(f'{key}={value}')

        clauses(filters, parts)
        if sort:
            parts.append('sort=' + (','.join(sort) if isinstance(sort, list) else sort))
        if limit is not None:
            parts.append(f'limit={limit}')
        return '/library/sections/3/all?' + '&'.join(parts)


class FakeServer:
    """Stores what it is PUT and serves it back, like the real one."""

    class _Session:
        put = 'PUT'

    _session = _Session()

    def __init__(self, owner):
        self.owner = owner
        self.puts = []

    def _uriRoot(self):
        return ROOT

    def query(self, key, method=None):
        self.puts.append(key)
        uri = dict(parse_qsl(urlsplit(key).query)).get('uri')
        if uri is None:
            return
        self.owner.content = uri
        # Plex cannot parse a having clause with unescaped parentheses. Rather
        # than erroring it drops the whole filter and matches everything - the
        # failure that made three separate fixes look correct in the response.
        body = uri.partition('?')[2]
        if '(' in unquote_plus(body.replace('%25', '%')) and '%28' not in body:
            self.owner.content = PATH + '?type=10'
            self.owner.leafCount = FULL_LIBRARY
        else:
            self.owner.leafCount = CURATED


class FakeSmartPlaylist(SmartFilterMixin):
    smart = True
    title = 'Starred: Top'
    ratingKey = 7
    key = '/playlists/7'
    leafCount = CURATED

    def __init__(self, content, server_factory=FakeServer):
        self.content = content
        self._server = server_factory(self)
        self._section = FakeSection()

    def section(self):
        return self._section

    def reload(self):
        pass


class WipingServer(FakeServer):
    """Stores something that matches everything, whatever it was sent."""

    def query(self, key, method=None):
        self.puts.append(key)
        if len(self.puts) == 1:
            self.owner.content = PATH + '?type=10&sort=track.random'
        else:
            uri = dict(parse_qsl(urlsplit(key).query)).get('uri')
            if uri:
                self.owner.content = uri


class SilentlyIgnoringServer(FakeServer):
    """Stores exactly what it was sent, but matches everything anyway.

    Models the failure that defeated three fixes: the saved filter reads
    correctly, so any text comparison of the criteria passes, while Plex has in
    fact discarded it. Only the item count tells them apart.
    """

    def query(self, key, method=None):
        self.puts.append(key)
        uri = dict(parse_qsl(urlsplit(key).query)).get('uri')
        if uri is None:
            return
        self.owner.content = uri
        self.owner.leafCount = CURATED if len(self.puts) > 1 else FULL_LIBRARY


# --------------------------------------------------------------------------- #

FAILURES = []


def check(label, condition, detail=''):
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f"\n      {detail}" if not condition else ''))
    if not condition:
        FAILURES.append(label)


def test_sort_only_preserves_criteria():
    """The one check that would have caught every failure so far."""
    for name, raw in encodings_of(QUERY).items():
        playlist = FakeSmartPlaylist(raw)
        before = _criteria_segments(raw)

        _, after, error = update_smart_filter(playlist, sort='track.random')
        check(f'[{name}] sort-only edit succeeds', error is None, str(error))

        # What the server ended up holding must still match the same things.
        check(f'[{name}] criteria unchanged after the write',
              _criteria_segments(playlist.content) == before,
              f'{before}\n      -> {_criteria_segments(playlist.content)}')

        stored = unquote(playlist.content)
        check(f'[{name}] parentheses stay escaped on the wire',
              'min%28' in playlist.content or 'min%2528' in playlist.content, playlist.content)
        for fragment in ('track.label=709338', 'group=grandparentTitle', 'having=', 'type=10'):
            check(f'[{name}] {fragment} survived', fragment in stored, stored)
        check(f'[{name}] the item count is unchanged',
              playlist.leafCount == CURATED,
              f'{CURATED} -> {playlist.leafCount}')
        check(f'[{name}] the sort actually changed', 'sort=track.random' in stored, stored)
        check(f'[{name}] exactly one sort=', stored.count('sort=') == 1, stored)
        check(f'[{name}] filter_after reports storage, not intent',
              after and after.get('sort') == ['track.random'], str(after))


def test_a_wiping_write_is_caught_and_undone():
    """If the server stores something that matches more, say so and put it back."""
    playlist = FakeSmartPlaylist(PATH + '?' + QUERY, server_factory=WipingServer)
    before = _criteria_segments(playlist.content)

    _, after, error = update_smart_filter(playlist, sort='track.random')
    check('a wiping write is detected', bool(error) and 'changed what this item matches' in error, str(error))
    check('  reported as an error, not success', after is None, str(after))
    check('  the previous filter is restored', _criteria_segments(playlist.content) == before,
          f'{before} -> {_criteria_segments(playlist.content)}')


def test_clearing_filters_is_refused_unless_asked_for():
    playlist = FakeSmartPlaylist(PATH + '?' + QUERY)
    _, _, error = update_smart_filter(playlist, filters={})
    check('clearing the filter is refused', bool(error) and 'entire library' in error, str(error))
    check('  and nothing was written', playlist._server.puts == [], str(playlist._server.puts))

    playlist = FakeSmartPlaylist(PATH + '?' + QUERY)
    _, _, error = update_smart_filter(playlist, filters={}, allow_empty_filter=True)
    check('clearing is possible on explicit opt-in', error is None, str(error))


def test_replacing_filters_keeps_the_other_parameters():
    for name, raw in encodings_of(QUERY).items():
        playlist = FakeSmartPlaylist(raw)
        _, after, error = update_smart_filter(playlist, filters={'genre': 'Jazz'})
        check(f'[{name}] replacing filters succeeds', error is None, str(error))
        check(f'[{name}] libtype inherited', after and after.get('libtype') == 'track', str(after))
        check(f'[{name}] sort inherited', after and after.get('sort') == ['titleSort'], str(after))
        check(f'[{name}] limit inherited', after and after.get('limit') == 102, str(after))


def test_unreadable_filters_are_still_editable():
    """plexapi cannot parse every filter Plex writes; that must not block an edit."""
    nested = (PATH + '?type=10&push=1&userRating%3E%3E=8&or=1&push=1&genre=Rock'
              '&and=1&year%3E%3E=1960&pop=1&sort=titleSort&pop=1')
    try:
        FakeSmartPlaylist(nested)._parseFilters(nested)
        plexapi_reads_it = True
    except Exception:
        plexapi_reads_it = False
    check('the fixture really does defeat plexapi', not plexapi_reads_it,
          'plexapi parsed it, so this no longer tests what it claims to')

    playlist = FakeSmartPlaylist(nested)
    before = _criteria_segments(nested)
    _, _, error = update_smart_filter(playlist, sort='track.random')
    check('a filter plexapi cannot parse is still editable', error is None, str(error))
    check('  criteria unchanged', _criteria_segments(playlist.content) == before,
          f'{before} -> {_criteria_segments(playlist.content)}')


def test_a_bad_rebuild_is_refused_before_writing():
    """The last line of defence is not writing at all.

    Rolling a bad write back is a recovery; refusing to make it is a prevention.
    This forces the rebuild to drop a criterion and asserts nothing reaches the
    server - exercised directly, because the post-write check would otherwise
    mask it.
    """
    import modules.smart_filter as smart_filter

    playlist = FakeSmartPlaylist(PATH + '?' + QUERY)
    original = smart_filter._replace_query_params
    smart_filter._replace_query_params = lambda raw, updates: PATH + '?type=10&sort=track.random'
    try:
        _, after, error = update_smart_filter(playlist, sort='track.random')
    finally:
        smart_filter._replace_query_params = original

    check('a rebuild that loses criteria is refused', bool(error) and 'altered' in error, str(error))
    check('  before writing anything', playlist._server.puts == [], str(playlist._server.puts))
    check('  and reported as an error', after is None, str(after))


def test_a_filter_plex_ignores_is_caught_by_the_count():
    """The criteria can read correctly while Plex has thrown them away.

    A having clause written with unescaped parentheses is stored verbatim and
    then ignored, so before and after compare equal as text. The item count is
    the only thing that changes, which is why it is checked.
    """
    playlist = FakeSmartPlaylist(PATH + '?' + QUERY, server_factory=SilentlyIgnoringServer)
    before_criteria = _criteria_segments(playlist.content)

    _, after, error = update_smart_filter(playlist, sort='track.random')

    check('a silently ignored filter is detected', bool(error) and 'items instead of' in error, str(error))
    check('  the criteria alone would NOT have caught it',
          _criteria_segments(playlist.content) == before_criteria,
          'the fixture no longer models the bug: the criteria changed too')
    check('  reported as an error, not success', after is None, str(after))
    check('  the item count is back', playlist.leafCount == CURATED, str(playlist.leafCount))


def test_empty_groups_are_not_reported_as_criteria():
    playlist = FakeSmartPlaylist(PATH + '?type=10&push=1&and=1&pop=1&genre=Rock')
    described = describe_smart_filter(playlist)
    check('empty groups are pruned from the parsed filter',
          described['smartFilter'].get('filters') == {'genre': 'Rock'},
          str(described['smartFilter']))
    check('  and the pruning is disclosed', 'smartFilterNote' in described)
    check('  while the raw string is untouched',
          'push=1&and=1&pop=1' in described['smartFilterRaw'], described['smartFilterRaw'])


def main():
    for test in (
        test_sort_only_preserves_criteria,
        test_a_wiping_write_is_caught_and_undone,
        test_clearing_filters_is_refused_unless_asked_for,
        test_replacing_filters_keeps_the_other_parameters,
        test_unreadable_filters_are_still_editable,
        test_a_bad_rebuild_is_refused_before_writing,
        test_a_filter_plex_ignores_is_caught_by_the_count,
        test_empty_groups_are_not_reported_as_criteria,
    ):
        print(f'\n--- {test.__name__}')
        test()

    print()
    if FAILURES:
        print(f'{len(FAILURES)} failure(s): ' + ', '.join(FAILURES))
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
