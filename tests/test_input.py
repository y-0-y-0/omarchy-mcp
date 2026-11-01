import asyncio
import sys
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

    async def test_cancelled_typing_stops_and_reaps_process(self):
        real_spawn = asyncio.create_subprocess_exec
        started = asyncio.Event()
        processes = []

        async def spawn(*args, **kwargs):
            if args[0] == "wtype":
                args = (sys.executable, "-c", "import time; time.sleep(30)")
                proc = await real_spawn(*args, **kwargs)
                processes.append(proc)
                started.set()
                return proc
            return await real_spawn(*args, **kwargs)

        with patch.object(desktop_input, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", side_effect=spawn
        ):
            task = asyncio.create_task(desktop_input.type_text("hello"))
            try:
                await asyncio.wait_for(started.wait(), 3)
                await asyncio.sleep(0.05)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertIsNotNone(processes[0].returncode)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                for proc in processes:
                    if proc.returncode is None:
                        proc.kill()
                    await proc.wait()

    async def test_repeated_cancellation_keeps_typing_serialized_until_reaped(self):
        for already_exited in (False, True):
            with self.subTest(already_exited=already_exited):
                real_spawn = asyncio.create_subprocess_exec
                communicating = asyncio.Event()
                cleanup_started = asyncio.Event()
                allow_cleanup = asyncio.Event()
                second_locale_checked = asyncio.Event()
                processes = []
                wtype_count = 0
                locale_count = 0

                class DelayedCleanupProcess:
                    def __init__(self, proc):
                        self.proc = proc

                    async def communicate(self, input=None):
                        if input is not None:
                            communicating.set()
                            return await self.proc.communicate(input=input)
                        if not already_exited:
                            cleanup_started.set()
                            await allow_cleanup.wait()
                        return await self.proc.communicate()

                    def kill(self):
                        self.proc.kill()
                        if already_exited:
                            raise ProcessLookupError

                    async def wait(self):
                        cleanup_started.set()
                        await allow_cleanup.wait()
                        return await self.proc.wait()

                async def spawn(*args, **kwargs):
                    nonlocal wtype_count, locale_count
                    if args[0] == "locale":
                        locale_count += 1
                        if locale_count == 2:
                            second_locale_checked.set()
                        locale = AsyncMock(returncode=0)
                        locale.communicate.return_value = (b"UTF-8\n", b"")
                        return locale
                    wtype_count += 1
                    if wtype_count == 1:
                        proc = await real_spawn(
                            sys.executable, "-c", "import time; time.sleep(30)", **kwargs
                        )
                        processes.append(proc)
                        return DelayedCleanupProcess(proc)
                    process = AsyncMock(returncode=0)
                    process.communicate.return_value = (b"", b"")
                    return process

                with patch.object(desktop_input, "require_tool"), patch.object(
                    asyncio, "create_subprocess_exec", side_effect=spawn
                ):
                    first = asyncio.create_task(desktop_input.type_text("first"))
                    second = None
                    try:
                        await asyncio.wait_for(communicating.wait(), 3)
                        first.cancel()
                        await asyncio.wait_for(cleanup_started.wait(), 3)
                        first.cancel()
                        second = asyncio.create_task(desktop_input.type_text("second"))
                        await asyncio.wait_for(second_locale_checked.wait(), 3)
                        await asyncio.sleep(0)
                        self.assertFalse(first.done())
                        self.assertEqual(wtype_count, 1)
                        allow_cleanup.set()
                        with self.assertRaises(asyncio.CancelledError):
                            await first
                        await asyncio.wait_for(second, 3)
                        self.assertEqual(wtype_count, 2)
                        self.assertIsNotNone(processes[0].returncode)
                    finally:
                        allow_cleanup.set()
                        for task in (first, second):
                            if task is not None and not task.done():
                                task.cancel()
                        await asyncio.gather(
                            *(task for task in (first, second) if task), return_exceptions=True
                        )
                        for proc in processes:
                            if proc.returncode is None:
                                proc.kill()
                            await proc.wait()

    async def test_concurrent_typing_does_not_overlap_processes(self):
        real_spawn = asyncio.create_subprocess_exec
        started = asyncio.Event()
        processes = []
        overlap = []

        async def spawn(*args, **kwargs):
            if args[0] == "wtype":
                overlap.append(any(proc.returncode is None for proc in processes))
                args = (sys.executable, "-c", "import time; time.sleep(0.3)")
                proc = await real_spawn(*args, **kwargs)
                processes.append(proc)
                started.set()
                return proc
            return await real_spawn(*args, **kwargs)

        with patch.object(desktop_input, "require_tool"), patch.object(
            asyncio, "create_subprocess_exec", side_effect=spawn
        ):
            first = asyncio.create_task(desktop_input.type_text("first"))
            second = None
            try:
                await asyncio.wait_for(started.wait(), 3)
                second = asyncio.create_task(desktop_input.type_text("second"))
                await asyncio.wait_for(asyncio.gather(first, second), 3)
                self.assertEqual(overlap, [False, False])
            finally:
                for task in (first, second):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(*(task for task in (first, second) if task), return_exceptions=True)
                for proc in processes:
                    if proc.returncode is None:
                        proc.kill()
                    await proc.wait()

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
