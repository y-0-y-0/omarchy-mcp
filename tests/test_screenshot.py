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


def monitor(name, x, y, width, height, scale=1, transform=0):
    return dict(name=name, x=x, y=y, width=width, height=height,
                scale=scale, transform=transform)


class ScreenshotTests(unittest.IsolatedAsyncioTestCase):
    async def capture(self, monitors, *, result=None, clients=None, **kwargs):
        async def query(command):
            return monitors if command == "monitors" else clients

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
        monitors = [monitor("a", -4, 0, 4, 4), monitor("b", 0, 0, 8, 8, 2)]
        (_, x, y), _ = await self.capture(monitors, result=png(4, 2), region="-2,1 4x2")
        self.assertEqual((x, y), (-2, 1))
        clients = [dict(**{"address": "0x1", "class": "Term", "title": "Hello", "at": [-3, 1], "size": [2, 2]})]
        (_, x, y), command = await self.capture(monitors, result=png(2, 2), clients=clients, window="title:ell")
        self.assertEqual((x, y), (-3, 1))
        self.assertIn("-3,1 2x2", command)

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
        first = [{"address": "0x1", "class": "Term", "title": "Terminal", "at": [0, 0], "size": [2, 2]}]
        moved = [{**first[0], "at": [1, 0]}]
        proc = AsyncMock(returncode=0)
        proc.communicate.return_value = (png(2, 2), b"")
        with patch.object(screenshot, "require_tool"), patch.object(
            screenshot.hyprctl, "query", new=AsyncMock(side_effect=[monitors, first, monitors, moved])
        ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)):
            with self.assertRaisesRegex(ScreenshotError, "changed"):
                await screenshot.capture_raw(window="class:term")

    async def test_window_replacement_at_same_position_is_rejected(self):
        monitors = [monitor("a", 0, 0, 4, 4)]
        first = [{"address": "0x1", "class": "Term", "title": "Terminal", "at": [0, 0], "size": [2, 2]}]
        replaced = [{**first[0], "address": "0x2"}]
        proc = AsyncMock(returncode=0)
        proc.communicate.return_value = (png(2, 2), b"")
        with patch.object(screenshot, "require_tool"), patch.object(
            screenshot.hyprctl, "query", new=AsyncMock(side_effect=[monitors, first, monitors, replaced])
        ), patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)):
            with self.assertRaisesRegex(ScreenshotError, "changed"):
                await screenshot.capture_raw(window="class:term")

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
