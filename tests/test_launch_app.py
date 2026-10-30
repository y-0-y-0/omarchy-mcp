import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from hyprland_mcp.server import launch_app, mcp


class LaunchAppTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"XDG_CONFIG_HOME": self.temp.name, "HOME": self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.config = Path(self.temp.name) / "hyprland-mcp" / "launch-allowlist.json"
        self.config.parent.mkdir()

    def allow(self, *commands):
        self.config.write_text(json.dumps({"allowed_argv": list(commands)}))

    async def test_allowed_argv_is_passed_literally_to_exec(self):
        argv = ["/usr/bin/example;literal", "https://example.test/?a=1&b=$(touch x)"]
        self.allow(argv)
        process = AsyncMock()
        process.wait.return_value = 0
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=process) as spawn, patch(
            "hyprland_mcp.server.hyprctl.dispatch", new_callable=AsyncMock
        ):
            result = await launch_app(argv)
        self.assertIn("Launched", result)
        self.assertEqual(spawn.call_args.args, tuple(argv))
        self.assertEqual(json.loads(self.config.read_text()), {"allowed_argv": [argv]})

    async def test_mcp_tool_launches_allowlisted_array(self):
        argv = ["/usr/bin/example", "literal;argument"]
        self.allow(argv)
        process = AsyncMock()
        process.wait.return_value = 0
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=process) as spawn:
            result = await mcp.call_tool("launch_app", {"command": argv})
        self.assertIn("Launched", str(result))
        self.assertEqual(spawn.call_args.args, tuple(argv))

    async def test_mcp_tool_rejects_old_string_with_migration_message(self):
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            with self.assertRaisesRegex(Exception, "(?i)(argv|array)"):
                await mcp.call_tool("launch_app", {"command": "firefox --new-window"})
            spawn.assert_not_called()

    async def test_fallback_config_path_and_running_process(self):
        config = Path(self.temp.name) / ".config" / "hyprland-mcp" / "launch-allowlist.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"allowed_argv": [["/usr/bin/example"]]}))
        process = AsyncMock()

        async def still_running():
            import asyncio
            await asyncio.sleep(10)

        process.wait.side_effect = still_running
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": ""}), patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=process
        ):
            result = await launch_app(["/usr/bin/example"])
        self.assertIn("still running", result)
        self.assertIn("unknown", result)

    async def test_rejects_invalid_arguments_before_spawning(self):
        self.allow(["/usr/bin/example"])
        invalid = [[], [""], ["/usr/bin/example", 1], ["/usr/bin/example", "x\0y"],
                   ["/usr/bin/example", "x" * 4097], ["/usr/bin/example"] * 129,
                   ["/usr/bin/example", "é" * 2049],
                   ["/usr/bin/example"] + ["x" * 4096] * 16]
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            for argv in invalid:
                with self.subTest(argv=repr(argv)[:100]), self.assertRaises(ValueError):
                    await launch_app(argv)
            with self.assertRaisesRegex(ValueError, "(?i)(argv|array)"):
                await launch_app("/usr/bin/example --flag")
            spawn.assert_not_called()

    async def test_missing_or_malformed_config_denies_launch(self):
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            with self.assertRaises((ValueError, OSError)):
                await launch_app(["/usr/bin/example"])
            for content in ("{", "{}", '{"allowed_argv": "x"}',
                            '{"allowed_argv": [["/usr/bin/example"], []]}',
                            '{"allowed_argv": [[1]]}',
                            '{"allowed_argv": [], "extra": true}'):
                self.config.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    await launch_app(["/usr/bin/example"])
            spawn.assert_not_called()

    async def test_allowlist_requires_exact_argv(self):
        self.allow(["/usr/bin/example", "one"])
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            for argv in (["/usr/bin/example"], ["/usr/bin/example", "two"],
                         ["/usr/bin/example", "one", "extra"]):
                with self.subTest(argv=argv), self.assertRaises(ValueError):
                    await launch_app(argv)
            spawn.assert_not_called()

    async def test_blocked_programs_are_rejected_even_if_allowlisted(self):
        names = ["sh", "bash", "env", "python", "python3.11", "sudo", "su",
                 "doas", "pkexec", "perl", "node", "xargs"]
        self.allow(*[["/usr/bin/" + name] for name in names])
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            for name in names:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    await launch_app(["/usr/bin/" + name])
            spawn.assert_not_called()

    async def test_blocked_program_symlink_is_rejected(self):
        alias = Path(self.temp.name) / "application"
        alias.symlink_to("/bin/sh")
        self.allow([str(alias)])
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            with self.assertRaises(ValueError):
                await launch_app([str(alias)])
            spawn.assert_not_called()

    async def test_shell_with_c_flag_is_rejected_when_allowlisted(self):
        argv = ["/bin/sh", "-c", "echo harmless"]
        self.allow(argv)
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            with self.assertRaises(ValueError):
                await launch_app(argv)
            spawn.assert_not_called()

    async def test_missing_executable_and_nonzero_exit_are_not_success(self):
        argv = ["/usr/bin/example"]
        self.allow(argv)
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock,
                   side_effect=FileNotFoundError("not found")):
            with self.assertRaises((OSError, RuntimeError)):
                await launch_app(argv)
        process = AsyncMock()
        process.wait.return_value = 7
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=process):
            with self.assertRaisesRegex(RuntimeError, "7"):
                await launch_app(argv)
