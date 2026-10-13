import json
import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

from modules import mcp, media


def ep(season, number, watched=False, aired=date(2020, 1, 1), key=None):
    return Mock(parentIndex=season, index=number, viewCount=1 if watched else 0,
                originallyAvailableAt=aired, ratingKey=key or season * 100 + number,
                title=f"S{season:02}E{number:02}", grandparentTitle="Show", duration=1)


class EpisodeTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, name, args, episodes):
        show = Mock(type="show", ratingKey=7, title="Show")
        show.episodes.return_value = episodes
        server = Mock()
        server.fetchItem.return_value = show
        with patch.object(media, "connect_to_plex"), \
                patch.object(media, "server_for_user", return_value=server) as for_user:
            content, _ = await mcp.call_tool(name, args)
            self.for_user = for_user
        return json.loads(content[0].text)

    async def next_of(self, episodes, **args):
        result = await self.call("media_get_next_unwatched_episode", {"media_id": 7, **args}, episodes)
        episode = result["episode"]
        return (episode["season"], episode["episode"]) if episode else None

    async def test_resumes_after_the_furthest_watched_episode(self):
        episodes = [ep(1, 1, True), ep(1, 2, True), ep(2, 3), ep(5, 10, True), ep(5, 11), ep(5, 12)]
        self.assertEqual(await self.next_of(episodes), (5, 11))

    async def test_skips_an_unwatched_special_by_default(self):
        episodes = [ep(0, 1, aired=date(2019, 1, 1)), ep(1, 1, True), ep(1, 2)]
        self.assertEqual(await self.next_of(episodes), (1, 2))
        self.assertEqual(await self.next_of(episodes, ignore_specials=False), (1, 2))
        fresh = [ep(0, 1), ep(1, 1), ep(1, 2)]
        self.assertEqual(await self.next_of(fresh), (1, 1))
        self.assertEqual(await self.next_of(fresh, ignore_specials=False), (0, 1))

    async def test_nothing_watched_gives_the_premiere(self):
        self.assertEqual(await self.next_of([ep(1, 2), ep(1, 1)]), (1, 1))

    async def test_caught_up_and_unaired(self):
        future = date.today() + timedelta(days=7)
        result = await self.call("media_get_next_unwatched_episode", {"media_id": 7},
                                 [ep(1, 1, True), ep(1, 2, aired=future), ep(1, 3, aired=None)])
        self.assertIsNone(result["episode"])
        self.assertIn("message", result)

    async def test_series_order_beats_air_date(self):
        # Aired out of order (the Firefly case): series order decides "next".
        episodes = [ep(1, 1, True, aired=date(2002, 9, 20)), ep(1, 2, aired=date(2002, 12, 20)),
                    ep(1, 3, aired=date(2002, 9, 27))]
        self.assertEqual(await self.next_of(episodes), (1, 2))

    async def test_username_selects_whose_watch_state(self):
        await self.call("media_get_next_unwatched_episode", {"media_id": 7, "username": "Son"}, [ep(1, 1)])
        self.assertEqual(self.for_user.call_args.kwargs, {"username": "Son"})

    async def test_episode_pages(self):
        episodes = [ep(1, n, aired=date(2020, 1, n)) for n in range(1, 6)]
        page = await self.call("media_get_episodes", {"media_id": 7, "limit": 2, "offset": 2}, episodes)
        self.assertEqual([e["episode"] for e in page["episodes"]], [3, 4])
        self.assertEqual((page["total"], page["offset"], page["count"], page["hasMore"]), (5, 2, 2, True))
        last = await self.call("media_get_episodes", {"media_id": 7, "offset": 4}, episodes)
        self.assertEqual((last["count"], last["hasMore"]), (1, False))

    async def test_air_date_order_keeps_ties_in_series_order_and_undated_last(self):
        same = date(2020, 1, 1)
        episodes = [ep(1, 2, aired=same), ep(1, 1, aired=same), ep(1, 3, aired=None), ep(1, 4, aired=date(2021, 1, 1))]
        asc = await self.call("media_get_episodes", {"media_id": 7}, episodes)
        self.assertEqual([e["episode"] for e in asc["episodes"]], [1, 2, 4, 3])
        desc = await self.call("media_get_episodes", {"media_id": 7, "sort_order": "desc"}, episodes)
        self.assertEqual([e["episode"] for e in desc["episodes"]], [4, 2, 1, 3])

    async def test_rejects_bad_arguments_and_non_shows(self):
        for args in ({"sort": "x"}, {"sort_order": "x"}, {"limit": 0}, {"offset": -1}):
            result = await self.call("media_get_episodes", {"media_id": 7, **args}, [])
            self.assertEqual(result["status"], "error")
        server = Mock()
        server.fetchItem.return_value = Mock(type="movie")
        with patch.object(media, "connect_to_plex"), patch.object(media, "server_for_user", return_value=server):
            content, _ = await mcp.call_tool("media_get_next_unwatched_episode", {"media_id": 7})
        self.assertIn("not a TV show", json.loads(content[0].text)["message"])
