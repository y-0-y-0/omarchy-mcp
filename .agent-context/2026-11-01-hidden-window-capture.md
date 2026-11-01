# [omarchy-mcp] Context — Hidden window capture (2026-11-01)

Status: blocked — implementation and simulated checks are complete; live desktop verification remains unavailable.

Goal: correct the confirmed disclosure risk where a window selector targets a hidden workspace but grim returns the visible contents at the same geometry.

Evidence: real Hyprland 0.56.2 / Omarchy 4.0.6 testing reproduced the problem twice using synthetic windows; Hyprland 0.57.0 and the user's runner are unavailable here. Capture uses a screen rectangle, not an isolated window surface.

Plan: inspect supported compositor visibility data and callers; reproduce with a regression test; reject visibility that cannot be verified before and after capture; independently review and run available checks. Preserve existing user changes and avoid new dependencies or installing software. Document non-atomic checks and occlusion limitations.

Relevant files: hyprland_mcp/screenshot.py, hyprland_mcp/server.py, tests/test_screenshot.py, README.md. Stack: Python 3.11 in this orb; project requires Python >=3.10, MCP, Pillow and pytesseract; these dependencies are not currently installed here.

Progress: verified Hyprland 0.56.2/0.57.0 JSON workspace identity differences and reproduced the original bug locally using a mock process. The implementation checks visibility before and after capture, rejecting ambiguous selectors, invisible or pinned windows, normal windows covered by a special workspace and windows spanning monitors. The README documents restrictions and the lack of surface isolation. Independent security review found these extra cases; regression checks were added and passed. Tests for inactive workspaces and workspace changes failed before the fix and pass with simulated image dependencies; tests cover named and special workspaces and missing visibility data.

Checks: 19 screenshot tests pass using simulated Pillow/MCP modules (excluding the OCR integration case); 18 dependency-free existing tests pass. Python AST parsing, bash syntax and git diff --check passed. Pillow, MCP and pytesseract are unavailable in this orb, and no live Hyprland session is available.

Remaining: verify the fix on a real target desktop and run the complete suite with real dependencies when accessible. Screen-rectangle capture is not isolated: occlusion, animations and changes that revert between checks can still disclose other pixels. The code has not been committed or pushed.
