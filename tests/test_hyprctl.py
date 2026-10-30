import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from hyprland_mcp import hyprctl
from hyprland_mcp.errors import HyprctlError


class HyprctlTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_uses_documented_json_flag_order(self):
        process = AsyncMock(returncode=0)
        process.communicate.return_value = (b'[{"name":"test"}]', b'')
        with patch.object(hyprctl, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ) as spawn:
            result = await hyprctl.query("monitors")

        self.assertEqual(result, [{"name": "test"}])
        self.assertEqual(spawn.call_args.args, ("hyprctl", "-j", "monitors"))

    async def test_dispatch_reports_error_even_when_process_exits_zero(self):
        process = AsyncMock(returncode=0)
        process.communicate.return_value = (b'unknown dispatcher', b'')
        with patch.object(hyprctl, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ):
            with self.assertRaises(HyprctlError):
                await hyprctl.dispatch("workspace", "1")

    async def test_query_rejects_unexpected_json_type(self):
        process = AsyncMock(returncode=0)
        process.communicate.return_value = (b'null', b'')
        with patch.object(hyprctl, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ):
            with self.assertRaises(HyprctlError):
                await hyprctl.query("monitors")

    async def test_query_failure_does_not_expose_stderr(self):
        process = AsyncMock(returncode=1)
        process.communicate.return_value = (b'', b'private screen data')
        with patch.object(hyprctl, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ):
            with self.assertRaises(HyprctlError) as error:
                await hyprctl.query("activewindow")
        self.assertNotIn("private screen data", str(error.exception))


if __name__ == "__main__":
    unittest.main()
