import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import anyio
from mcp import ClientSession

from hyprland_mcp.server import LAUNCH_UNAVAILABLE, LaunchUnavailableError, launch_app, mcp


class LaunchAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_is_disabled_even_for_allowlisted_commands(self):
        commands = [
            ["/usr/bin/example", "normal"],
            ["/bin/sh", "-c", "echo private-marker"],
            ["/usr/bin/example", "$(touch private-marker)"],
            "firefox --new-window",
        ]
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "hyprland-mcp" / "launch-allowlist.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"allowed_argv": commands[:3]}))
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": temp}), patch(
                "pathlib.Path.open", side_effect=AssertionError("config was read")
            ) as open_config, patch(
                "asyncio.create_subprocess_exec", new_callable=AsyncMock
            ) as spawn:
                for command in commands:
                    with self.subTest(command=command):
                        with self.assertRaisesRegex(LaunchUnavailableError, LAUNCH_UNAVAILABLE):
                            await launch_app(command)
                        with self.assertRaisesRegex(Exception, LAUNCH_UNAVAILABLE) as error:
                            await mcp.call_tool("launch_app", {"command": command})
                        self.assertNotIn("private-marker", str(error.exception))
                open_config.assert_not_called()
                spawn.assert_not_awaited()

    async def test_mcp_protocol_rejects_without_config_or_process_access(self):
        client_write, server_read = anyio.create_memory_object_stream(0)
        server_write, client_read = anyio.create_memory_object_stream(0)
        low_level = mcp._mcp_server
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(low_level.run, server_read, server_write, low_level.create_initialization_options())
            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                with patch("pathlib.Path.open", side_effect=AssertionError("config was read")) as open_config, patch(
                    "asyncio.create_subprocess_exec", new_callable=AsyncMock
                ) as spawn:
                    for command in (["/usr/bin/example"], ["/bin/sh", "-c", "private-marker"]):
                        with self.subTest(command=command):
                            result = await session.call_tool("launch_app", {"command": command})
                            self.assertTrue(result.isError)
                            self.assertIn(LAUNCH_UNAVAILABLE, str(result))
                            self.assertNotIn("private-marker", str(result))
                    open_config.assert_not_called()
                    spawn.assert_not_awaited()
            tasks.cancel_scope.cancel()
