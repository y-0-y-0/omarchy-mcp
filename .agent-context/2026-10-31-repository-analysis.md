# [omarchy-mcp] Context — Repository analysis (2026-10-31)

Status: done for the requested analysis; real desktop and full dependency-based validation remain unperformed.

Goal: explain the stack and operation of the entire repository, then independently audit bugs, security and other weaknesses with subagents. Deliver an evidence-based report in French; do not modify application code or real desktop configuration.

Scope: README.md, pyproject.toml, install.sh, hyprland_mcp/ and tests/. The existing modernization note records deliberately disabled dispatch and launching; verify current code rather than treating historical results as current evidence.

Plan: independently map server and desktop integrations; then assign separate adversarial analyses for correctness and security; validate material findings with local, non-destructive checks where possible. Record test commands and real-session limitations. No dependency installation, external scans, deployment or installer execution.

Progress: two subagents mapped the server and desktop integrations; two separate subagents audited correctness and security. Findings were reviewed, with local simulations for window selection, empty title selectors, wtype arguments, and OCR phrase matching. The full French report is [Repository report](2026-10-31-repository-report.md). No application code or desktop configuration was changed.

Verification: 16 stdlib-only unittest tests passed across clipboard, hyprctl, input, and installer; bash -n install.sh and Python syntax parsing of 15 files passed. No installer execution, dependency installation, full test suite, dependency CVE audit, external scan, or real Hyprland session. Python 3.11.6 is installed; MCP, Pillow and pytesseract are absent from the current interpreter.

Remaining risks: capture may select an unseen window, blank title selectors match the first window, OCR can generate incorrect matches or exhaust resources, wtype arguments can reveal entered text, and clipboard reads are unbounded. See the report for precise conditions, evidence, additional findings, and suggested fixes. No fix was requested or implemented.
