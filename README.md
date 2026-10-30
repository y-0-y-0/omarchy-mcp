# hyprland-mcp

MCP server for Hyprland desktop automation. This draft exposes screen, clipboard,
and limited input tools; window management and several other actions are disabled
as described below. Desktop compatibility has not been verified.

Built for [Claude Code](https://docs.anthropic.com/en/docs/claude-code), but works with any MCP client.

## What it does

- **Screenshots** — Capture the full desktop, a specific monitor, window, or region. Images are automatically resized and JPEG-compressed to fit within MCP output limits. Every screenshot includes a coordinate mapping so the AI knows how to translate image positions to screen coordinates.
- **OCR** — Find text on screen using Tesseract; automatic clicking is currently unavailable.
- **Mouse** — Click and scroll at the current cursor position; positioning and dragging are currently unavailable.
- **Keyboard** — Type text. Shortcuts are currently unavailable.
- **Window management** — List windows; actions are currently unavailable.
- **Workspaces & monitors** — List workspaces and query monitor layout and cursor position; workspace switching is currently unavailable.
- **Clipboard** — Read and write clipboard text.
- **App launching** — Currently unavailable pending a reviewed executable trust policy.

> **Do not deploy this draft.** Dispatch is disabled for every Hyprland version
> because Lua-mode dispatch evaluates its input. Window and workspace actions,
> cursor movement, shortcuts, and actions that depend on them therefore fail.
> Application launching is also disabled because the former allowlist has
> unresolved trust and filesystem security issues. No real Omarchy or Hyprland
> session has been tested.

### Compatibility status

| Environment | Status | Evidence and limitation |
|---|---|---|
| Omarchy 4.0.6 | Not verified | Lua configuration reviewed in upstream source only. |
| Hyprland 0.56.2 | Not compatible for dispatch actions | Supports both Lua and legacy config; actions are disabled in both modes. |
| Hyprland 0.57.0 | Not compatible for dispatch actions | Lua-only; actions are disabled. No live session tested. |
| Python 3.11.6 / MCP 1.30.0 | Conditionally supported | Unit tests and isolated package installation; desktop behavior not verified. |
| Python 3.10 or other MCP 1.x | Not verified | Declared dependency range is not a tested compatibility guarantee. |

Omarchy 4.0.6 loads `hyprland.lua`, its bootstrap and defaults, then the user's
`hypr.*` modules and generated toggle state. This server does not modify those
files or reload Hyprland. See the upstream [entry point](https://github.com/omacom/omarchy/blob/v4.0.6/config/hypr/hyprland.lua)
and [bootstrap](https://github.com/omacom/omarchy/blob/v4.0.6/default/hypr/bootstrap.lua).
Avoid `omarchy-refresh-hyprland`: it replaces user configuration.

## Requirements

- [Hyprland](https://hyprland.org/) (Wayland compositor)
- Python 3.10+
- System tools, only for the features that use them: `grim` for screenshots,
  `wtype` for typing, `ydotool` for mouse buttons and scrolling, `wl-clipboard`
  (`wl-copy`/`wl-paste`) for clipboard access, and `tesseract` plus language
  data for OCR. `ydotool` also requires its daemon and access to uinput; set
  these up according to your distribution's documentation.

The installer reports missing tools; it does not install system packages or
change services, device permissions, or groups.

## Installation

Clone the verified repository, inspect `install.sh`, then run it:

```bash
git clone https://github.com/y-0-y-0/omarchy-mcp.git
cd omarchy-mcp
./install.sh
```

The non-interactive installer uses pipx, reports optional missing tools, and
registers with Claude Code if available without replacing an existing entry.

Restart Claude Code after installing.

Verify with `claude mcp list` — you should see `hyprland: ✓ Connected`.

<details>
<summary>Manual installation</summary>

```bash
pipx install git+https://github.com/y-0-y-0/omarchy-mcp.git
claude mcp add --transport stdio --scope user hyprland -- hyprland-mcp
```

Or from a local clone:

```bash
git clone https://github.com/y-0-y-0/omarchy-mcp.git
cd omarchy-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
claude mcp add --transport stdio --scope user hyprland -- /path/to/hyprland-mcp/.venv/bin/hyprland-mcp
```

</details>

## Tools (27)

### Screenshot & OCR

| Tool | Description |
|------|-------------|
| `screenshot` | Capture desktop, monitor, window, or region. Returns inline JPEG + coordinate mapping for translating image positions to screen coordinates. |
| `screenshot_with_ocr` | Screenshot + OCR in one call. Returns the image and all detected text. Auto-scopes to active window. |
| `click_text` | Unavailable: cursor positioning is disabled. |
| `find_text_on_screen` | Find text via OCR and report estimated screen coordinates; positioned clicking is unavailable. |
| `type_into` | Unavailable: cursor positioning is disabled. |

### Mouse

| Tool | Description |
|------|-------------|
| `mouse_move` | Unavailable: dispatch is disabled. |
| `mouse_click` | Click at current location; positioned clicks are unavailable. |
| `mouse_scroll` | Scroll at current location; positioned scrolls are unavailable. |
| `mouse_drag` | Unavailable: cursor positioning is disabled. |

### Keyboard

| Tool | Description |
|------|-------------|
| `type_text` | Type text as keyboard input (via `wtype`) |
| `key_press` | Unavailable: dispatch is disabled. |
| `send_shortcut` | Unavailable: dispatch is disabled. |

### Window Management

| Tool | Description |
|------|-------------|
| `list_windows` | List all windows with class, title, size, position (filterable by workspace/monitor) |
| `get_active_window` | Get details about the currently focused window |
| `focus_window`, `close_window`, `move_window`, `resize_window`, `toggle_fullscreen`, `toggle_floating` | Unavailable: dispatch is disabled. |

### Workspace & Monitor

| Tool | Description |
|------|-------------|
| `list_monitors` | List connected monitors with resolution, position, refresh rate |
| `list_workspaces` | List active workspaces with window counts |
| `switch_workspace` | Unavailable: dispatch is disabled. |
| `get_cursor_position` | Get current cursor position in absolute layout coordinates |

### Clipboard & System

| Tool | Description |
|------|-------------|
| `clipboard_read` | Read current clipboard text |
| `clipboard_write` | Write text to clipboard |
| `launch_app` | Unavailable: executable trust policy is not implemented. |

## How it works

### Screenshot coordinate mapping

Multi-monitor setups and image scaling make coordinate translation tricky. Every `screenshot` call returns a coordinate mapping alongside the image:

```
Coordinate mapping: This 941x1030 image covers screen region
starting at absolute (5447, 38), logical size 941x1030.
To convert image coordinates to absolute screen coordinates:
  screen_x = image_x * 941/941 + 5447
  screen_y = image_y * 1030/1030 + 38
```

Capture requests use `grim -s 1` and logical monitor geometry. Overlapping
outputs, uncovered regions, ambiguous fractional geometry, and detected layout
changes during capture are rejected. Before/after checks are not atomic and
cannot detect transient changes that revert. These checks are based on simulated tests;
fractional scaling, rotation, and multi-monitor layouts have not been validated
on a real desktop. Do not rely on the mapping for precision input.

### OCR and dark themes

Tesseract OCR was designed for black text on white paper. Most desktop apps use dark themes, which tanks OCR accuracy. hyprland-mcp automatically detects dark-background screenshots and inverts them before running OCR, significantly improving text detection.

OCR tools auto-scope to the active window by default (configurable with `scope="full"` for the entire desktop). This is a capture of its visible rectangle, not isolated window content: overlapping windows may appear. Before/after checks cannot eliminate focus, geometry, or occlusion races.

### Mouse positioning

Mouse positioning is currently unavailable because legacy `hyprctl dispatch`
arguments are unsafe under Lua. As a result `mouse_move`, positioned clicks and
scrolls, dragging, `click_text`, and `type_into` cannot complete. Clicking or
scrolling at the current position does not require dispatch.

### Screenshot sizing

Screenshots are automatically scaled to fit within MCP output limits. Default: max width 1024px, JPEG quality 60. A 2560x1440 desktop becomes ~80-100KB — small enough for inline display in the conversation.

For reading fine text or UI details, use the `region` parameter to capture a smaller area at full resolution, or capture a specific `window`.

## Project structure

```
hyprland_mcp/
  server.py       # FastMCP instance, all tool definitions, entry point
  hyprctl.py      # Async wrappers for hyprctl IPC (query, dispatch, batch)
  screenshot.py   # grim capture + Pillow resize/compress + coordinate mapping
  input.py        # Mouse (movecursor + ydotool) and keyboard (wtype + sendshortcut)
  clipboard.py    # wl-copy / wl-paste wrappers
  ocr.py          # Tesseract OCR with dark-theme preprocessing
  errors.py       # Exception hierarchy + tool availability checks
```

## Safety

- `close_window` is unavailable while dispatch is disabled.
- Mouse and keyboard input and launched applications run with the user's session
  privileges. Desktop automation can operate applications that access files;
  it is not a sandbox.
- `launch_app` is disabled before reading configuration or starting a process.
  The previous allowlist lacked ownership, permission, symlink and race checks;
  name-based exclusions cannot reliably detect scripts, renamed interpreters or
  wrappers. A future allowlist would not be a sandbox or constrain the behavior
  of an allowed application.
- MCP tool errors are sanitized and may not name a missing system tool.

## Diagnostics

On the target session, check `hyprctl version`, `hyprctl -j monitors`, and
`hyprctl configerrors` without copying sensitive output into bug reports.
Check that the MCP client inherits the Wayland session environment and that
the optional tools and permissions described above are available. Tool errors
are deliberately sanitized; inspect configuration locally, without sharing
clipboard contents, window titles, screenshots, or application arguments.
The installation script itself has not been executed in this validation.

## License

MIT
