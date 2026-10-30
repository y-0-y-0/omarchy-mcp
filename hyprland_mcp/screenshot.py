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


async def _get_window_geometry(selector: str) -> tuple[str, str]:
    """Get a window's identity and logical geometry for grim."""
    clients = await hyprctl.query("clients")
    for client in clients:
        if selector.startswith("class:"):
            matches = client["class"].lower() == selector[6:].lower()
        elif selector.startswith("title:"):
            matches = selector[6:].lower() in client["title"].lower()
        else:
            matches = client["class"].lower() == selector.lower()
        if matches:
            try:
                address = client["address"]
                x, y = client["at"]
                width, height = client["size"]
                if (not isinstance(address, str) or not address or address == "0x0"
                        or any(type(v) is not int for v in (x, y, width, height))):
                    raise ValueError
                geometry = f"{x},{y} {width}x{height}"
                _parse_geometry(geometry)
                return address, geometry
            except (KeyError, TypeError, ValueError):
                raise ScreenshotError("Invalid window geometry") from None
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
        address, geometry = await _get_window_geometry(window)
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
    if window is not None and await _get_window_geometry(window) != (address, geometry):
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
