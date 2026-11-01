"""Screenshot capture and optimization using grim + Pillow."""

import asyncio
import io
import math
import re

from PIL import Image as PILImage
from mcp.server.fastmcp import Image

from . import hyprctl
from .errors import ScreenshotError, require_tool


def _parse_geometry(value: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"(-?\d+),(-?\d+) (\d+)x(\d+)", value)
    if not match:
        raise ScreenshotError("Invalid capture geometry; expected X,Y WxH")
    try:
        x, y, width, height = map(int, match.groups())
    except ValueError:
        raise ScreenshotError("Capture geometry is outside supported bounds") from None
    # grim uses signed 32-bit coordinates and pixman images have finite bounds.
    if (width < 1 or height < 1 or width > 32767 or height > 32767
            or width * height > 100_000_000
            or not all(-(2**31) <= v < 2**31 for v in (x, y, x + width, y + height))):
        raise ScreenshotError("Capture geometry is outside supported bounds")
    return x, y, width, height


def _monitor_rectangles(monitors: list) -> dict[str, tuple[int, int, int, int]]:
    """Convert Hyprland's pixel modes into unambiguous logical rectangles."""
    rectangles = {}
    try:
        for monitor in monitors:
            if monitor.get("disabled", False):
                continue
            name = monitor["name"]
            x, y = monitor["x"], monitor["y"]
            width, height = monitor["width"], monitor["height"]
            scale, transform = monitor["scale"], monitor["transform"]
            if (not isinstance(name, str) or not name or name in rectangles
                    or any(type(v) is not int for v in (x, y, width, height, transform))
                    or type(scale) not in (int, float) or not math.isfinite(scale)
                    or scale <= 0 or width <= 0 or height <= 0 or transform not in range(8)):
                raise ValueError
            if transform % 2:
                width, height = height, width
            logical_w, logical_h = width / scale, height / scale
            # Rounding rules have varied across compositor versions. Do not guess.
            if (abs(logical_w - round(logical_w)) > 1e-6
                    or abs(logical_h - round(logical_h)) > 1e-6):
                raise ValueError
            rectangles[name] = _parse_geometry(
                f"{x},{y} {round(logical_w)}x{round(logical_h)}"
            )
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise ScreenshotError("Cannot determine reliable monitor geometry") from None
    if not rectangles:
        raise ScreenshotError("No usable monitors")
    # Mirrored/overlapping outputs have ambiguous screen content.
    rects = list(rectangles.values())
    for i, (x, y, w, h) in enumerate(rects):
        for ox, oy, ow, oh in rects[i + 1:]:
            if max(x, ox) < min(x + w, ox + ow) and max(y, oy) < min(y + h, oy + oh):
                raise ScreenshotError("Overlapping monitor geometry is unsupported")
    return rectangles


def _covered(rect: tuple[int, int, int, int], monitors: list[tuple[int, int, int, int]]) -> bool:
    """Whether the entire rectangle is covered by the non-overlapping monitors."""
    x, y, width, height = rect
    area = sum(
        max(0, min(x + width, mx + mw) - max(x, mx))
        * max(0, min(y + height, my + mh) - max(y, my))
        for mx, my, mw, mh in monitors
    )
    return area == width * height


async def _get_window_geometry(
    selector: str, monitor_data: list, monitors: dict[str, tuple[int, int, int, int]],
) -> tuple:
    """Get a uniquely matching window whose workspace is visible on its monitor."""
    value = selector[6:] if selector.startswith(("class:", "title:")) else selector
    if not value.strip():
        raise ScreenshotError("Window selector must not be empty")
    clients = await hyprctl.query("clients")
    for client in clients:
        try:
            if selector.startswith("class:"):
                matches = client["class"].lower() == selector[6:].lower()
            elif selector.startswith("title:"):
                matches = selector[6:].lower() in client["title"].lower()
            else:
                matches = client["class"].lower() == selector.lower()
        except (AttributeError, KeyError, TypeError):
            raise ScreenshotError("Cannot identify window") from None
        if matches:
            try:
                key = "title" if selector.startswith("title:") else "class"
                needle = value.lower()
                candidates = [c for c in clients if (
                    needle in c[key].lower() if key == "title" else needle == c[key].lower()
                )]
                if len(candidates) != 1:
                    raise ScreenshotError("Window selector is ambiguous")
                address = client["address"]
                x, y = client["at"]
                width, height = client["size"]
                if (not isinstance(address, str) or not address or address == "0x0"
                        or any(type(v) is not int for v in (x, y, width, height))):
                    raise ValueError
                geometry = f"{x},{y} {width}x{height}"
                rect = _parse_geometry(geometry)
                if (client["mapped"] is not True or client["hidden"] is not False
                        or client["visible"] is not True
                        or client["pinned"] is not False or type(client["monitor"]) is not int
                        or client["monitor"] < 0):
                    raise ValueError
                matching = [m for m in monitor_data if m.get("id") == client["monitor"]]
                if (len(matching) != 1 or type(matching[0]["id"]) is not int
                        or matching[0].get("disabled", False) is not False):
                    raise ValueError
                target_monitor = matching[0]
                if not _covered(rect, [monitors[target_monitor["name"]]]):
                    raise ValueError
                workspace = client["workspace"]
                active = target_monitor["activeWorkspace"]
                special = target_monitor["specialWorkspace"]
                if not all(isinstance(w, dict) for w in (workspace, active, special)):
                    raise ValueError
                if not isinstance(workspace.get("name"), str) or not workspace["name"]:
                    raise ValueError
                if "address" in workspace or "type" in workspace:
                    # 0.57+: address is an addressable workspace name, not a pointer.
                    kind = workspace["type"]
                    if kind not in ("normal", "special"):
                        raise ValueError
                    for state, expected in ((active, "normal"), (special, "special")):
                        if (not all(isinstance(state.get(k), str) for k in ("address", "type", "name"))
                                or ("id" in state and (type(state["id"]) is not int or state["id"] == 0))):
                            raise ValueError
                        if state is special and not state["address"]:
                            if state["type"] or state["name"] or "id" in state:
                                raise ValueError
                        elif state["type"] != expected or not state["address"] or not state["name"]:
                            raise ValueError
                    current = active if kind == "normal" else special
                    if kind == "normal" and special["address"]:
                        raise ValueError
                    if (not isinstance(workspace["address"], str) or not workspace["address"]
                            or any(workspace.get(k) != current.get(k) for k in ("address", "type", "name"))
                            or ("id" in workspace) != ("id" in current)):
                        raise ValueError
                    if "id" in workspace and (type(workspace["id"]) is not int
                                               or type(current["id"]) is not int
                                               or workspace["id"] != current["id"]):
                        raise ValueError
                else:
                    # 0.56: special workspace IDs are in [-99, -2].
                    ws_id = workspace["id"]
                    if type(ws_id) is not int or ws_id in (-1, 0):
                        raise ValueError
                    if (type(active.get("id")) is not int or active["id"] in range(-99, 1)
                            or not isinstance(active.get("name"), str) or not active["name"]
                            or type(special.get("id")) is not int
                            or not isinstance(special.get("name"), str)
                            or not ((special["id"] == 0 and not special["name"])
                                    or (-99 <= special["id"] <= -2 and special["name"]))
                            or any("address" in state or "type" in state for state in (active, special))):
                        raise ValueError
                    current = special if -99 <= ws_id <= -2 else active
                    if current is active and special["id"] != 0:
                        raise ValueError
                    if (type(current.get("id")) is not int or current["id"] != ws_id
                            or current.get("name") != workspace["name"]
                            or "address" in current or "type" in current):
                        raise ValueError
                # Include both workspace states so switches on this output invalidate capture.
                return address, geometry, client["monitor"], workspace.copy(), active.copy(), special.copy()
            except (AttributeError, KeyError, TypeError, ValueError):
                raise ScreenshotError("Cannot verify window visibility or geometry") from None
    raise ScreenshotError("No matching window found")


async def capture_raw(
    monitor: str | None = None,
    window: str | None = None,
    region: str | None = None,
    include_cursor: bool = False,
) -> tuple[bytes, int, int]:
    """Capture PNG at one pixel per logical coordinate for OCR callers."""
    if sum(value is not None for value in (monitor, window, region)) > 1:
        raise ScreenshotError("Choose only one capture scope")
    if any(value == "" for value in (monitor, window, region)):
        raise ScreenshotError("Capture scope must not be empty")
    require_tool("grim")
    monitor_data = await hyprctl.query("monitors")
    monitors = _monitor_rectangles(monitor_data)
    if window is not None:
        window_state = await _get_window_geometry(window, monitor_data, monitors)
        geometry = window_state[1]
        rect = _parse_geometry(geometry)
    elif region is not None:
        rect = _parse_geometry(region)
    elif monitor is not None:
        if monitor not in monitors:
            raise ScreenshotError("Monitor not found")
        rect = monitors[monitor]
    else:
        x = min(r[0] for r in monitors.values())
        y = min(r[1] for r in monitors.values())
        right = max(r[0] + r[2] for r in monitors.values())
        bottom = max(r[1] + r[3] for r in monitors.values())
        rect = _parse_geometry(f"{x},{y} {right - x}x{bottom - y}")

    # OCR consumers add the origin without checking whether a point is on an output.
    if not _covered(rect, list(monitors.values())):
        raise ScreenshotError("Capture region is not fully covered by monitors")
    x, y, width, height = rect
    cmd = ["grim", "-t", "png", "-l", "0", "-s", "1", "-g", f"{x},{y} {width}x{height}"]
    if include_cursor:
        cmd.append("-c")
    cmd.append("-")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except OSError:
        raise ScreenshotError("Unable to start grim") from None
    if proc.returncode != 0 or not stdout:
        raise ScreenshotError("grim capture failed")
    # In particular, grim warns when it has to guess output logical geometry.
    if stderr.strip():
        raise ScreenshotError("grim reported a warning; capture geometry cannot be verified")
    try:
        with PILImage.open(io.BytesIO(stdout)) as image:
            if image.format != "PNG" or image.size != (width, height):
                raise ScreenshotError("Capture dimensions do not match logical geometry")
            image.verify()
    except (OSError, ValueError, SyntaxError, PILImage.DecompressionBombError):
        raise ScreenshotError("grim returned an invalid PNG") from None
    after = await hyprctl.query("monitors")
    fields = ("name", "x", "y", "width", "height", "scale", "transform", "disabled")
    before_state = {m["name"]: tuple(m.get(field) for field in fields) for m in monitor_data}
    after_state = {m["name"]: tuple(m.get(field) for field in fields) for m in after}
    if _monitor_rectangles(after) != monitors or after_state != before_state:
        raise ScreenshotError("Monitor layout changed during capture")
    if window is not None and await _get_window_geometry(window, after, monitors) != window_state:
        raise ScreenshotError("Window identity or geometry changed during capture")
    return stdout, x, y


def resize_and_compress(
    png_bytes: bytes,
    max_width: int = 1024,
    quality: int = 60,
) -> tuple[Image, float]:
    """Resize and JPEG-compress a PNG. Returns (Image, width scale factor)."""
    if type(max_width) is not int or not 1 <= max_width <= 32767:
        raise ScreenshotError("max_width must be between 1 and 32767")
    if type(quality) is not int or not 1 <= quality <= 100:
        raise ScreenshotError("quality must be between 1 and 100")
    try:
        with PILImage.open(io.BytesIO(png_bytes)) as source:
            img = source.copy()
        scale = min(1.0, max_width / img.width)
        if scale < 1:
            img = img.resize((max_width, max(1, int(img.height * scale))), PILImage.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
    except (OSError, ValueError, SyntaxError, PILImage.DecompressionBombError):
        raise ScreenshotError("Unable to process screenshot") from None
    return Image(data=buf.getvalue(), format="jpeg"), scale


async def take_screenshot(
    monitor: str | None = None,
    window: str | None = None,
    region: str | None = None,
    max_width: int = 1024,
    quality: int = 60,
    include_cursor: bool = False,
) -> tuple[Image, str]:
    """Capture a screenshot and return it with logical coordinate mapping."""
    png_bytes, origin_x, origin_y = await capture_raw(
        monitor=monitor, window=window, region=region, include_cursor=include_cursor,
    )
    with PILImage.open(io.BytesIO(png_bytes)) as native_img:
        native_w, native_h = native_img.size
    image, scale = resize_and_compress(png_bytes, max_width=max_width, quality=quality)
    img_w = min(native_w, max_width)
    img_h = max(1, int(native_h * scale)) if scale < 1 else native_h
    coord_info = (
        f"Coordinate mapping: This {img_w}x{img_h} image covers screen region "
        f"starting at absolute ({origin_x}, {origin_y}), "
        f"logical size {native_w}x{native_h}.\n"
        f"To convert image coordinates to absolute screen coordinates:\n"
        f"  screen_x = image_x * {native_w}/{img_w} + {origin_x}\n"
        f"  screen_y = image_y * {native_h}/{img_h} + {origin_y}\n"
        f"IMPORTANT: Always use absolute screen coordinates with mouse tools, "
        f"never raw image pixel positions."
    )
    return image, coord_info
