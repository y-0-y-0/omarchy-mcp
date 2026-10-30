#!/usr/bin/env bash
set -euo pipefail

# Install from this checkout when run as a file, or from the canonical
# repository when piped to bash.
SOURCE="git+https://github.com/y-0-y-0/omarchy-mcp.git"
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
    if [[ -f "$SCRIPT_DIR/pyproject.toml" && -d "$SCRIPT_DIR/hyprland_mcp" ]]; then
        SOURCE="$SCRIPT_DIR"
    fi
fi

echo "hyprland-mcp installer"

# These tools are only needed by the corresponding runtime features. Their
# availability must not prevent installation or use of unrelated features.
check_tool() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf 'Missing %s: %s. Install it with your package manager when needed.\n' "$1" "$2"
    fi
}
check_tool hyprctl "Hyprland window and workspace control"
check_tool grim "screenshot capture"
check_tool wtype "keyboard text input"
check_tool ydotool "mouse clicks, scrolling and dragging"
check_tool wl-copy "clipboard write"
check_tool wl-paste "clipboard read"
check_tool tesseract "OCR text recognition (language data may also be needed)"

if ! command -v pipx >/dev/null 2>&1; then
    echo "pipx is required to install hyprland-mcp. Install pipx using your package manager or follow https://pipx.pypa.io/stable/installation/" >&2
    echo "If your package manager is unsupported, consult your distribution's documentation or the pipx installation guide, then rerun this script." >&2
    exit 1
fi

if [[ "$SOURCE" == git+* ]] && ! command -v git >/dev/null 2>&1; then
    echo "git is required to install from the remote repository. Install git with your package manager, or run this script from a local checkout." >&2
    exit 1
fi

echo "Installing hyprland-mcp from $SOURCE using pipx..."
export PIP_NO_INPUT=1 GIT_TERMINAL_PROMPT=0
pipx install --force "$SOURCE" </dev/null

# An absolute executable path works even when Claude's PATH does not include
# pipx's binary directory. Fall back to the command name on older pipx.
BIN_DIR="$(pipx environment --value PIPX_BIN_DIR </dev/null 2>/dev/null || true)"
SERVER_COMMAND="hyprland-mcp"
if [[ -n "$BIN_DIR" && -x "$BIN_DIR/hyprland-mcp" ]]; then
    SERVER_COMMAND="$BIN_DIR/hyprland-mcp"
else
    echo "Ensure the pipx binary directory is on your MCP client's PATH."
fi

if command -v claude >/dev/null 2>&1; then
    # Do not treat a failed inspection as an absent registration.
    if SERVERS="$(claude mcp list </dev/null 2>/dev/null)"; then
        if grep -qE '^[[:space:]]*hyprland:' <<< "$SERVERS"; then
            echo "Claude MCP server hyprland is already registered; leaving it unchanged."
        elif claude mcp add --transport stdio --scope user hyprland -- "$SERVER_COMMAND" </dev/null; then
            echo "Registered hyprland with Claude Code."
        else
            echo "Could not register with Claude Code; configure your MCP client manually." >&2
        fi
    else
        echo "Could not inspect Claude MCP registrations; leaving them unchanged. Configure your MCP client manually if needed." >&2
    fi
else
    echo "Claude Code not found; registration is optional. Configure your MCP client to run $SERVER_COMMAND."
fi

echo "Installation complete. Restart your MCP client after configuration."
