"""Hyprland MCP server — desktop automation tools for Claude."""

from mcp.server.fastmcp import FastMCP, Image
from mcp.server.fastmcp.exceptions import ToolError

from . import hyprctl
from .errors import HyprctlError, ScreenshotError, check_tools


DISPATCH_UNAVAILABLE = "Hyprland dispatch is unavailable: the safe Lua interface is not implemented"
LAUNCH_UNAVAILABLE = "Application launching is unavailable: a safe launch policy is not implemented"


class LaunchUnavailableError(Exception):
    """Application launching is disabled until a safe policy is available."""


class SafeFastMCP(FastMCP):
    async def call_tool(self, name: str, arguments: dict):
        try:
            return await super().call_tool(name, arguments)
        except ToolError as exc:
            cause = exc.__cause__
            if (isinstance(cause, HyprctlError) and str(cause) == DISPATCH_UNAVAILABLE
                    or isinstance(cause, LaunchUnavailableError) and str(cause) == LAUNCH_UNAVAILABLE):
                raise ToolError(str(cause)) from None
            raise ToolError("Tool failed: check arguments, argv format, and session configuration") from None
        except Exception:
            raise ToolError("Tool failed: check arguments, argv format, and session configuration") from None


mcp = SafeFastMCP(
    "hyprland",
    instructions=(
        "Desktop automation server for Hyprland (Wayland). "
        "Provides screenshots, mouse/keyboard input, window management, "
        "clipboard access, and app launching. All tools wrap native Hyprland "
        "and Wayland utilities — no X11 required. Hyprland dispatch-dependent "
        "actions and application launching are currently disabled. Mouse clicks "
        "and scrolling without coordinates remain available. Auto-scoped OCR "
        "falls back to the full desktop when no window is focused; captures "
        "are non-atomic and can contain overlapping windows or other content."
    ),
)


# ── Monitors & Workspaces ──────────────────────────────────────────────


@mcp.tool()
async def list_monitors() -> str:
    """List all connected monitors with resolution, position, and active workspace."""
    monitors = await hyprctl.query("monitors")
    lines = []
    for m in monitors:
        lines.append(
            f"- {m['name']}: {m['width']}x{m['height']}@{m['refreshRate']:.0f}Hz "
            f"at ({m['x']},{m['y']}), workspace {m['activeWorkspace']['name']}"
            f"{' [focused]' if m.get('focused') else ''}"
        )
    return "\n".join(lines)


@mcp.tool()
async def list_workspaces() -> str:
    """List all active workspaces with window counts."""
    workspaces = await hyprctl.query("workspaces")
    workspaces.sort(key=lambda w: (w.get("id") is None, w.get("id", 0), w["name"]))
    lines = []
    for w in workspaces:
        workspace_id = f" (id={w['id']})" if "id" in w else ""
        lines.append(
            f"- Workspace {w['name']}{workspace_id}: "
            f"{w['windows']} window(s), monitor {w['monitor']}"
        )
    return "\n".join(lines)


@mcp.tool()
async def switch_workspace(workspace: str) -> str:
    """Switch to a workspace by name or number.

    Currently disabled because Hyprland dispatch is unavailable.

    Args:
        workspace: Workspace name or number (e.g. "1", "3", "special:scratchpad")
    """
    await hyprctl.dispatch("workspace", workspace)
    return f"Switched to workspace {workspace}"


@mcp.tool()
async def get_cursor_position() -> str:
    """Get the current cursor position in absolute layout coordinates."""
    pos = await hyprctl.query("cursorpos")
    return f"Cursor at ({pos['x']}, {pos['y']})"


# ── Window Management ──────────────────────────────────────────────────


@mcp.tool()
async def list_windows(workspace: int | None = None, monitor: str | None = None) -> str:
    """List all open windows with class, title, size, and position.

    Args:
        workspace: Filter to a specific workspace number
        monitor: Filter to a specific monitor name
    """
    clients = await hyprctl.query("clients")
    if workspace is not None:
        clients = [c for c in clients if c["workspace"].get("id") == workspace]
    if monitor is not None:
        monitors = await hyprctl.query("monitors")
        monitor_ids = {m["id"] for m in monitors if m["name"] == monitor}
        clients = [c for c in clients if c["monitor"] in monitor_ids]
    if not clients:
        return "No windows found matching the filter."
    lines = []
    for c in clients:
        focused = " [focused]" if c.get("focusHistoryID") == 0 else ""
        lines.append(
            f"- [{c['class']}] \"{c['title']}\" — "
            f"{c['size'][0]}x{c['size'][1]} at ({c['at'][0]},{c['at'][1]}), "
            f"workspace {c['workspace']['name']}{focused}"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_active_window() -> str:
    """Get details about the currently focused window."""
    w = await hyprctl.query("activewindow")
    if not w or not w.get("class"):
        return "No window is currently focused."
    return (
        f"Active window: [{w['class']}] \"{w['title']}\"\n"
        f"Size: {w['size'][0]}x{w['size'][1]}, Position: ({w['at'][0]},{w['at'][1]})\n"
        f"Workspace: {w['workspace']['name']}, Monitor: {w['monitor']}\n"
        f"Floating: {w['floating']}, Fullscreen: {w['fullscreen']}"
    )


@mcp.tool()
async def focus_window(target: str) -> str:
    """Focus a window by class or title.

    Currently disabled because Hyprland dispatch is unavailable.

    Args:
        target: Window selector — "class:firefox", "title:My Document", etc.
    """
    await hyprctl.dispatch("focuswindow", target)
    return f"Focused window matching '{target}'"


@mcp.tool()
async def close_window(target: str | None = None) -> str:
    """Close a window (sends WM_CLOSE — apps can show save dialogs).

    Currently disabled because Hyprland dispatch is unavailable.

    Args:
        target: Window selector (e.g. "class:firefox"). If omitted, closes the active window.
    """
    await hyprctl.dispatch("closewindow", target or "")
    return f"Closed window{f' matching {target!r}' if target else ' (active)'}"


@mcp.tool()
async def move_window(
    target: str | None = None,
    x: int | None = None,
    y: int | None = None,
    workspace: str | None = None,
) -> str:
    """Move a window to a position or workspace.

    Moves are currently disabled because Hyprland dispatch is unavailable.

    Args:
        target: Window selector. If omitted, moves the active window.
        x: Target X position in pixels
        y: Target Y position in pixels
        workspace: Target workspace name/number to move the window to
    """
    results = []
    addr = target or ""
    if x is not None and y is not None:
        await hyprctl.dispatch("movewindowpixel", f"exact {x} {y},{addr}")
        results.append(f"Moved to ({x},{y})")
    if workspace is not None:
        if target:
            await hyprctl.dispatch("movetoworkspace", f"{workspace},{target}")
        else:
            await hyprctl.dispatch("movetoworkspace", workspace)
        results.append(f"Moved to workspace {workspace}")
    if not results:
        return "No position or workspace specified — nothing to do."
    return "; ".join(results)


@mcp.tool()
async def resize_window(
    width: int,
    height: int,
    target: str | None = None,
) -> str:
    """Resize a window to exact pixel dimensions.

    Currently disabled because Hyprland dispatch is unavailable.

    Args:
        width: Target width in pixels
        height: Target height in pixels
        target: Window selector. If omitted, resizes the active window.
    """
    await hyprctl.dispatch("resizewindowpixel", f"exact {width} {height},{target or ''}")
    return f"Resized to {width}x{height}"


@mcp.tool()
async def toggle_fullscreen(mode: str = "fullscreen") -> str:
    """Toggle fullscreen for the active window.

    Currently disabled because Hyprland dispatch is unavailable.

    Args:
        mode: "fullscreen" for real fullscreen, "maximize" for maximized (keeps bar)
    """
    flag = "0" if mode == "fullscreen" else "1"
    await hyprctl.dispatch("fullscreen", flag)
    return f"Toggled {mode}"


@mcp.tool()
async def toggle_floating(target: str | None = None) -> str:
    """Toggle floating mode for a window.

    Currently disabled because Hyprland dispatch is unavailable.

    Args:
        target: Window selector. If omitted, toggles the active window.
    """
    await hyprctl.dispatch("togglefloating", target or "")
    return f"Toggled floating{f' for {target}' if target else ''}"


# ── Clipboard ──────────────────────────────────────────────────────────


@mcp.tool()
async def clipboard_read() -> str:
    """Read the current clipboard contents as text."""
    from . import clipboard
    return await clipboard.read()


@mcp.tool()
async def clipboard_write(text: str) -> str:
    """Write text to the clipboard.

    Args:
        text: The text to copy to the clipboard
    """
    from . import clipboard
    await clipboard.write(text)
    return f"Copied {len(text)} characters to clipboard"


# ── App Launching ──────────────────────────────────────────────────────


@mcp.tool()
async def launch_app(command: list[str] | str) -> str:
    """Launch an application. Currently disabled pending a safe launch policy.

    Args:
        command: Application command or argument vector.
    """
    raise LaunchUnavailableError(LAUNCH_UNAVAILABLE)


# ── Input: Mouse ───────────────────────────────────────────────────────


@mcp.tool()
async def mouse_move(x: int, y: int) -> str:
    """Move the mouse cursor to absolute layout coordinates.

    Currently disabled because Hyprland dispatch is unavailable.

    Uses Hyprland's native movecursor — pixel-accurate, no acceleration issues.

    Args:
        x: Target X coordinate
        y: Target Y coordinate
    """
    from . import input as inp
    await inp.move_cursor(x, y)
    return f"Moved cursor to ({x}, {y})"


@mcp.tool()
async def mouse_click(
    button: str = "left",
    x: int | None = None,
    y: int | None = None,
    double: bool = False,
) -> str:
    """Click the mouse at a position (or current position if no coordinates given).

    Positioned clicks are disabled because Hyprland dispatch is unavailable;
    clicks without coordinates use the current cursor position.

    Args:
        button: "left", "right", or "middle"
        x: X coordinate to click at (optional — clicks at current position if omitted)
        y: Y coordinate to click at (optional)
        double: Whether to double-click
    """
    from . import input as inp
    if (x is None) != (y is None):
        raise ValueError("Both coordinates must be provided together")
    if button not in ("left", "right", "middle"):
        raise ValueError("Invalid mouse button")
    if x is not None and y is not None:
        await inp.move_cursor(x, y)
    await inp.click(button, double=double)
    pos = f" at ({x},{y})" if x is not None and y is not None else ""
    kind = "Double-clicked" if double else "Clicked"
    return f"{kind} {button}{pos}"


@mcp.tool()
async def mouse_scroll(
    direction: str = "down",
    amount: int = 3,
    x: int | None = None,
    y: int | None = None,
) -> str:
    """Scroll the mouse wheel.

    Positioned scrolling is disabled because Hyprland dispatch is unavailable;
    scrolling without coordinates uses the current cursor position.

    Args:
        direction: "up" or "down"
        amount: Number of scroll steps (default 3)
        x: X coordinate to scroll at (optional)
        y: Y coordinate to scroll at (optional)
    """
    from . import input as inp
    if (x is None) != (y is None):
        raise ValueError("Both coordinates must be provided together")
    if direction not in ("up", "down") or type(amount) is not int or amount <= 0:
        raise ValueError("Invalid scroll direction or amount")
    if x is not None and y is not None:
        await inp.move_cursor(x, y)
    await inp.scroll(direction, amount)
    pos = f" at ({x},{y})" if x is not None and y is not None else ""
    return f"Scrolled {direction} {amount} steps{pos}"


@mcp.tool()
async def mouse_drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    button: str = "left",
) -> str:
    """Drag from one position to another.

    Currently disabled because Hyprland dispatch is unavailable.

    Args:
        start_x: Starting X coordinate
        start_y: Starting Y coordinate
        end_x: Ending X coordinate
        end_y: Ending Y coordinate
        button: Mouse button to hold during drag ("left", "right", "middle")
    """
    from . import input as inp
    await inp.drag(start_x, start_y, end_x, end_y, button)
    return f"Dragged {button} from ({start_x},{start_y}) to ({end_x},{end_y})"


# ── Input: Keyboard ────────────────────────────────────────────────────


@mcp.tool()
async def type_text(text: str, delay_ms: int = 0) -> str:
    """Type text as if from a keyboard.

    Args:
        text: The text to type
        delay_ms: Delay between keystrokes in milliseconds (0 = instant)
    """
    from . import input as inp
    await inp.type_text(text, delay_ms=delay_ms)
    return f"Typed {len(text)} characters"


@mcp.tool()
async def key_press(keys: str, target: str | None = None) -> str:
    """Press a key combination.

    Currently disabled because Hyprland dispatch is unavailable.

    Uses Hyprland's native sendshortcut — can target specific windows without focusing them.

    Args:
        keys: Key combo string like "ctrl+c", "alt+F4", "super+1", "Return"
        target: Optional window selector to send the key to (e.g. "class:firefox").
                If omitted, sends to the active window.
    """
    from . import input as inp
    await inp.key_press(keys, target=target)
    return f"Pressed {keys}{f' on {target}' if target else ''}"


@mcp.tool()
async def send_shortcut(mods: str, key: str, target: str | None = None) -> str:
    """Send a keyboard shortcut via Hyprland (can target specific windows).

    Currently disabled because Hyprland dispatch is unavailable.

    Args:
        mods: Modifier keys (e.g. "CTRL", "SUPER SHIFT", "ALT CTRL", or "" for none)
        key: Key name (e.g. "c", "F4", "Return", "space")
        target: Optional window selector (e.g. "class:firefox"). Empty = active window.
    """
    target_str = target or ""
    await hyprctl.dispatch("sendshortcut", f"{mods}, {key}, {target_str}")
    desc = f"{mods}+{key}" if mods else key
    return f"Sent shortcut {desc}{f' to {target}' if target else ''}"


# ── Screenshot ─────────────────────────────────────────────────────────


@mcp.tool()
async def screenshot(
    monitor: str | None = None,
    window: str | None = None,
    region: str | None = None,
    max_width: int = 1024,
    quality: int = 60,
    include_cursor: bool = False,
) -> list:
    """Take a screenshot and return it as an inline image with coordinate mapping.

    Returns the image AND a coordinate mapping guide so you can convert image
    pixel positions to absolute screen coordinates for mouse tools.

    Supports three capture modes:
    - Full desktop/monitor (default): overview at reduced resolution
    - Window: capture a specific window by class/title
    - Region: capture a specific rectangle at higher resolution

    Args:
        monitor: Capture a specific monitor (e.g. "DP-1"). Default: all monitors.
        window: Capture a specific window by selector (e.g. "class:firefox")
        region: Capture a region as "X,Y WxH" (e.g. "100,200 800x600")
        max_width: Maximum output width in pixels (default 1024, lower = smaller output)
        quality: JPEG quality 1-100 (default 60, lower = smaller output)
        include_cursor: Whether to include the cursor in the screenshot
    """
    from . import screenshot as ss
    image, coord_info = await ss.take_screenshot(
        monitor=monitor,
        window=window,
        region=region,
        max_width=max_width,
        quality=quality,
        include_cursor=include_cursor,
    )
    return [image, coord_info]


# ── OCR & Smart Actions ────────────────────────────────────────────────


async def _auto_scope_capture(
    monitor: str | None, window: str | None, region: str | None,
) -> tuple[bytes, int, int]:
    """Capture screenshot, auto-scoping to the active window if no scope specified.

    Auto scope captures the active window's rectangle, or the full desktop if
    no window is focused. Before/after checks are not atomic: changes that
    revert between checks and overlapping content cannot be detected.
    """
    from . import screenshot as ss

    if any(value is not None for value in (monitor, window, region)):
        return await ss.capture_raw(monitor=monitor, window=window, region=region)

    def window_state(active: dict) -> tuple | None:
        if not active:
            return None
        try:
            address = active["address"]
            x, y = active["at"]
            width, height = active["size"]
            if (not isinstance(address, str) or not address or address == "0x0"
                    or any(type(value) is not int for value in (x, y, width, height))):
                raise ValueError
            ss._parse_geometry(f"{x},{y} {width}x{height}")
            return address, x, y, width, height
        except (KeyError, TypeError, ValueError):
            raise ScreenshotError("Cannot determine active window identity and geometry") from None

    before = window_state(await hyprctl.query("activewindow"))
    if before is None:
        capture = await ss.capture_raw()
    else:
        _, x, y, width, height = before
        capture = await ss.capture_raw(region=f"{x},{y} {width}x{height}")
    if window_state(await hyprctl.query("activewindow")) != before:
        raise ScreenshotError("Active window changed during capture")
    return capture


@mcp.tool()
async def find_text_on_screen(
    target: str,
    monitor: str | None = None,
    window: str | None = None,
    region: str | None = None,
    scope: str = "auto",
) -> str:
    """Find text on screen using OCR. Returns matching locations in screen coordinates.

    Take a screenshot, run OCR, and find all occurrences of the target text.
    Coordinates are in absolute screen space — ready to pass to mouse_click.
    Auto scope falls back to the full desktop if no window is focused. Capture
    checks are non-atomic and the window rectangle may include overlapping content.

    Args:
        target: Text to find (case-insensitive, supports multi-word)
        monitor: Limit search to a specific monitor
        window: Limit search to a specific window (e.g. "class:discord")
        region: Limit search to a region "X,Y WxH"
        scope: "auto" (default) captures just the active window for better accuracy.
               "full" captures the entire desktop.
    """
    from . import screenshot as ss, ocr

    if not target.strip() or scope not in ("auto", "full"):
        raise ValueError("Text must be nonempty and scope must be auto or full")
    if scope == "full" and all(value is None for value in (monitor, window, region)):
        png_bytes, origin_x, origin_y = await ss.capture_raw()
    else:
        png_bytes, origin_x, origin_y = await _auto_scope_capture(
            monitor, window, region,
        )

    boxes = ocr.extract_boxes(png_bytes)
    matches = ocr.find_text(boxes, target)

    if not matches:
        all_text = ocr.extract_text(png_bytes)
        preview = all_text[:500] + "..." if len(all_text) > 500 else all_text
        return f"Text '{target}' not found.\n\nOCR detected text:\n{preview}"

    lines = [f"Found {len(matches)} match(es) for '{target}':"]
    for m in matches:
        screen_x = m["x"] + origin_x + m["w"] // 2
        screen_y = m["y"] + origin_y + m["h"] // 2
        lines.append(
            f"- \"{m['text']}\" at screen ({screen_x}, {screen_y}) "
            f"[box: {m['x']+origin_x},{m['y']+origin_y} {m['w']}x{m['h']}, "
            f"conf: {m['conf']}%]"
        )
    return "\n".join(lines)


@mcp.tool()
async def click_text(
    target: str,
    button: str = "left",
    double: bool = False,
    monitor: str | None = None,
    window: str | None = None,
    region: str | None = None,
    occurrence: int = 1,
    scope: str = "auto",
) -> str:
    """Find text on screen and click it — screenshot + OCR + click in one call.

    Currently disabled because Hyprland dispatch is unavailable; no capture is performed.

    Args:
        target: Text to find and click (case-insensitive)
        button: Mouse button ("left", "right", "middle")
        double: Whether to double-click
        monitor: Limit search to a specific monitor
        window: Limit search to a specific window (e.g. "class:discord")
        region: Limit search to a region "X,Y WxH"
        occurrence: Which match to click if multiple found (1 = first/best, 2 = second, etc.)
        scope: "auto" (default) searches the active window. "full" searches entire desktop.
    """
    if not target.strip() or scope not in ("auto", "full") or occurrence < 1:
        raise ValueError("Invalid text, scope, or occurrence")
    if button not in ("left", "right", "middle"):
        raise ValueError("Invalid mouse button")
    raise HyprctlError(DISPATCH_UNAVAILABLE)


@mcp.tool()
async def type_into(
    text: str,
    input_hint: str | None = None,
    submit: bool = False,
    window: str | None = None,
) -> str:
    """Find a text input field, click it, type text, and optionally submit.

    Currently disabled because Hyprland dispatch is unavailable; no capture is performed.

    Args:
        text: The text to type
        input_hint: Placeholder or label text near the input field to click on
                    (e.g. "Type a message", "Search", "Message"). If omitted,
                    tries common placeholders.
        submit: Whether to press Enter after typing (default False)
        window: Target a specific window (e.g. "class:signal"). Default: active window.
    """
    raise HyprctlError(DISPATCH_UNAVAILABLE)


@mcp.tool()
async def screenshot_with_ocr(
    monitor: str | None = None,
    window: str | None = None,
    region: str | None = None,
    max_width: int = 1024,
    quality: int = 60,
    scope: str = "auto",
) -> list:
    """Take a screenshot AND run OCR, returning both the image and extracted text.

    More efficient than calling screenshot + find_text_on_screen separately.
    The returned text does not include word coordinates.
    Auto scope falls back to the full desktop if no window is focused. Capture
    checks are non-atomic and the window rectangle may include overlapping content.

    Args:
        monitor: Capture a specific monitor
        window: Capture a specific window (e.g. "class:discord")
        region: Capture a region as "X,Y WxH"
        max_width: Maximum output width for the image (default 1024)
        quality: JPEG quality for the image (default 60)
        scope: "auto" (default) captures the active window. "full" captures entire desktop.
    """
    from . import screenshot as ss, ocr

    if scope not in ("auto", "full"):
        raise ValueError("Scope must be auto or full")
    if scope == "full" and all(value is None for value in (monitor, window, region)):
        png_bytes, origin_x, origin_y = await ss.capture_raw()
    else:
        png_bytes, origin_x, origin_y = await _auto_scope_capture(
            monitor, window, region,
        )

    text = ocr.extract_text(png_bytes)
    image, _ = ss.resize_and_compress(png_bytes, max_width=max_width, quality=quality)

    return [image, f"OCR text:\n{text}"]


# ── Entry Point ────────────────────────────────────────────────────────


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
