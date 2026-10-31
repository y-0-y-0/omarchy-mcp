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
        locale_process = AsyncMock(returncode=0)
        locale_process.communicate.return_value = (b"UTF-8\n", b"")
        process = AsyncMock(returncode=1)
        process.communicate.return_value = (b"", b"sensitive input")
        with patch.object(desktop_input, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(side_effect=[locale_process, process])
        ):
            with self.assertRaises(InputError) as error:
                await desktop_input.type_text("sensitive input")
        self.assertNotIn("sensitive input", str(error.exception))

    async def test_typing_passes_text_through_stdin(self):
        locale_process = AsyncMock(returncode=0)
        locale_process.communicate.return_value = (b"UTF-8\n", b"")
        process = AsyncMock(returncode=0)
        process.communicate.return_value = (b"", b"")
        with patch.object(desktop_input, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(side_effect=[locale_process, process])
        ) as spawn, patch.dict("os.environ", {"LC_ALL": "C"}):
            await desktop_input.type_text("-été\nsecret", delay_ms=7)
        self.assertEqual(spawn.call_args.args, ("wtype", "-d", "7", "-"))
        self.assertEqual(spawn.call_args.kwargs["stdin"], asyncio.subprocess.PIPE)
        self.assertEqual(spawn.call_args.kwargs["env"]["LC_ALL"], "C.UTF-8")
        self.assertEqual(spawn.call_args_list[0].kwargs["env"]["LC_ALL"], "C.UTF-8")
        process.communicate.assert_awaited_once_with(input="-été\nsecret".encode())

    async def test_typing_invalid_unicode_or_unavailable_locale_never_starts_wtype(self):
        with patch.object(asyncio, "create_subprocess_exec", new=AsyncMock()) as spawn:
            with self.assertRaises(InputError):
                await desktop_input.type_text("secret\ud800")
            spawn.assert_not_awaited()
        locale_process = AsyncMock(returncode=0)
        locale_process.communicate.return_value = (b"ANSI_X3.4-1968\n", b"")
        with patch.object(desktop_input, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(return_value=locale_process)
        ) as spawn:
            with self.assertRaises(InputError):
                await desktop_input.type_text("été")
        self.assertEqual(spawn.await_count, 1)
        self.assertEqual(spawn.call_args.args, ("locale", "charmap"))


if __name__ == "__main__":
    unittest.main()
