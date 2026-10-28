import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from antigravity_auth.install_plugins import (
  is_pm_managed_hermes,
  main,
  readmit_plugins,
  vendor_package_into_plugin,
)
from antigravity_auth.package_info import __version__


class TestInstallPluginsPM(unittest.TestCase):
  def setUp(self):
    self.temp_dir = tempfile.TemporaryDirectory()
    self.home = Path(self.temp_dir.name)

  def tearDown(self):
    self.temp_dir.cleanup()

  def test_is_pm_managed_hermes_detection_true_and_false(self):
    self.assertFalse(is_pm_managed_hermes(self.home))

    installs_dir = self.home / "installs"
    installs_dir.mkdir(parents=True)
    self.assertFalse(is_pm_managed_hermes(self.home))

    (installs_dir / "facts.json").write_text("{}", encoding="utf-8")
    self.assertFalse(is_pm_managed_hermes(self.home))

    empty_install = installs_dir / "empty-install"
    empty_install.mkdir()
    self.assertFalse(is_pm_managed_hermes(self.home))

    facts_dir = empty_install / "facts.json"
    facts_dir.mkdir()
    self.assertFalse(is_pm_managed_hermes(self.home))
    facts_dir.rmdir()

    active_install = installs_dir / "active-install-123"
    active_install.mkdir()
    (active_install / "facts.json").write_text("{}", encoding="utf-8")
    self.assertTrue(is_pm_managed_hermes(self.home))

  def test_vendored_tree_contains_interceptor_and_no_pycache(self):
    plugin_dir = vendor_package_into_plugin(self.home)
    self.assertEqual(plugin_dir, self.home / "plugins" / "antigravity-cli")

    vendored_pkg = plugin_dir / "antigravity_auth"
    self.assertTrue((vendored_pkg / "interceptor.py").is_file())
    self.assertTrue((vendored_pkg / "install_plugins.py").is_file())

    pycache_dirs = [p for p in vendored_pkg.rglob("__pycache__") if p.is_dir()]
    self.assertEqual(pycache_dirs, [])

    pyc_files = list(vendored_pkg.rglob("*.pyc"))
    self.assertEqual(pyc_files, [])

    hidden_dot_underscore = [p for p in vendored_pkg.rglob("._*")]
    self.assertEqual(hidden_dot_underscore, [])

  def test_vendor_writes_pyproject_toml_with_build_system_and_version(self):
    vendor_package_into_plugin(self.home)
    pyproject_path = self.home / "plugins" / "antigravity-cli" / "pyproject.toml"
    self.assertTrue(pyproject_path.is_file())

    content = pyproject_path.read_text(encoding="utf-8")
    self.assertIn("[build-system]", content)
    self.assertIn('requires = ["hatchling"]', content)
    self.assertIn('build-backend = "hatchling.build"', content)
    self.assertIn(f'version = "{__version__}"', content)
    self.assertIn('antigravity-cli = "antigravity_auth.hermes_plugin"', content)
    self.assertIn('packages = ["antigravity_auth"]', content)

  def test_re_vendoring_replaces_stale_files_when_file_removed_from_source(self):
    mock_src = self.home / "mock_src"
    mock_src.mkdir(parents=True)
    (mock_src / "__init__.py").write_text("# init", encoding="utf-8")
    (mock_src / "alpha.py").write_text("print('alpha')", encoding="utf-8")
    (mock_src / "beta.py").write_text("print('beta')", encoding="utf-8")
    pycache = mock_src / "__pycache__"
    pycache.mkdir()
    (pycache / "alpha.cpython-310.pyc").write_bytes(b"cache")

    vendor_package_into_plugin(self.home, package_dir=mock_src)
    vendored_target = self.home / "plugins" / "antigravity-cli" / "antigravity_auth"
    self.assertTrue((vendored_target / "alpha.py").is_file())
    self.assertTrue((vendored_target / "beta.py").is_file())
    self.assertFalse((vendored_target / "__pycache__").exists())

    (mock_src / "beta.py").unlink()
    (mock_src / "gamma.py").write_text("print('gamma')", encoding="utf-8")

    vendor_package_into_plugin(self.home, package_dir=mock_src)
    self.assertTrue((vendored_target / "alpha.py").is_file())
    self.assertTrue((vendored_target / "gamma.py").is_file())
    self.assertFalse((vendored_target / "beta.py").exists())

  def test_re_vendoring_replaces_stale_file_in_existing_target(self):
    vendor_package_into_plugin(self.home)
    vendored_target = self.home / "plugins" / "antigravity-cli" / "antigravity_auth"
    stale_file = vendored_target / "stale_local_residue.py"
    stale_file.write_text("stale", encoding="utf-8")
    self.assertTrue(stale_file.exists())

    vendor_package_into_plugin(self.home)
    self.assertFalse(stale_file.exists())
    self.assertTrue((vendored_target / "interceptor.py").is_file())

  def test_readmit_plugins_disables_then_enables_both_plugins(self):
    launcher = Path("/test/bin/hermes")
    with patch("antigravity_auth.install_plugins.subprocess.run") as mock_run:
      readmit_plugins(launcher)

    self.assertEqual(
      mock_run.call_args_list,
      [
        call([str(launcher), "plugins", "disable", "antigravity-cli"], check=False),
        call([str(launcher), "plugins", "enable", "antigravity-cli"], check=True),
        call([str(launcher), "plugins", "enable", "model-providers/antigravity"], check=True),
      ],
    )

  def test_main_pm_mode_vendors_readmits_and_skips_pip(self):
    install_dir = self.home / "installs" / "inst-1"
    install_dir.mkdir(parents=True)
    (install_dir / "facts.json").write_text("{}", encoding="utf-8")

    launcher = self.home / "bin" / "hermes"
    launcher.parent.mkdir(parents=True)
    launcher.touch()

    stdout_capture = io.StringIO()
    with patch("antigravity_auth.install_plugins.subprocess.run") as mock_run, patch(
      "antigravity_auth.install_plugins.resolve_hermes_python",
    ) as mock_resolve_python, patch(
      "antigravity_auth.install_plugins.install_package_in_hermes_python",
    ) as mock_pip, contextlib.redirect_stdout(stdout_capture):
      main(["--home", str(self.home), "--hermes-bin", str(launcher)])

    mock_resolve_python.assert_not_called()
    mock_pip.assert_not_called()

    self.assertEqual(
      mock_run.call_args_list,
      [
        call([str(launcher), "plugins", "disable", "antigravity-cli"], check=False),
        call([str(launcher), "plugins", "enable", "antigravity-cli"], check=True),
        call([str(launcher), "plugins", "enable", "model-providers/antigravity"], check=True),
      ],
    )

    cli_dir = self.home / "plugins" / "antigravity-cli"
    provider_dir = self.home / "plugins" / "model-providers" / "antigravity"
    self.assertTrue((cli_dir / "__init__.py").is_file())
    self.assertTrue((cli_dir / "plugin.yaml").is_file())
    self.assertTrue((cli_dir / "pyproject.toml").is_file())
    self.assertTrue((cli_dir / "antigravity_auth" / "interceptor.py").is_file())
    self.assertTrue((provider_dir / "__init__.py").is_file())
    self.assertTrue((provider_dir / "plugin.yaml").is_file())

    output = stdout_capture.getvalue()
    self.assertIn(f"Installed {cli_dir}", output)
    self.assertIn(f"Installed {provider_dir}", output)
    self.assertIn(
      f"Vendored package into {cli_dir} (Hermes PM rebuilds it on every update)",
      output,
    )
    self.assertIn(f"Re-admitted Antigravity plugins via {launcher}", output)

  def test_main_non_pm_mode_invokes_pip_path(self):
    launcher = self.home / "bin" / "hermes"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    python_bin = self.home / "venv" / "bin" / "python3"

    stdout_capture = io.StringIO()
    with patch(
      "antigravity_auth.install_plugins.resolve_hermes_python",
      return_value=python_bin,
    ) as mock_resolve_python, patch(
      "antigravity_auth.install_plugins.install_package_in_hermes_python",
      return_value=True,
    ) as mock_pip, patch(
      "antigravity_auth.install_plugins.subprocess.run",
    ) as mock_run, contextlib.redirect_stdout(stdout_capture):
      main(["--home", str(self.home), "--hermes-bin", str(launcher)])

    mock_resolve_python.assert_called_once_with(str(launcher))
    mock_pip.assert_called_once_with(python_bin, None)
    mock_run.assert_not_called()

    cli_dir = self.home / "plugins" / "antigravity-cli"
    provider_dir = self.home / "plugins" / "model-providers" / "antigravity"
    self.assertTrue((cli_dir / "__init__.py").is_file())
    self.assertFalse((cli_dir / "pyproject.toml").exists())
    self.assertFalse((cli_dir / "antigravity_auth").exists())

    output = stdout_capture.getvalue()
    self.assertIn(f"Installed package in Hermes Python: {python_bin}", output)
    self.assertIn(f"Installed {cli_dir}", output)
    self.assertIn(f"Installed {provider_dir}", output)
