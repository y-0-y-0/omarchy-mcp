"""Read-only regression checks: the installer must never be executed by tests."""

import re
import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"


class InstallerStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = INSTALLER.read_text()

    def test_canonical_repository_is_a_pipx_git_url(self):
        self.assertIn("git+https://github.com/y-0-y-0/omarchy-mcp.git", self.script)
        self.assertNotIn("alderban107/hyprland-mcp", self.script)

    def test_no_interactive_or_system_mutation_commands(self):
        self.assertNotRegex(self.script, r"(?m)^\s*(?:read\s|sudo\s|systemctl\s|groupadd\s|usermod\s|udevadm\s)")
        self.assertNotRegex(self.script, r"\bsudo\b")
        self.assertNotRegex(self.script, r"(?m)^\s*(?:pacman|apt-get|dnf|zypper|xbps-install|emerge)\s+(?:-S|install)")

    def test_local_checkout_is_preferred_and_reinstall_is_repeatable(self):
        self.assertIn('BASH_SOURCE[0]', self.script)
        self.assertIn('pyproject.toml', self.script)
        self.assertRegex(self.script, r'pipx install --force "\$[A-Za-z_]+"')

    def test_external_install_and_registration_cannot_consume_stdin(self):
        self.assertRegex(self.script, r'pipx install --force [^\n]*</dev/null')
        self.assertRegex(self.script, r'claude mcp list [^\n]*</dev/null')
        self.assertRegex(self.script, r'claude mcp add [^\n]*</dev/null')

    def test_claude_is_optional_and_existing_registration_is_preserved(self):
        self.assertRegex(self.script, r'if command -v claude\b')
        self.assertRegex(self.script, r'claude mcp list')
        self.assertRegex(self.script, r'claude mcp add\b')
        self.assertIn('already registered', self.script)
        self.assertIn('Could not inspect', self.script)

    def test_optional_tools_have_functional_advice(self):
        for tool in ("hyprctl", "grim", "wtype", "ydotool", "wl-copy", "wl-paste", "tesseract"):
            with self.subTest(tool=tool):
                self.assertRegex(self.script, rf'{re.escape(tool)}.*(?:Hyprland|screenshot|keyboard|mouse|clipboard|OCR)')
        self.assertIn('package manager', self.script)
        self.assertIn('pipx', self.script)
        self.assertNotIn('requires Hyprland.', self.script)


if __name__ == "__main__":
    unittest.main()
