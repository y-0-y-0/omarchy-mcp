# hyprland-mcp

MCP server for Hyprland desktop automation. Gives AI assistants the ability to see the screen, control mouse and keyboard, manage windows, and interact with the desktop — all through Hyprland's native Wayland tools.

Built for [Claude Code](https://docs.anthropic.com/en/docs/claude-code), but works with any MCP client.

## What it does

- **Screenshots** — Capture the full desktop, a specific monitor, window, or region. Images are automatically resized and JPEG-compressed to fit within MCP output limits. Every screenshot includes a coordinate mapping so the AI knows how to translate image positions to screen coordinates.
- **OCR** — Find and click text on screen using Tesseract. `click_text("Send")` captures a screenshot, runs OCR, finds the text, and clicks it — all in one tool call. Auto-scopes to the active window for better accuracy.
- **Mouse** — Move, click, scroll, and drag. Positioning uses Hyprland's native `movecursor` (pixel-accurate, no mouse acceleration issues).
- **Keyboard** — Type text or send key combinations. Shortcuts can target specific windows without focusing them.
- **Window management** — List, focus, close, move, resize, fullscreen, and float windows.
- **Workspaces & monitors** — List workspaces, switch between them, query monitor layout and cursor position.
- **Clipboard** — Read and write clipboard text.
- **App launching** — Launch locally allowlisted applications directly, without a shell.

> **Compatibility:** Hyprland's Lua dispatch interface is not yet supported by
> the window, workspace, cursor, and shortcut actions in this version. Hyprland
> 0.57 removed legacy configuration support; those actions have not been verified
> on it. Omarchy and fractional-scale screenshot coordinates are not verified.

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
| `click_text` | Find text on screen via OCR and click it. One tool call replaces screenshot → parse → click. Auto-scopes to active window. |
| `find_text_on_screen` | Find text on screen via OCR. Returns screen coordinates of all matches, ready for `mouse_click`. |
| `type_into` | Find a text input field by placeholder text, click it, type, and optionally press Enter. |

### Mouse

| Tool | Description |
|------|-------------|
| `mouse_move` | Move cursor to absolute coordinates (pixel-accurate via Hyprland's `movecursor`) |
| `mouse_click` | Click at position or current location (left/right/middle, single/double) |
| `mouse_scroll` | Scroll wheel up/down at position or current location |
| `mouse_drag` | Click-drag from one position to another |

### Keyboard

| Tool | Description |
|------|-------------|
| `type_text` | Type text as keyboard input (via `wtype`) |
| `key_press` | Press a key combination like `ctrl+c`, `alt+F4` (via Hyprland `sendshortcut`) |
| `send_shortcut` | Send a shortcut with explicit modifiers and key, optionally targeting a specific window |

### Window Management

| Tool | Description |
|------|-------------|
| `list_windows` | List all windows with class, title, size, position (filterable by workspace/monitor) |
| `get_active_window` | Get details about the currently focused window |
| `focus_window` | Focus a window by class or title selector |
| `close_window` | Close a window (WM_CLOSE — apps can show save dialogs) |
| `move_window` | Move a window to a pixel position or workspace |
| `resize_window` | Resize a window to exact pixel dimensions |
| `toggle_fullscreen` | Toggle fullscreen or maximize mode |
| `toggle_floating` | Toggle floating mode |

### Workspace & Monitor

| Tool | Description |
|------|-------------|
| `list_monitors` | List connected monitors with resolution, position, refresh rate |
| `list_workspaces` | List active workspaces with window counts |
| `switch_workspace` | Switch to a workspace by name or number |
| `get_cursor_position` | Get current cursor position in absolute layout coordinates |

### Clipboard & System

| Tool | Description |
|------|-------------|
| `clipboard_read` | Read current clipboard text |
| `clipboard_write` | Write text to clipboard |
| `launch_app` | Launch an application with an exact, owner-allowlisted argument array |

## How it works

### Screenshot coordinate mapping

Multi-monitor setups and image scaling make coordinate translation tricky. Every `screenshot` call returns a coordinate mapping alongside the image:

```
Coordinate mapping: This 941x1030 image covers screen region
starting at absolute (5447, 38), native size 941x1030.
To convert image coordinates to absolute screen coordinates:
  screen_x = image_x * 1.00 + 5447
  screen_y = image_y * 1.00 + 38
```

This mapping has not been validated for fractional scaling, rotation, or all
multi-monitor layouts. Do not rely on it for precision input in those cases.

### OCR and dark themes

Tesseract OCR was designed for black text on white paper. Most desktop apps use dark themes, which tanks OCR accuracy. hyprland-mcp automatically detects dark-background screenshots and inverts them before running OCR, significantly improving text detection.

OCR tools auto-scope to the active window by default (configurable with `scope="full"` for the entire desktop). Smaller capture area = better OCR accuracy = more reliable coordinate mapping.

### Mouse positioning

Mouse movement uses `hyprctl dispatch movecursor` — Hyprland's native IPC command that sets the cursor to exact pixel coordinates. No mouse acceleration, no relative movement, no coordinate drift. ydotool is only used for click and scroll events (which don't involve positioning).

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

- `close_window` sends WM_CLOSE — apps can show "save changes?" dialogs. There is no force-kill tool.
- Mouse and keyboard input and launched applications run with the user's session
  privileges. Desktop automation can operate applications that access files;
  it is not a sandbox.
- `launch_app` reads only its owner-managed allowlist and executes permitted
  argument arrays directly. Existing string commands must migrate to arrays;
  shell operators are literal arguments, not shell syntax.
- To enable `launch_app`, create
  `$XDG_CONFIG_HOME/hyprland-mcp/launch-allowlist.json` (or
  `~/.config/hyprland-mcp/launch-allowlist.json` when `XDG_CONFIG_HOME` is
  unset) yourself, for example:

  ```json
  {"allowed_argv": [["/usr/bin/firefox"], ["/usr/bin/nautilus", "/home/user/Documents"]]}
  ```

  Every argument must match exactly, including an absolute executable path.
  Only allow trusted applications and arguments. Common shells, interpreters,
  wrappers, terminals and privilege tools are refused, but name checks cannot
  identify every program capable of executing code. This is not a sandbox.
- If a launched process is still running after a short observation, the tool
  reports that it started but cannot know whether it will later fail.
- Missing system tools produce clear error messages listing what to install.

## License

MIT
