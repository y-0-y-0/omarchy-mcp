# [omarchy-mcp] Context — Compatibility fixes (2026-10-31)

Status: blocked — published fixes have partial verification; live compatibility and remaining audit findings are unverified or unresolved.

Goal: implement and push corrections arising from the Hyprland 0.57.0 / Omarchy 4.0.6 review and earlier confirmed security findings. Preserve user files, secure dispatch and launch fail-closed behavior. Do not claim live desktop compatibility without a real session.

Acceptance: address confirmed defects safely with targeted regression tests, independently review changes, run available relevant checks, document any remaining compatibility blockers and push only the intended changes. No new dependencies or installation without authorization.

Relevant files: hyprland_mcp/server.py, hyprland_mcp/screenshot.py, tests/test_server.py, tests/test_screenshot.py, README.md; previous findings in 2026-10-31-version-compatibility.md and 2026-10-31-repository-report.md.

Plan: preserve disabled dispatch until a safe tested Lua interface exists; fix empty capture selectors and named workspace filtering, investigate further safe improvements, review and verify, then commit and push as requested. Current orb lacks MCP/Pillow/pytesseract and a real Wayland session. Existing uncommitted context files belong to previous work; do not include them in a push unless appropriate and authorized.

Progress: added named workspace filtering, empty window-selector rejection, stdin-based wtype input with UTF-8 validation, and OCR phrase matching and histogram memory improvements. Independent review identified locale, Unicode and OCR-spacing issues; these were addressed before publication. The dispatch and launch restrictions remain in place. Published to origin/main at b04d6a53d37f43e2ae44cce4c095a461478ae6a9; CI subscription enabled. Prior context notes were not included.

Checks: 18 tests passed across test_clipboard.py, test_hyprctl.py, test_input.py, and test_installer.py; seven OCR tests and the empty-selector regression passed with simulated dependency modules. Bash syntax, Python AST parsing, and git diff --check passed. Actual MCP, Pillow, Tesseract, wtype, Hyprland and Wayland integration have not been tested; project dependencies are absent and were not installed.

Remaining: validate on the target desktop and run the complete suite with dependencies; resolve the risk of capturing other visible content when selecting a hidden window and other outstanding audit findings. OCR spacing remains heuristic and can reject exceptionally spaced phrases.
