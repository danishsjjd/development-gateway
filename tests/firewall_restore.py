"""Real nftables regression tests; run only via scripts/test-firewall.sh."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
TARGETS = [
    Path("/etc/caddy-gateway.nft"),
    Path("/etc/systemd/system/caddy-gateway-firewall.service"),
    Path("/etc/systemd/system/docker.service.d/caddy-gateway-firewall.conf"),
]
PREVIOUS_RULES = """table inet caddy_gateway {
    chain input {
        type filter hook input priority -10; policy accept;
        tcp dport 4321 drop
    }
}
"""


class FirewallRestoreTests(unittest.TestCase):
    def nft(self, *args, check=True):
        return subprocess.run(["/usr/bin/nft", *args], check=check,
                              capture_output=True, text=True)

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="restore-"))
        self.addCleanup(shutil.rmtree, self.directory)
        self.backup = self.directory / "backup"
        self.backup.mkdir()
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.log = self.directory / "systemctl.log"
        self.environment = {
            "PATH": str(self.bin) + ":/usr/bin:/bin",
            "HOME": "/scratch", "TMPDIR": "/scratch",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SYSTEMCTL_TEST_LOG": str(self.log),
        }
        # Fail the test if restoration ever stops/restarts a required service.
        # The real system bus and host service units are absent from the sandbox.
        self.write_executable("systemctl", """#!/usr/bin/python3
import json, os, sys
with open(os.environ['SYSTEMCTL_TEST_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1] not in ('disable', 'enable', 'daemon-reload', 'start'):
    sys.exit(99)
""")
        for index, target in enumerate(TARGETS):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("installed " + str(index))
            (self.backup / target.name).write_text("previous " + str(index))
        (self.backup / "prepared.nft").touch()
        (self.backup / "previous.nft").write_text(PREVIOUS_RULES)
        for marker in ("table.present", "service.active", "service.enabled"):
            (self.backup / marker).touch()
        # Flushing is safe only in this fresh, isolated network namespace.
        self.nft("flush", "ruleset")
        self.nft("--file", str(ROOT / "firewall/caddy-gateway.nft"))
        self.nft("add", "table", "inet", "unrelated")
        self.current_rules = self.nft("list", "ruleset").stdout

    def write_executable(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o700)

    def restore(self):
        return subprocess.run(["/bin/sh", str(ROOT / "scripts/restore-firewall.sh"),
                               str(self.backup)], env=self.environment,
                              capture_output=True, text=True, timeout=5)

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def assert_unchanged(self):
        self.assertEqual(self.nft("list", "ruleset").stdout, self.current_rules)
        for index, target in enumerate(TARGETS):
            self.assertEqual(target.read_text(), "installed " + str(index))
        self.assertEqual(self.calls(), [])
        self.assertEqual(list(self.backup.glob("restore-*.nft")), [])

    def test_restores_rules_and_files_without_stopping_services(self):
        result = self.restore()
        self.assertEqual(result.returncode, 0, result.stderr)
        rules = self.nft("list", "table", "inet", "caddy_gateway").stdout
        self.assertIn("tcp dport 4321 drop", rules)
        self.assertNotIn("3000-9999", rules)
        self.assertEqual(self.nft("list", "table", "inet", "unrelated").returncode, 0)
        for index, target in enumerate(TARGETS):
            self.assertEqual(target.read_text(), "previous " + str(index))
        self.assertEqual(self.calls(), [
            ["disable", "caddy-gateway-firewall.service"], ["daemon-reload"],
            ["enable", "caddy-gateway-firewall.service"],
            ["start", "caddy-gateway-firewall.service"],
        ])
        self.assertEqual(list(self.backup.glob("restore-*.nft")), [])

    def test_invalid_snapshot_preserves_rules_files_and_services(self):
        (self.backup / "previous.nft").write_text("invalid nftables syntax\n")
        result = self.restore()
        self.assertNotEqual(result.returncode, 0)
        self.assert_unchanged()

    def test_apply_failure_after_check_keeps_current_rules(self):
        # Check succeeds, then the apply fails inside the same kernel transaction.
        # A split delete/load implementation would already have lost protection.
        self.write_executable("nft", """#!/usr/bin/python3
import os, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] in ('--file', '-f'):
    replacement = Path(args[1]).with_suffix('.failure')
    replacement.write_text(Path(args[1]).read_text() +
        'add rule inet caddy_gateway missing_chain counter\\n')
    try:
        sys.exit(subprocess.run(['/usr/bin/nft', '--file', str(replacement)]).returncode)
    finally:
        replacement.unlink()
os.execv('/usr/bin/nft', ['/usr/bin/nft'] + args)
""")
        result = self.restore()
        self.assertNotEqual(result.returncode, 0)
        self.assert_unchanged()

    def test_missing_file_backup_preserves_current_state(self):
        (self.backup / TARGETS[1].name).unlink()
        self.assertNotEqual(self.restore().returncode, 0)
        self.assert_unchanged()

    def test_missing_rule_backup_preserves_current_state(self):
        (self.backup / "previous.nft").unlink()
        self.assertNotEqual(self.restore().returncode, 0)
        self.assert_unchanged()

    def test_snapshot_without_prior_installation_removes_only_gateway_state(self):
        for target in TARGETS:
            (self.backup / target.name).unlink()
            (self.backup / (target.name + ".absent")).touch()
        for marker in ("table.present", "service.active", "service.enabled"):
            (self.backup / marker).unlink()
        result = self.restore()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.nft("list", "table", "inet", "caddy_gateway", check=False).returncode, 0)
        self.assertEqual(self.nft("list", "table", "inet", "unrelated").returncode, 0)
        self.assertTrue(all(not target.exists() for target in TARGETS))
        self.assertEqual(self.calls(), [
            ["disable", "caddy-gateway-firewall.service"], ["daemon-reload"],
        ])
        self.assertEqual(self.restore().returncode, 0)

    def test_restoration_is_repeatable(self):
        self.assertEqual(self.restore().returncode, 0)
        restored = self.nft("list", "ruleset").stdout
        self.assertEqual(self.restore().returncode, 0)
        self.assertEqual(self.nft("list", "ruleset").stdout, restored)

    def test_restores_snapshot_when_current_table_is_absent(self):
        self.nft("delete", "table", "inet", "caddy_gateway")
        result = self.restore()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tcp dport 4321 drop",
                      self.nft("list", "table", "inet", "caddy_gateway").stdout)


if __name__ == "__main__":
    if os.environ.get("GATEWAY_FIREWALL_TEST_SANDBOX") != "1":
        raise SystemExit("Run sh scripts/test-firewall.sh to isolate rules and system files.")
    unittest.main(verbosity=2)
