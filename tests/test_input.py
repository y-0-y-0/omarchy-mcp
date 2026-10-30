import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from hyprland_mcp import input as desktop_input
from hyprland_mcp.errors import InputError


class InputTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_scroll_direction_is_rejected(self):
        process = AsyncMock(returncode=0)
        process.communicate.return_value = (b"", b"")
        with patch.object(desktop_input, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ) as spawn:
            with self.assertRaises(InputError):
                await desktop_input.scroll("sideways", 3)
        spawn.assert_not_awaited()

    async def test_drag_releases_button_when_movement_fails(self):
        process = AsyncMock(returncode=0)
        process.communicate.return_value = (b"", b"")
        move = AsyncMock(side_effect=[None, InputError("move failed")])
        with patch.object(desktop_input, "require_tool"), patch.object(
            desktop_input, "move_cursor", move
        ), patch.object(asyncio, "sleep", new=AsyncMock()), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ) as spawn:
            with self.assertRaises(InputError):
                await desktop_input.drag(1, 2, 3, 4)
        self.assertEqual(spawn.call_args_list[-1].args, ("ydotool", "click", "0x80"))

    async def test_typing_error_does_not_expose_stderr(self):
        process = AsyncMock(returncode=1)
        process.communicate.return_value = (b"", b"sensitive input")
        with patch.object(desktop_input, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ):
            with self.assertRaises(InputError) as error:
                await desktop_input.type_text("sensitive input")
        self.assertNotIn("sensitive input", str(error.exception))


if __name__ == "__main__":
    unittest.main()
