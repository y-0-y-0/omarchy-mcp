"""Mouse and keyboard input simulation.

Mouse positioning: hyprctl dispatch movecursor (native, pixel-accurate)
Mouse events: ydotool (click, scroll — events only, no positioning)
Key combos: hyprctl dispatch sendshortcut (native, can target windows)
Text typing: wtype (only remaining wtype use)
"""

import asyncio
import os
from weakref import WeakValueDictionary

from . import hyprctl
from .errors import InputError, require_tool

# Locks are scoped to an event loop and retained only while typing is active or queued.
_typing_locks: WeakValueDictionary = WeakValueDictionary()

# ydotool button codes (hex, with 0xC0 = down+up mask)
_BUTTON_MAP = {
    "left": "0xC0",
    "right": "0xC1",
    "middle": "0xC2",
}

# For mouse_drag: separate down/up codes
_BUTTON_DOWN = {
    "left": "0x40",
    "right": "0x41",
    "middle": "0x42",
}
_BUTTON_UP = {
    "left": "0x80",
    "right": "0x81",
    "middle": "0x82",
}


async def move_cursor(x: int, y: int) -> None:
    """Move cursor to absolute coordinates using Hyprland's native movecursor."""
    await hyprctl.dispatch("movecursor", f"{x} {y}")


async def click(button: str = "left", double: bool = False) -> None:
    """Click at the current cursor position using ydotool."""
    require_tool("ydotool")
    code = _BUTTON_MAP.get(button)
    if code is None:
        raise InputError(f"Unknown button: {button}. Use 'left', 'right', or 'middle'.")

    cmd = ["ydotool", "click", code]
    if double:
        cmd.extend(["-r", "2", "-D", "50"])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise InputError("ydotool click failed")


async def scroll(direction: str = "down", amount: int = 3) -> None:
    """Scroll the mouse wheel using ydotool."""
    if direction not in ("up", "down"):
        raise InputError("Scroll direction must be 'up' or 'down'.")
    if type(amount) is not int or amount <= 0:
        raise InputError("Scroll amount must be a positive integer.")
    require_tool("ydotool")
    # ydotool mousemove --wheel: positive Y = down, negative Y = up
    y_val = amount if direction == "down" else -amount
    proc = await asyncio.create_subprocess_exec(
        "ydotool", "mousemove", "--wheel", "-x", "0", "-y", str(y_val),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise InputError("ydotool scroll failed")


async def drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    button: str = "left",
) -> None:
    """Drag from one position to another."""
    require_tool("ydotool")
    down_code = _BUTTON_DOWN.get(button)
    up_code = _BUTTON_UP.get(button)
    if down_code is None:
        raise InputError(f"Unknown button: {button}")

    # Move to start position
    await move_cursor(start_x, start_y)
    await asyncio.sleep(0.05)

    # Button down
    proc = await asyncio.create_subprocess_exec(
        "ydotool", "click", down_code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await proc.communicate()
        if proc.returncode != 0:
            raise InputError("ydotool button press failed")
        await asyncio.sleep(0.05)
        await move_cursor(end_x, end_y)
        await asyncio.sleep(0.05)
    finally:
        proc = await asyncio.create_subprocess_exec(
            "ydotool", "click", up_code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode != 0:
            raise InputError("ydotool button release failed")


async def type_text(text: str, delay_ms: int = 0) -> None:
    """Type text using wtype."""
    if "\0" in text:
        raise InputError("Text cannot contain NUL characters")
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise InputError("Text is not valid Unicode") from None
    require_tool("wtype")
    # wtype decodes stdin using the C locale and may silently stop on invalid bytes.
    env = {**os.environ, "LC_ALL": "C.UTF-8"}
    try:
        locale_proc = await asyncio.create_subprocess_exec(
            "locale", "charmap", env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        charmap, _ = await locale_proc.communicate()
    except OSError:
        raise InputError("Unable to verify UTF-8 locale for wtype") from None
    if locale_proc.returncode != 0 or charmap.strip().upper() != b"UTF-8":
        raise InputError("UTF-8 locale unavailable for wtype")
    cmd = ["wtype"]
    if delay_ms > 0:
        cmd.extend(["-d", str(delay_ms)])
    cmd.append("-")

    loop = asyncio.get_running_loop()
    lock = _typing_locks.get(loop)
    if lock is None:
        lock = _typing_locks[loop] = asyncio.Lock()
    async with lock:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await proc.communicate(input=data)
        except asyncio.CancelledError:
            async def cleanup():
                try:
                    proc.kill()
                except ProcessLookupError:
                    await proc.wait()
                await proc.communicate()

            cleanup_task = asyncio.create_task(cleanup())
            while not cleanup_task.done():
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    continue
            cleanup_task.result()
            raise
        if proc.returncode != 0:
            raise InputError("wtype failed")


async def key_press(keys: str, target: str | None = None) -> None:
    """Press a key combination using hyprctl dispatch sendshortcut.

    Args:
        keys: Key combo like "ctrl+c", "alt+F4", "Return", "super+1"
        target: Optional window selector
    """
    # Parse "ctrl+shift+c" into mods="CTRL SHIFT" and key="c"
    parts = keys.split("+")
    if len(parts) == 1:
        mods = ""
        key = parts[0]
    else:
        key = parts[-1]
        mods = " ".join(p.upper() for p in parts[:-1])

    target_str = target or ""
    await hyprctl.dispatch("sendshortcut", f"{mods}, {key}, {target_str}")
