import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from hyprland_mcp import clipboard
from hyprland_mcp.errors import ClipboardError


class ClipboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_binary_clipboard_is_rejected_without_exposing_content(self):
        process = AsyncMock(returncode=0)
        process.communicate.return_value = (b"\xffsecret", b"")
        with patch.object(clipboard, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ):
            with self.assertRaises(ClipboardError) as error:
                await clipboard.read()
        self.assertNotIn("secret", str(error.exception))

    async def test_clipboard_error_does_not_expose_stderr(self):
        process = AsyncMock(returncode=1)
        process.communicate.return_value = (b"", b"secret clipboard data")
        with patch.object(clipboard, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ):
            with self.assertRaises(ClipboardError) as error:
                await clipboard.read()
        self.assertNotIn("secret clipboard data", str(error.exception))


if __name__ == "__main__":
    unittest.main()
