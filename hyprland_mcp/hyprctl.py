"""Async wrappers for hyprctl IPC commands."""

import asyncio
import json

from .errors import HyprctlError, require_tool


async def query(command: str) -> dict | list:
    """Run a hyprctl query command and return parsed JSON.

    Example: query("monitors") → list of monitor dicts
    """
    require_tool("hyprctl")
    proc = await asyncio.create_subprocess_exec(
        "hyprctl", "-j", command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HyprctlError("hyprctl query failed")
    try:
        result = json.loads(stdout)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HyprctlError("Invalid hyprctl JSON output") from None
    expected = list if command in ("monitors", "clients", "workspaces") else dict
    if not isinstance(result, expected):
        raise HyprctlError("Unexpected hyprctl JSON output")
    return result


async def dispatch(command: str, args: str = "") -> str:
    """Refuse legacy dispatch until a safe interface is available."""
    # shortcut: dispatch is disabled for all versions until its active mode can be handled safely.
    raise HyprctlError("Hyprland dispatch is unavailable: the safe Lua interface is not implemented")


async def batch(commands: list[str]) -> str:
    """Refuse unvalidated batched commands."""
    raise HyprctlError("Hyprland batch dispatch is unavailable")
