import subprocess
import tempfile
import unittest
from pathlib import Path

from muse_tmr.app import AppConfig, create_local_app_server
from muse_tmr.app.auto_update import AutoUpdater, current_build, pull_if_behind


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class PullIfBehindTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.origin = root / "origin.git"
        git(root, "init", "--bare", "-b", "main", str(self.origin))
        self.upstream = root / "upstream"
        git(root, "clone", "-q", str(self.origin), str(self.upstream))
        git(self.upstream, "checkout", "-q", "-b", "main")
        (self.upstream / "app.txt").write_text("v1\n")
        git(self.upstream, "add", "app.txt")
        git(self.upstream, "commit", "-q", "-m", "v1")
        git(self.upstream, "push", "-q", "origin", "main")
        self.checkout = root / "checkout"
        git(root, "clone", "-q", str(self.origin), str(self.checkout))

    def tearDown(self):
        self._tmp.cleanup()

    def push_new_commit(self):
        (self.upstream / "app.txt").write_text("v2\n")
        git(self.upstream, "commit", "-q", "-am", "v2")
        git(self.upstream, "push", "-q", "origin", "main")
        return git(self.upstream, "rev-parse", "--short", "HEAD")

    def test_fast_forwards_clean_main(self):
        new_build = self.push_new_commit()

        self.assertEqual(pull_if_behind(self.checkout), new_build)
        self.assertEqual(current_build(self.checkout), new_build)
        self.assertEqual((self.checkout / "app.txt").read_text(), "v2\n")

    def test_up_to_date_returns_none(self):
        self.assertIsNone(pull_if_behind(self.checkout))

    def test_untracked_files_do_not_block(self):
        new_build = self.push_new_commit()
        (self.checkout / "notes.sh").write_text("local\n")

        self.assertEqual(pull_if_behind(self.checkout), new_build)

    def test_leaves_tracked_changes_alone(self):
        self.push_new_commit()
        (self.checkout / "app.txt").write_text("my edit\n")

        self.assertIsNone(pull_if_behind(self.checkout))
        self.assertEqual((self.checkout / "app.txt").read_text(), "my edit\n")

    def test_leaves_other_branches_alone(self):
        self.push_new_commit()
        git(self.checkout, "checkout", "-q", "-b", "feature/x")

        self.assertIsNone(pull_if_behind(self.checkout))
        self.assertEqual((self.checkout / "app.txt").read_text(), "v1\n")

    def test_local_main_ahead_of_origin_is_not_an_update(self):
        (self.checkout / "local.txt").write_text("x\n")
        git(self.checkout, "add", "local.txt")
        git(self.checkout, "commit", "-q", "-m", "local")
        before = current_build(self.checkout)

        self.assertIsNone(pull_if_behind(self.checkout))
        self.assertEqual(current_build(self.checkout), before)

    def test_diverged_main_is_not_merged(self):
        self.push_new_commit()
        (self.checkout / "local.txt").write_text("x\n")
        git(self.checkout, "add", "local.txt")
        git(self.checkout, "commit", "-q", "-m", "local")
        before = current_build(self.checkout)

        self.assertIsNone(pull_if_behind(self.checkout))
        self.assertEqual(current_build(self.checkout), before)


class AutoUpdaterTest(unittest.TestCase):
    def make(self, idle_values, pull_result="abc1234"):
        self.idle_values = list(idle_values)
        self.pulls = 0
        self.restarts = 0

        def pull(_root):
            self.pulls += 1
            return pull_result

        def restart():
            self.restarts += 1

        return AutoUpdater(
            Path("."),
            is_idle=lambda: self.idle_values.pop(0),
            restart=restart,
            pull=pull,
        )

    def test_busy_app_does_not_pull(self):
        updater = self.make([False])
        self.assertFalse(updater.check_once())
        self.assertEqual((self.pulls, self.restarts), (0, 0))

    def test_idle_app_pulls_and_restarts(self):
        updater = self.make([True, True])
        self.assertTrue(updater.check_once())
        self.assertEqual((self.pulls, self.restarts), (1, 1))

    def test_nothing_new_does_not_restart(self):
        updater = self.make([True], pull_result=None)
        self.assertFalse(updater.check_once())
        self.assertEqual((self.pulls, self.restarts), (1, 0))

    def test_restart_waits_until_idle_again_without_pulling_twice(self):
        # Pulled, but the user connected the headband meanwhile.
        updater = self.make([True, False, False, True, True])
        self.assertFalse(updater.check_once())
        self.assertFalse(updater.check_once())
        self.assertTrue(updater.check_once())
        self.assertEqual((self.pulls, self.restarts), (1, 1))


class IdleForUpdateTest(unittest.TestCase):
    def test_fresh_app_is_idle_and_connected_app_is_not(self):
        server = create_local_app_server(AppConfig(port=0, source="mock"), build="abc1234")
        self.addCleanup(server.server_close)
        self.addCleanup(server.app_state.shutdown)
        state = server.app_state

        self.assertTrue(state.idle_for_update())
        self.assertEqual(state.ui_state()["build"], "abc1234")
        state.connect()
        self.assertFalse(state.idle_for_update())
        state.disconnect()
        self.assertTrue(state.idle_for_update())


if __name__ == "__main__":
    unittest.main()
