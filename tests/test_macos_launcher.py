import importlib.util
import plistlib
import stat
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = REPO_ROOT / "scripts" / "install_macos_launcher.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("install_macos_launcher", INSTALLER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class MacosLauncherTest(unittest.TestCase):
    def test_create_launcher_app_writes_executable_bundle(self):
        installer = load_installer()
        original_install_icon = installer._install_icon
        installer._install_icon = lambda resources: False
        try:
            with tempfile.TemporaryDirectory() as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                target = temp_dir / "Muse TMR Setup.app"
                repo_root = temp_dir / "repo"
                repo_root.mkdir()

                installer.create_launcher_app(
                    target=target,
                    app_name="Muse TMR Setup",
                    repo_root=repo_root,
                    source="mock",
                    address="",
                    host="127.0.0.1",
                    port=8765,
                )

                info = plistlib.loads((target / "Contents" / "Info.plist").read_bytes())
                self.assertEqual(info["CFBundleName"], "Muse TMR Setup")
                self.assertEqual(info["CFBundleExecutable"], "launch")
                self.assertNotIn("CFBundleIconFile", info)

                launcher = target / "Contents" / "MacOS" / "launch"
                runner = target / "Contents" / "Resources" / "run-local-app.command"
                self.assertTrue(launcher.stat().st_mode & stat.S_IXUSR)
                self.assertTrue(runner.stat().st_mode & stat.S_IXUSR)

                launcher_text = launcher.read_text(encoding="utf-8")
                runner_text = runner.read_text(encoding="utf-8")
                self.assertIn('RUNNER="$SCRIPT_DIR/../Resources/run-local-app.command"', launcher_text)
                self.assertIn("--source mock", runner_text)
                self.assertNotIn("--address", runner_text)
        finally:
            installer._install_icon = original_install_icon

    def test_amused_launcher_bakes_optional_address(self):
        installer = load_installer()
        original_install_icon = installer._install_icon
        installer._install_icon = lambda resources: True
        try:
            with tempfile.TemporaryDirectory() as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                target = temp_dir / "Muse TMR Setup.app"
                repo_root = temp_dir / "repo"
                repo_root.mkdir()

                installer.create_launcher_app(
                    target=target,
                    app_name="Muse TMR Setup",
                    repo_root=repo_root,
                    source="amused",
                    address="2C48FFC8-A1C5-BDFD-A5A4-EEA280A7BBA6",
                    host="127.0.0.1",
                    port=8765,
                )

                info = plistlib.loads((target / "Contents" / "Info.plist").read_bytes())
                self.assertEqual(info["CFBundleIconFile"], "muse-tmr")
                runner_text = (
                    target / "Contents" / "Resources" / "run-local-app.command"
                ).read_text(encoding="utf-8")
                self.assertIn("--source amused", runner_text)
                self.assertIn("--address 2C48FFC8-A1C5-BDFD-A5A4-EEA280A7BBA6", runner_text)
        finally:
            installer._install_icon = original_install_icon


if __name__ == "__main__":
    unittest.main()
