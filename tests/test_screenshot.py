"""Simulated grim/Hyprland captures; these are not real compositor tests."""

import asyncio
import io
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image as PILImage

from hyprland_mcp import screenshot
from hyprland_mcp.errors import ScreenshotError


def png(width, height):
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), "white").save(buf, "PNG")
    return buf.getvalue()


def monitor(name, x, y, width, height, scale=1, transform=0, *, id=0, workspace=1):
    return dict(name=name, x=x, y=y, width=width, height=height,
                scale=scale, transform=transform, id=id,
                activeWorkspace={"id": workspace, "name": str(workspace)},
                specialWorkspace={"id": 0, "name": ""})


class ScreenshotTests(unittest.IsolatedAsyncioTestCase):
    async def capture(self, monitors, *, result=None, clients=None, **kwargs):
        async def query(command):
            return {"monitors": monitors, "clients": clients, "workspaces": [
                {"id": m["activeWorkspace"].get("id"), "name": m["activeWorkspace"]["name"],
                 "monitor": m["name"], "monitorID": m["id"]}
                for m in monitors
            ]}[command]

        process = AsyncMock(returncode=0)
        process.communicate.return_value = (result or png(1, 1), b"")
        with patch.object(screenshot, "require_tool"), patch.object(
            screenshot.hyprctl, "query", new=AsyncMock(side_effect=query)
        ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)) as spawn:
            captured = await screenshot.capture_raw(**kwargs)
        return captured, spawn.call_args.args

    async def test_desktop_negative_origin_and_mixed_scale(self):
        monitors = [monitor("left", -4, -2, 8, 8, 2), monitor("right", 0, -2, 5, 5, 1.25)]
        (data, x, y), command = await self.capture(monitors, result=png(8, 4))
        self.assertEqual((x, y), (-4, -2))
        self.assertEqual(PILImage.open(io.BytesIO(data)).size, (8, 4))
        self.assertEqual(command[command.index("-s") + 1], "1")
        self.assertEqual(command[command.index("-g") + 1], "-4,-2 8x4")

    async def test_rotated_monitor_and_cursor(self):
        monitors = [monitor("rotated", -3, 1, 4, 6, 2, 1)]
        (_, x, y), command = await self.capture(monitors, result=png(3, 2), monitor="rotated", include_cursor=True)
        self.assertEqual((x, y), (-3, 1))
        self.assertIn("-c", command)
        self.assertIn("-3,1 3x2", command)

    async def test_region_spanning_monitors_and_window(self):
        monitors = [monitor("a", -4, 0, 4, 4), monitor("b", 0, 0, 8, 8, 2, id=1, workspace=2)]
        (_, x, y), _ = await self.capture(monitors, result=png(4, 2), region="-2,1 4x2")
        self.assertEqual((x, y), (-2, 1))
        clients = [dict(**{"address": "0x1", "class": "Term", "title": "Hello", "at": [-3, 1], "size": [2, 2],
                           "monitor": 0, "workspace": {"id": 1, "name": "1"},
                           "mapped": True, "hidden": False, "visible": True, "pinned": False})]
        (_, x, y), command = await self.capture(monitors, result=png(2, 2), clients=clients, window="title:ell")
        self.assertEqual((x, y), (-3, 1))
        self.assertIn("-3,1 2x2", command)

    async def test_reject_empty_window_selectors_before_grim(self):
        monitors = [monitor("a", 0, 0, 2, 2)]
        clients = [{"address": "0x1", "class": " ", "title": "Hello world",
                    "at": [0, 0], "size": [2, 2]}]

        async def query(command):
            return monitors if command == "monitors" else clients

        for window in ("", " ", "\t\n", "class:", "class: ", "class:\t\n",
                       "title:", "title: ", "title:\t\n"):
            with self.subTest(window=window), patch.object(screenshot, "require_tool"), patch.object(
                screenshot.hyprctl, "query", new=AsyncMock(side_effect=query)
            ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock()) as spawn:
                with self.assertRaises(ScreenshotError):
                    await screenshot.capture_raw(window=window)
                spawn.assert_not_called()

    async def test_reject_invalid_scopes_and_geometry(self):
        monitors = [monitor("a", -4, 0, 4, 4)]
        for kwargs in [dict(monitor="missing"), dict(monitor="a", region="0,0 1x1"),
                       dict(region="not geometry"), dict(region="0,0 0x1"),
                       dict(region="-4,0 5x4"), dict(region="2147483647,0 1x1")]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ScreenshotError):
                await self.capture(monitors, **kwargs)

    async def test_reject_gap_overlap_and_ambiguous_scaling(self):
        for monitors in [
            [monitor("a", 0, 0, 2, 2), monitor("b", 3, 0, 2, 2)],
            [monitor("a", 0, 0, 2, 2), monitor("b", 1, 0, 2, 2)],
            [monitor("a", 0, 0, 3, 3, 2)], [],
        ]:
            with self.subTest(monitors=monitors), self.assertRaises(ScreenshotError):
                await self.capture(monitors)

    async def test_reject_bad_image_warning_and_redact_failure(self):
        monitors = [monitor("a", 0, 0, 2, 2)]
        with self.assertRaises(ScreenshotError):
            await self.capture(monitors, result=png(1, 1))
        for code, stderr in [(1, b"secret stderr"), (0, b"secret warning")]:
            proc = AsyncMock(returncode=code)
            proc.communicate.return_value = (png(2, 2), stderr)
            with patch.object(screenshot, "require_tool"), patch.object(
                screenshot.hyprctl, "query", new=AsyncMock(return_value=monitors)
            ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)):
                with self.assertRaises(ScreenshotError) as error:
                    await screenshot.capture_raw()
            self.assertNotIn("secret", str(error.exception))

    async def test_layout_change_is_rejected(self):
        before = [monitor("a", 0, 0, 2, 2)]
        after = [monitor("a", -1, 0, 2, 2)]
        proc = AsyncMock(returncode=0)
        proc.communicate.return_value = (png(2, 2), b"")
        with patch.object(screenshot, "require_tool"), patch.object(
            screenshot.hyprctl, "query", new=AsyncMock(side_effect=[before, after])
        ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)):
            with self.assertRaisesRegex(ScreenshotError, "changed"):
                await screenshot.capture_raw()

    async def test_mode_change_with_same_logical_rectangle_is_rejected(self):
        before = [monitor("a", 0, 0, 4, 2)]
        for after in ([monitor("a", 0, 0, 2, 4, 1, 1)],
                      [monitor("a", 0, 0, 8, 4, 2)]):
            proc = AsyncMock(returncode=0)
            proc.communicate.return_value = (png(4, 2), b"")
            with self.subTest(after=after), patch.object(screenshot, "require_tool"), patch.object(
                screenshot.hyprctl, "query", new=AsyncMock(side_effect=[before, after])
            ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)):
                with self.assertRaisesRegex(ScreenshotError, "changed"):
                    await screenshot.capture_raw()

    async def test_window_movement_is_rejected(self):
        monitors = [monitor("a", 0, 0, 4, 4)]
        first = [{"address": "0x1", "class": "Term", "title": "Terminal", "at": [0, 0], "size": [2, 2],
                  "monitor": 0, "workspace": {"id": 1, "name": "1"},
                  "mapped": True, "hidden": False, "visible": True, "pinned": False}]
        moved = [{**first[0], "at": [1, 0]}]
        capture_finished = False

        async def query(command):
            return {"monitors": monitors, "clients": moved if capture_finished else first,
                    "workspaces": [{"id": 1, "name": "1", "monitor": "a", "monitorID": 0}]}[command]

        async def communicate():
            nonlocal capture_finished
            capture_finished = True
            return png(2, 2), b""

        proc = AsyncMock(returncode=0)
        proc.communicate.side_effect = communicate
        with patch.object(screenshot, "require_tool"), patch.object(
            screenshot.hyprctl, "query", new=AsyncMock(side_effect=query)
        ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)):
            with self.assertRaisesRegex(ScreenshotError, "changed"):
                await screenshot.capture_raw(window="class:term")

    async def test_window_replacement_at_same_position_is_rejected(self):
        monitors = [monitor("a", 0, 0, 4, 4)]
        first = [{"address": "0x1", "class": "Term", "title": "Terminal", "at": [0, 0], "size": [2, 2],
                  "monitor": 0, "workspace": {"id": 1, "name": "1"},
                  "mapped": True, "hidden": False, "visible": True, "pinned": False}]
        replaced = [{**first[0], "address": "0x2"}]
        capture_finished = False

        async def query(command):
            return {"monitors": monitors, "clients": replaced if capture_finished else first,
                    "workspaces": [{"id": 1, "name": "1", "monitor": "a", "monitorID": 0}]}[command]

        async def communicate():
            nonlocal capture_finished
            capture_finished = True
            return png(2, 2), b""

        proc = AsyncMock(returncode=0)
        proc.communicate.side_effect = communicate
        with patch.object(screenshot, "require_tool"), patch.object(
            screenshot.hyprctl, "query", new=AsyncMock(side_effect=query)
        ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)):
            with self.assertRaisesRegex(ScreenshotError, "changed"):
                await screenshot.capture_raw(window="class:term")

    async def test_window_on_inactive_workspace_is_rejected_before_grim(self):
        monitors = [monitor("a", 0, 0, 4, 4)]
        target = {"address": "0x1", "class": "Term", "title": "Terminal", "at": [0, 0], "size": [2, 2],
                  "monitor": 0, "workspace": {"id": 2, "name": "2"},
                  "mapped": True, "hidden": False, "visible": True, "pinned": False}
        visible = {**target, "address": "0x2", "class": "Browser", "title": "Browser",
                   "workspace": {"id": 1, "name": "1"}}
        workspaces = [{"id": 1, "name": "1", "monitor": "a", "monitorID": 0},
                      {"id": 2, "name": "2", "monitor": "a", "monitorID": 0}]

        async def query(command):
            return {"monitors": monitors, "clients": [target, visible], "workspaces": workspaces}[command]

        proc = AsyncMock(returncode=0)
        proc.communicate.return_value = (png(2, 2), b"")
        with patch.object(screenshot, "require_tool"), patch.object(
            screenshot.hyprctl, "query", new=AsyncMock(side_effect=query)
        ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)) as spawn:
            with self.assertRaises(ScreenshotError):
                await screenshot.capture_raw(window="class:term")
            spawn.assert_not_called()

    async def test_workspace_hidden_during_capture_rejects_image(self):
        before = [monitor("a", 0, 0, 4, 4)]
        after = [monitor("a", 0, 0, 4, 4, workspace=2)]
        target = {"address": "0x1", "class": "Term", "title": "Terminal", "at": [0, 0], "size": [2, 2],
                  "monitor": 0, "workspace": {"id": 1, "name": "1"},
                  "mapped": True, "hidden": False, "visible": True, "pinned": False}
        other = {**target, "address": "0x2", "class": "Browser", "title": "Browser",
                 "workspace": {"id": 2, "name": "2"}}
        workspaces = [{"id": 1, "name": "1", "monitor": "a", "monitorID": 0},
                      {"id": 2, "name": "2", "monitor": "a", "monitorID": 0}]
        capture_finished = False

        async def query(command):
            return {"monitors": after if capture_finished else before,
                    "clients": [target, other], "workspaces": workspaces}[command]

        async def communicate():
            nonlocal capture_finished
            capture_finished = True
            return png(2, 2), b""

        proc = AsyncMock(returncode=0)
        proc.communicate.side_effect = communicate
        with patch.object(screenshot, "require_tool"), patch.object(
            screenshot.hyprctl, "query", new=AsyncMock(side_effect=query)
        ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)) as spawn:
            with self.assertRaises(ScreenshotError):
                await screenshot.capture_raw(window="class:term")
            spawn.assert_awaited_once()
            proc.communicate.assert_awaited_once()

    async def test_057_named_and_special_workspace_visibility(self):
        named = {"address": "notes", "type": "normal", "name": "notes"}
        special = {"address": "special:notes", "type": "special", "name": "special:notes"}
        for workspace, active_field in ((named, "activeWorkspace"), (special, "specialWorkspace")):
            with self.subTest(workspace=workspace):
                display = monitor("a", 0, 0, 4, 4)
                display["activeWorkspace"] = {"address": "1", "type": "normal", "name": "1", "id": 1}
                display["specialWorkspace"] = {"address": "", "type": "", "name": ""}
                display[active_field] = dict(workspace)
                client = {"address": "0x1", "class": "Term", "title": "Terminal",
                          "at": [0, 0], "size": [2, 2], "monitor": 0,
                          "workspace": dict(workspace), "mapped": True,
                          "hidden": False, "visible": True, "pinned": False}
                capture, _ = await self.capture([display], clients=[client],
                                                 result=png(2, 2), window="class:term")
                self.assertEqual(capture[1:], (0, 0))
                display[active_field] = {**workspace, "address": workspace["address"] + "-other"}
                with self.assertRaises(ScreenshotError):
                    await self.capture([display], clients=[client], window="class:term")

    async def test_window_missing_visibility_information_is_rejected(self):
        display = monitor("a", 0, 0, 4, 4)
        client = {"address": "0x1", "class": "Term", "title": "Terminal",
                  "at": [0, 0], "size": [2, 2], "monitor": 0,
                  "workspace": {"id": 1, "name": "1"},
                  "mapped": True, "hidden": False, "visible": True, "pinned": False}
        for field in ("monitor", "workspace", "mapped", "hidden", "visible", "pinned"):
            with self.subTest(field=field):
                incomplete = {key: value for key, value in client.items() if key != field}
                with self.assertRaises(ScreenshotError):
                    await self.capture([display], clients=[incomplete], window="class:term")

    async def test_special_workspace_and_conservative_window_rejections(self):
        display = monitor("a", 0, 0, 4, 4)
        display["specialWorkspace"] = {"id": -2, "name": "special:notes"}
        client = {"address": "0x1", "class": "Term", "title": "Terminal",
                  "at": [0, 0], "size": [2, 2], "monitor": 0,
                  "workspace": {"id": -2, "name": "special:notes"},
                  "mapped": True, "hidden": False, "visible": True, "pinned": False}
        captured, _ = await self.capture([display], clients=[client],
                                          result=png(2, 2), window="class:term")
        self.assertEqual(captured[1:], (0, 0))
        for changed in ({"pinned": True}, {"mapped": False}, {"hidden": True},
                        {"at": [3, 0]}, {"workspace": {"id": -3, "name": "special:other"}}):
            with self.subTest(changed=changed), self.assertRaises(ScreenshotError):
                await self.capture([display], clients=[{**client, **changed}], window="class:term")
        second = {**client, "address": "0x2", "workspace": {"id": 1, "name": "1"}}
        with self.assertRaises(ScreenshotError):
            await self.capture([display], clients=[{**client, "hidden": True}, second], window="class:term")

    async def test_reject_covered_invisible_and_ambiguous_windows(self):
        display = monitor("a", 0, 0, 4, 4)
        client = {"address": "0x1", "class": "Term", "title": "Terminal",
                  "at": [0, 0], "size": [2, 2], "monitor": 0,
                  "workspace": {"id": 1, "name": "1"}, "mapped": True,
                  "hidden": False, "visible": True, "pinned": False}
        covered = {**display, "specialWorkspace": {"id": -2, "name": "special:notes"}}
        workspace_057 = {"address": "1", "id": 1, "type": "normal", "name": "1"}
        covered_057 = {**display, "activeWorkspace": workspace_057,
                       "specialWorkspace": {"address": "special:notes", "type": "special",
                                            "name": "special:notes"}}
        cases = [([covered], [client]), ([covered_057], [{**client, "workspace": workspace_057}]),
                 ([display], [{**client, "visible": False}]),
                 ([display], [client, {**client, "address": "0x2"}]),
                 ([display], [{**client, "address": "0x2"}, client])]
        for monitors, clients in cases:
            async def query(command):
                return {"monitors": monitors, "clients": clients}[command]
            with self.subTest(monitors=monitors, clients=clients), patch.object(
                screenshot, "require_tool"
            ), patch.object(screenshot.hyprctl, "query", new=AsyncMock(side_effect=query)), patch.object(
                asyncio, "create_subprocess_exec", new=AsyncMock()
            ) as spawn:
                with self.assertRaises(ScreenshotError):
                    await screenshot.capture_raw(window="class:term")
                spawn.assert_not_awaited()

    async def test_resize_mapping_uses_actual_rounded_height(self):
        with patch.object(screenshot, "capture_raw", new=AsyncMock(return_value=(png(7, 5), -8, -3))):
            image, mapping = await screenshot.take_screenshot(max_width=4)
        self.assertEqual(PILImage.open(io.BytesIO(image.data)).size, (4, 2))
        self.assertIn("screen_x = image_x * 7/4 + -8", mapping)
        self.assertIn("screen_y = image_y * 5/2 + -3", mapping)

    async def test_ocr_reports_raw_logical_origin(self):
        from hyprland_mcp import server, ocr

        monitors = [monitor("a", -4, -2, 8, 8, 2)]
        proc = AsyncMock(returncode=0)
        proc.communicate.return_value = (png(4, 4), b"")
        match = dict(text="go", x=1, y=1, w=2, h=2, conf=99)
        with patch.object(screenshot, "require_tool"), patch.object(
            screenshot.hyprctl, "query", new=AsyncMock(return_value=monitors)
        ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)), patch.object(
            ocr, "extract_boxes", return_value=[match]
        ):
            result = await server.find_text_on_screen("go", scope="full")
        self.assertIn("at screen (-2, 0)", result)

    def test_resize_validation(self):
        for kwargs in [dict(max_width=0), dict(max_width=True), dict(quality=0), dict(quality=101)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ScreenshotError):
                screenshot.resize_and_compress(png(2, 2), **kwargs)


if __name__ == "__main__":
    unittest.main()
