import sys
import unittest
from unittest.mock import AsyncMock, patch

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from hyprland_mcp import server


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_workspaces_without_numeric_id_are_listed(self):
        workspaces = [
            {"name": "special:notes", "windows": 1, "monitor": "DP-1"},
            {"id": 2, "name": "2", "windows": 3, "monitor": "HDMI-A-1"},
        ]
        with patch.object(server.hyprctl, "query", new=AsyncMock(return_value=workspaces)):
            result = await server.list_workspaces()
        self.assertIn("Workspace 2 (id=2)", result)
        self.assertIn("Workspace special:notes: 1", result)

    async def test_window_monitor_name_is_resolved_to_numeric_id(self):
        clients = [
            {"class": "wanted", "title": "first", "size": [40, 50], "at": [1, 2],
             "monitor": 7, "workspace": {"name": "notes"}},
            {"class": "other", "title": "second", "size": [40, 50], "at": [3, 4],
             "monitor": 2, "workspace": {"id": 3, "name": "3"}},
        ]
        monitors = [{"name": "DP-1", "id": 7}, {"name": "HDMI-A-1", "id": 2}]
        async def query(command):
            return {"clients": clients, "monitors": monitors}[command]
        with patch.object(server.hyprctl, "query", new=query):
            result = await server.list_windows(monitor="DP-1")
            filtered = await server.list_windows(workspace=3)
        self.assertIn("wanted", result)
        self.assertNotIn("other", result)
        self.assertIn("other", filtered)
        self.assertNotIn("wanted", filtered)

    async def test_invalid_click_and_scroll_have_no_effect(self):
        with patch("hyprland_mcp.input.click", new_callable=AsyncMock) as click, patch(
            "hyprland_mcp.input.scroll", new_callable=AsyncMock
        ) as scroll, patch("hyprland_mcp.input.move_cursor", new_callable=AsyncMock) as move:
            with self.assertRaises(ValueError):
                await server.mouse_click(x=10)
            with self.assertRaises(ValueError):
                await server.mouse_scroll(direction="invalid", x=1, y=2)
            click.assert_not_awaited()
            scroll.assert_not_awaited()
            move.assert_not_awaited()

    async def test_mcp_validation_errors_do_not_return_input(self):
        with self.assertRaises(Exception) as error:
            await server.mcp.call_tool("mouse_move", {"x": "private-marker-value", "y": 1})
        self.assertNotIn("private-marker-value", str(error.exception))

    async def test_stdio_initialization_and_sanitized_errors(self):
        params = StdioServerParameters(command=sys.executable, args=["-m", "hyprland_mcp.server"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                initialization = await session.initialize()
                tools = await session.list_tools()
                invalid = await session.call_tool("mouse_move", {"x": "private-marker-value", "y": 1})
                blocked = await session.call_tool("switch_workspace", {"workspace": "1"})
                click = await session.call_tool("click_text", {"target": "private-marker"})
                typing = await session.call_tool("type_into", {"text": "private-marker"})
                launch = await session.call_tool("launch_app", {"command": ["/bin/sh", "-c", "private-marker"]})
        self.assertEqual(len(tools.tools), 27)
        descriptions = {tool.name: tool.description for tool in tools.tools}
        for name in ("switch_workspace", "focus_window", "close_window", "move_window",
                     "resize_window", "toggle_fullscreen", "toggle_floating", "mouse_move",
                     "mouse_drag", "key_press", "send_shortcut", "click_text", "type_into"):
            with self.subTest(tool=name):
                self.assertIn("disabled", descriptions[name].lower())
                self.assertIn("dispatch", descriptions[name].lower())
        for name in ("mouse_click", "mouse_scroll"):
            with self.subTest(tool=name):
                self.assertIn("positioned", descriptions[name].lower())
                self.assertIn("disabled", descriptions[name].lower())
                self.assertIn("without coordinates", descriptions[name].lower())
        self.assertIn("disabled", descriptions["launch_app"].lower())
        self.assertIn("launching are currently disabled", initialization.instructions)
        self.assertIn("non-atomic", initialization.instructions)
        self.assertTrue(invalid.isError)
        self.assertNotIn("private-marker-value", str(invalid))
        self.assertTrue(blocked.isError)
        self.assertIn("safe Lua interface is not implemented", str(blocked))
        for result in (click, typing):
            self.assertTrue(result.isError)
            self.assertIn(server.DISPATCH_UNAVAILABLE, str(result))
            self.assertNotIn("private-marker", str(result))
        self.assertTrue(launch.isError)
        self.assertIn(server.LAUNCH_UNAVAILABLE, str(launch))
        self.assertNotIn("private-marker", str(launch))

    async def test_ocr_invalid_inputs_fail_before_capture(self):
        with patch("hyprland_mcp.screenshot.capture_raw", new_callable=AsyncMock) as capture:
            with self.assertRaises(ValueError):
                await server.click_text("test", occurrence=0)
            with self.assertRaises(ValueError):
                await server.find_text_on_screen("  ")
            capture.assert_not_awaited()

    async def test_ocr_empty_explicit_scopes_are_not_expanded(self):
        async def query(command):
            if command == "activewindow":
                return {}
            return [{"name": "DP-1", "x": 0, "y": 0, "width": 4, "height": 4, "scale": 1, "transform": 0}]

        with patch("hyprland_mcp.screenshot.require_tool"), patch.object(
            server.hyprctl, "query", new=AsyncMock(side_effect=query)
        ), patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, side_effect=AssertionError("unexpected capture")) as spawn:
            for tool in (server.find_text_on_screen, server.screenshot_with_ocr):
                for scope in ("auto", "full"):
                    for field in ("monitor", "window", "region"):
                        args = {field: "", "scope": scope}
                        if tool is server.find_text_on_screen:
                            args["target"] = "example"
                        with self.subTest(tool=tool.__name__, scope=scope, field=field):
                            with self.assertRaises(server.ScreenshotError):
                                await tool(**args)
            spawn.assert_not_awaited()

    async def test_disabled_smart_actions_do_not_capture_or_ocr(self):
        client_write, server_read = anyio.create_memory_object_stream(0)
        server_write, client_read = anyio.create_memory_object_stream(0)
        low_level = server.mcp._mcp_server
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(low_level.run, server_read, server_write, low_level.create_initialization_options())
            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                with patch("hyprland_mcp.screenshot.capture_raw", new_callable=AsyncMock) as capture, patch(
                    "hyprland_mcp.ocr.extract_boxes"
                ) as boxes, patch("hyprland_mcp.ocr.extract_text") as text, patch(
                    "hyprland_mcp.server.hyprctl.query", new_callable=AsyncMock
                ) as query:
                    cases = [
                        ("click_text", {"target": "missing"}),
                        ("click_text", {"target": "missing", "scope": "full"}),
                        ("click_text", {"target": "missing", "window": "class:demo"}),
                        ("type_into", {"text": "secret"}),
                        ("type_into", {"text": "secret", "window": "class:demo", "submit": True}),
                    ]
                    for name, arguments in cases:
                        with self.subTest(name=name, arguments=arguments):
                            result = await session.call_tool(name, arguments)
                            self.assertTrue(result.isError)
                            self.assertIn(server.DISPATCH_UNAVAILABLE, str(result))
                    capture.assert_not_awaited()
                    query.assert_not_awaited()
                    boxes.assert_not_called()
                    text.assert_not_called()
            tasks.cancel_scope.cancel()

    async def test_auto_scope_requires_stable_identity_and_geometry(self):
        active = {"address": "0x123", "at": [10, 20], "size": [100, 80]}
        captured = (b"private-image", 10, 20)
        changes = [
            {**active, "address": "0x456"},
            {**active, "at": [11, 20]},
            {**active, "size": [100, 81]},
            {},
            {"at": [10, 20], "size": [100, 80]},
        ]
        with patch("hyprland_mcp.screenshot.capture_raw", new_callable=AsyncMock, return_value=captured) as capture:
            with patch.object(server.hyprctl, "query", new=AsyncMock(side_effect=[active, dict(active)])):
                self.assertEqual(await server._auto_scope_capture(None, None, None), captured)
                capture.assert_awaited_once_with(region="10,20 100x80")
            for after in changes:
                with self.subTest(after=after), patch.object(
                    server.hyprctl, "query", new=AsyncMock(side_effect=[active, after])
                ), patch("hyprland_mcp.ocr.extract_boxes") as boxes:
                    with self.assertRaises(server.ScreenshotError):
                        await server.find_text_on_screen("anything")
                    boxes.assert_not_called()

    async def test_auto_scope_validates_before_capture_and_empty_fallback(self):
        invalid = [
            {"at": [1, 2], "size": [3, 4]},
            {"address": "0x0", "at": [1, 2], "size": [3, 4]},
            {"address": "0x1", "at": [1, 2], "size": [0, 4]},
        ]
        with patch("hyprland_mcp.screenshot.capture_raw", new_callable=AsyncMock, return_value=(b"png", 0, 0)) as capture:
            for active in invalid:
                with self.subTest(active=active), patch.object(
                    server.hyprctl, "query", new=AsyncMock(return_value=active)
                ):
                    with self.assertRaises(server.ScreenshotError):
                        await server._auto_scope_capture(None, None, None)
            capture.assert_not_awaited()
            with patch.object(server.hyprctl, "query", new=AsyncMock(side_effect=[{}, {}])):
                self.assertEqual(await server._auto_scope_capture(None, None, None), (b"png", 0, 0))
            with patch.object(server.hyprctl, "query", new=AsyncMock(side_effect=[{}, {
                "address": "0x1", "at": [0, 0], "size": [10, 10]
            }])):
                with self.assertRaises(server.ScreenshotError):
                    await server._auto_scope_capture(None, None, None)
