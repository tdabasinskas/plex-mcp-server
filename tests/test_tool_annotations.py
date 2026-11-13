import unittest

import plex_mcp_server  # noqa: F401  registers every tool module
from modules import mcp

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


class ToolAnnotationTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_tool_sets_all_four_hints(self):
        tools = await mcp.list_tools()
        self.assertTrue(tools)
        missing = {}
        for tool in tools:
            annotations = tool.annotations
            unset = [h for h in HINTS if annotations is None or getattr(annotations, h) is None]
            if unset:
                missing[tool.name] = unset
        self.assertEqual(missing, {}, "tools without explicit annotation hints")

    async def test_read_only_tools_are_not_destructive(self):
        for tool in await mcp.list_tools():
            if tool.annotations and tool.annotations.readOnlyHint:
                self.assertFalse(tool.annotations.destructiveHint, tool.name)


if __name__ == "__main__":
    unittest.main()
