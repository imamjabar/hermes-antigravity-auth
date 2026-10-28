"""Regression tests for Hermes v0.22 compatibility."""

import asyncio
import importlib
import importlib.machinery
import shutil
import sys
import tempfile
import types
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, patch

import antigravity_auth.constants as constants
import antigravity_auth.hermes_compat as hermes_compat
import antigravity_auth.hermes_provider_plugin as provider_mod
import antigravity_auth.interceptor as interceptor
from antigravity_auth.cloudcode_client import (
  AntigravityCloudCodeClient,
  AsyncAntigravityCloudCodeClient,
  VIRTUAL_CLOUDCODE_BASE_URL,
)


def _make_fake_modern_modules(
  *,
  create_openai_client=None,
  resolve_runtime_provider=None,
  resolve_provider_client=None,
  to_async_client=None,
  resolve_requested_provider=None,
  get_model_config=None,
):
  agent_runtime_helpers = types.ModuleType("agent.agent_runtime_helpers")
  agent_runtime_helpers.create_openai_client = create_openai_client or (lambda *args, **kwargs: object())

  runtime_provider = types.ModuleType("hermes_cli.runtime_provider")
  runtime_provider.resolve_runtime_provider = resolve_runtime_provider or (lambda **kwargs: {"provider": "original"})
  if resolve_requested_provider is not None:
    runtime_provider.resolve_requested_provider = resolve_requested_provider
  if get_model_config is not None:
    runtime_provider._get_model_config = get_model_config

  auxiliary_client = types.ModuleType("agent.auxiliary_client")
  auxiliary_client.resolve_provider_client = resolve_provider_client or (lambda *args, **kwargs: (None, None))
  if to_async_client is not None:
    auxiliary_client._to_async_client = to_async_client

  native_adapter = types.ModuleType("agent.gemini_native_adapter")
  native_adapter.build_gemini_request = lambda **kwargs: {}
  native_adapter.translate_gemini_response = lambda payload, model: payload
  native_adapter.translate_stream_event = lambda event, model, tool_call_indices: []
  native_adapter._iter_sse_events = lambda response: iter(())
  native_adapter.gemini_http_error = lambda response, body_text="": RuntimeError(body_text)

  fake_agent_pkg = types.ModuleType("agent")
  fake_hermes_cli = types.ModuleType("hermes_cli")

  return {
    "agent": fake_agent_pkg,
    "agent.gemini_cloudcode_adapter": None,
    "agent.agent_runtime_helpers": agent_runtime_helpers,
    "agent.auxiliary_client": auxiliary_client,
    "agent.gemini_native_adapter": native_adapter,
    "hermes_cli": fake_hermes_cli,
    "hermes_cli.runtime_provider": runtime_provider,
  }


class TestHermesV022Compat(unittest.TestCase):
  def setUp(self):
    self._orig_interceptor_state = {
      "_PATCHED": interceptor._PATCHED,
      "_GLOBAL_HTTPX_HOOK_INSTALLED": interceptor._GLOBAL_HTTPX_HOOK_INSTALLED,
      "_ORIGINAL_INIT": interceptor._ORIGINAL_INIT,
      "_ORIGINAL_WRAP_CODE_ASSIST": interceptor._ORIGINAL_WRAP_CODE_ASSIST,
      "_ORIGINAL_ENSURE_PROJECT_CONTEXT": interceptor._ORIGINAL_ENSURE_PROJECT_CONTEXT,
      "_ORIGINAL_CREATE_OPENAI_CLIENT": interceptor._ORIGINAL_CREATE_OPENAI_CLIENT,
      "_ORIGINAL_RESOLVE_RUNTIME_PROVIDER": interceptor._ORIGINAL_RESOLVE_RUNTIME_PROVIDER,
      "_ORIGINAL_RESOLVE_PROVIDER_CLIENT": interceptor._ORIGINAL_RESOLVE_PROVIDER_CLIENT,
      "_ORIGINAL_TO_ASYNC_CLIENT": interceptor._ORIGINAL_TO_ASYNC_CLIENT,
      "_MODERN_RUNTIME_PATCHED": interceptor._MODERN_RUNTIME_PATCHED,
      "_DEFERRED_FINDER": interceptor._DEFERRED_FINDER,
      "_INSTALLING": interceptor._INSTALLING,
    }
    self._reset_interceptor_state()

  def tearDown(self):
    interceptor.uninstall()
    for key, val in self._orig_interceptor_state.items():
      setattr(interceptor, key, val)
    interceptor._remove_deferred_finder()
    sys.meta_path[:] = [
      finder for finder in sys.meta_path
      if not isinstance(finder, interceptor._DeferredInstallFinder)
    ]

  def _reset_interceptor_state(self):
    interceptor._PATCHED = False
    interceptor._GLOBAL_HTTPX_HOOK_INSTALLED = False
    interceptor._ORIGINAL_INIT = None
    interceptor._ORIGINAL_WRAP_CODE_ASSIST = None
    interceptor._ORIGINAL_ENSURE_PROJECT_CONTEXT = None
    interceptor._ORIGINAL_CREATE_OPENAI_CLIENT = None
    interceptor._ORIGINAL_RESOLVE_RUNTIME_PROVIDER = None
    interceptor._ORIGINAL_RESOLVE_PROVIDER_CLIENT = None
    interceptor._ORIGINAL_TO_ASYNC_CLIENT = None
    interceptor._MODERN_RUNTIME_PATCHED = False
    interceptor._DEFERRED_FINDER = None
    interceptor._INSTALLING = False

  def _create_fake_package_tree(self, root: Path):
    (root / "hermes_cli").mkdir(parents=True, exist_ok=True)
    (root / "hermes_cli/__init__.py").write_text("")
    (root / "hermes_cli/runtime_provider.py").write_text("""
def resolve_runtime_provider(**kwargs):
    return {"provider": "original-unpatched"}

def resolve_requested_provider(requested=None):
    return "google-gemini-cli"

def _get_model_config():
    return {"provider": "google-gemini-cli", "default": "gemini-3.8-flash-high"}
""")
    (root / "agent").mkdir(parents=True, exist_ok=True)
    (root / "agent/__init__.py").write_text("")
    (root / "agent/agent_runtime_helpers.py").write_text("""
def create_openai_client(*args, **kwargs):
    return None
""")
    (root / "agent/auxiliary_client.py").write_text("""
def resolve_provider_client(*args, **kwargs):
    return None, None

def _to_async_client(client, model, *args, **kwargs):
    return "original-async-result", model
""")
    (root / "agent/gemini_native_adapter.py").write_text("""
def build_gemini_request(**kwargs):
    return {}

def translate_gemini_response(payload, model):
    return payload

def translate_stream_event(event, model, tool_call_indices):
    return []

def _iter_sse_events(response):
    return iter(())

def gemini_http_error(response, body_text=""):
    return RuntimeError(body_text)
""")

  def test_resolve_runtime_provider_with_no_requested_checks_requested_provider(self):
    orig_resolver = MagicMock(return_value={"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1"})
    resolve_requested = MagicMock(return_value="google-gemini-cli")

    mods = _make_fake_modern_modules(
      resolve_runtime_provider=orig_resolver,
      resolve_requested_provider=resolve_requested,
    )
    with patch.dict(sys.modules, mods), patch("antigravity_auth.interceptor._install_global_httpx_hook"):
      self.assertTrue(interceptor.install())
      rp = mods["hermes_cli.runtime_provider"]

      res = rp.resolve_runtime_provider()
      self.assertEqual(res["provider"], "google-gemini-cli")
      self.assertEqual(res["base_url"], "cloudcode-pa://google")
      self.assertEqual(res["requested_provider"], "google-gemini-cli")
      orig_resolver.assert_not_called()

      resolve_requested.return_value = "openrouter"
      res_fallback = rp.resolve_runtime_provider()
      self.assertEqual(res_fallback["provider"], "openrouter")
      orig_resolver.assert_called_once()

  def test_to_async_client_wraps_cloudcode_client_and_restores_on_uninstall(self):
    original_to_async = MagicMock(return_value=("delegated_async", "delegated_model"))
    mods = _make_fake_modern_modules(to_async_client=original_to_async)

    with patch.dict(sys.modules, mods), patch("antigravity_auth.interceptor._install_global_httpx_hook"):
      self.assertTrue(interceptor.install())
      aux = mods["agent.auxiliary_client"]
      self.assertIsNot(aux._to_async_client, original_to_async)

      sync_client = AntigravityCloudCodeClient(
        api_key="antigravity-oauth",
        base_url=VIRTUAL_CLOUDCODE_BASE_URL,
      )
      wrapped_async = None
      try:
        wrapped_async, model = aux._to_async_client(sync_client, "gemini-3.8-flash-low")
        self.assertIsInstance(wrapped_async, AsyncAntigravityCloudCodeClient)
        self.assertEqual(model, "gemini-3.8-flash-low")
        original_to_async.assert_not_called()
      finally:
        sync_client.close()
        if wrapped_async is not None:
          asyncio.run(wrapped_async.close())

      other_client = object()
      delegated_res, delegated_model = aux._to_async_client(other_client, "other-model")
      self.assertEqual((delegated_res, delegated_model), ("delegated_async", "delegated_model"))
      original_to_async.assert_called_once_with(other_client, "other-model")

      self.assertTrue(interceptor.uninstall())
      self.assertIs(aux._to_async_client, original_to_async)

  def test_aux_default_model_uses_configured_default_or_fallback(self):
    mods = _make_fake_modern_modules()
    with patch.dict(sys.modules, mods), patch("antigravity_auth.interceptor._install_global_httpx_hook"):
      self.assertTrue(interceptor.install())
      aux = mods["agent.auxiliary_client"]
      rp = mods["hermes_cli.runtime_provider"]

      rp._get_model_config = MagicMock(return_value={"provider": "google-gemini-cli", "default": "gemini-3.8-flash-high"})
      client, model = aux.resolve_provider_client("google-gemini-cli")
      self.assertEqual(model, "gemini-3.8-flash-high")
      self.assertIsInstance(client, AntigravityCloudCodeClient)
      client.close()

      rp._get_model_config = MagicMock(return_value={"provider": "openrouter", "default": "anthropic/claude-3-opus"})
      client2, model2 = aux.resolve_provider_client("google-gemini-cli")
      self.assertEqual(model2, constants.ANTIGRAVITY_DEFAULT_AUX_MODEL)
      self.assertIsInstance(client2, AntigravityCloudCodeClient)
      client2.close()

  def test_deferred_install_end_to_end_with_real_import_machinery(self):
    tmp_dir = tempfile.mkdtemp(prefix="test_v022_real_import_")
    modules_to_clean = [
      "hermes_cli",
      "hermes_cli.runtime_provider",
      "hermes_cli.auth",
      "agent",
      "agent.agent_runtime_helpers",
      "agent.auxiliary_client",
      "agent.gemini_native_adapter",
      "agent.gemini_cloudcode_adapter",
    ]
    try:
      self._create_fake_package_tree(Path(tmp_dir))
      sys.path.insert(0, tmp_dir)
      for mod in modules_to_clean:
        sys.modules.pop(mod, None)
      importlib.invalidate_caches()

      fake_auth = types.ModuleType("hermes_cli.auth")
      auth_spec = importlib.machinery.ModuleSpec("hermes_cli.auth", loader=None)
      auth_spec._initializing = True
      fake_auth.__spec__ = auth_spec
      sys.modules["hermes_cli.auth"] = fake_auth

      with patch("antigravity_auth.interceptor._install_global_httpx_hook"):
        status = interceptor.install_when_ready()
        self.assertEqual(status, "deferred")
        self.assertIn(interceptor._DEFERRED_FINDER, sys.meta_path)
        self.assertFalse(interceptor.is_installed())
        self.assertFalse(interceptor._MODERN_RUNTIME_PATCHED)

        importlib.import_module("agent.agent_runtime_helpers")
        self.assertFalse(interceptor.is_installed())
        self.assertFalse(interceptor._MODERN_RUNTIME_PATCHED)
        self.assertIn(interceptor._DEFERRED_FINDER, sys.meta_path)

        auth_spec._initializing = False
        rp = importlib.import_module("hermes_cli.runtime_provider")

        self.assertTrue(interceptor.is_installed())
        self.assertTrue(interceptor._MODERN_RUNTIME_PATCHED)
        self.assertNotIn(interceptor._DEFERRED_FINDER, sys.meta_path)
        runtime = rp.resolve_runtime_provider()
        self.assertEqual(runtime["provider"], "google-gemini-cli")
        self.assertEqual(runtime["base_url"], "cloudcode-pa://google")
    finally:
      if tmp_dir in sys.path:
        sys.path.remove(tmp_dir)
      shutil.rmtree(tmp_dir, ignore_errors=True)
      for mod in modules_to_clean:
        sys.modules.pop(mod, None)
      importlib.invalidate_caches()

  def test_install_when_ready_when_auth_absent_or_ready_installs_immediately(self):
    with patch.dict(sys.modules, {"hermes_cli.auth": None}, clear=False):
      sys.modules.pop("hermes_cli.auth", None)
      with patch("antigravity_auth.interceptor.install", return_value=True) as mock_install:
        self.assertEqual(interceptor.install_when_ready(), "installed")
        mock_install.assert_called_once()
        self.assertIsNone(interceptor._DEFERRED_FINDER)

      with patch("antigravity_auth.interceptor.install", return_value=False) as mock_install:
        self.assertEqual(interceptor.install_when_ready(), "declined")
        mock_install.assert_called_once()
        self.assertIsNone(interceptor._DEFERRED_FINDER)

    fake_auth = types.ModuleType("hermes_cli.auth")
    auth_spec = importlib.machinery.ModuleSpec("hermes_cli.auth", loader=None)
    auth_spec._initializing = False
    fake_auth.__spec__ = auth_spec
    with patch.dict(sys.modules, {"hermes_cli.auth": fake_auth}):
      with patch("antigravity_auth.interceptor.install", return_value=True) as mock_install:
        self.assertEqual(interceptor.install_when_ready(), "installed")
        mock_install.assert_called_once()
        self.assertIsNone(interceptor._DEFERRED_FINDER)

      with patch("antigravity_auth.interceptor.install", return_value=False) as mock_install:
        self.assertEqual(interceptor.install_when_ready(), "declined")
        mock_install.assert_called_once()
        self.assertIsNone(interceptor._DEFERRED_FINDER)

  def test_uninstall_while_deferred_removes_finder_so_install_never_resurrects(self):
    fake_auth = types.ModuleType("hermes_cli.auth")
    auth_spec = importlib.machinery.ModuleSpec("hermes_cli.auth", loader=None)
    auth_spec._initializing = True
    fake_auth.__spec__ = auth_spec
    with patch.dict(sys.modules, {"hermes_cli.auth": fake_auth}):
      self.assertEqual(interceptor.install_when_ready(), "deferred")
      finder = interceptor._DEFERRED_FINDER
      self.assertIn(finder, sys.meta_path)

      self.assertFalse(interceptor.uninstall())

    self.assertNotIn(finder, sys.meta_path)
    self.assertIsNone(interceptor._DEFERRED_FINDER)

  def test_detect_hermes_features_with_initializing_auth_reports_info_and_skips_gaps(self):
    fake_auth = types.ModuleType("hermes_cli.auth")
    auth_spec = importlib.machinery.ModuleSpec("hermes_cli.auth", loader=None)
    auth_spec._initializing = True
    fake_auth.__spec__ = auth_spec

    with patch.dict(sys.modules, {"hermes_cli.auth": fake_auth}), \
         patch("antigravity_auth.hermes_compat.modern_runtime_feature_gaps") as mock_gaps:
      rows = hermes_compat.detect_hermes_features()
      mock_gaps.assert_not_called()
      runtime_rows = [r for r in rows if r.check == "Hermes runtime factory internals"]
      self.assertEqual(len(runtime_rows), 1)
      self.assertEqual(runtime_rows[0].status, "INFO")
      self.assertIn("deferred", runtime_rows[0].detail.lower())

  def test_patch_hermes_model_picker_without_provider_entry_or_grouping_tables(self):
    CustomEntry = namedtuple("CustomEntry", ["slug", "label", "tui_desc"])
    fake_models = types.ModuleType("hermes_cli.models")
    fake_models._PROVIDER_MODELS = {"google-gemini-cli": ["old-model"]}
    fake_models._PROVIDER_LABELS = {"google-gemini-cli": "Google Gemini (OAuth)"}
    fake_models._PROVIDER_ALIASES = {}
    fake_models.CANONICAL_PROVIDERS = [
      CustomEntry("google-gemini-cli", "Google Gemini (OAuth)", "OAuth desc"),
    ]
    models_spec = importlib.machinery.ModuleSpec("hermes_cli.models", loader=None)
    models_spec._initializing = False
    fake_models.__spec__ = models_spec

    fake_hermes_cli = types.ModuleType("hermes_cli")
    fake_hermes_cli.models = fake_models

    original_diagnostics = list(provider_mod._PROVIDER_DIAGNOSTICS)
    provider_mod._PROVIDER_DIAGNOSTICS.clear()
    try:
      with patch.dict(sys.modules, {
        "hermes_cli": fake_hermes_cli,
        "hermes_cli.models": fake_models,
      }), \
      patch.object(provider_mod, "_set_oauth_env_from_credentials"), \
      patch("threading.Thread") as mock_thread:
        provider_mod._patch_hermes_model_picker()

        mock_thread.assert_not_called()
        self.assertEqual(
          fake_models._PROVIDER_MODELS["google-gemini-cli"],
          list(provider_mod.ANTIGRAVITY_MODELS),
        )
        canonical = fake_models.CANONICAL_PROVIDERS[0]
        self.assertEqual(canonical.slug, "google-gemini-cli")
        self.assertEqual(canonical.label, "Google Antigravity")
        self.assertIs(type(canonical), CustomEntry)

        diagnostics = provider_mod.get_provider_diagnostics()
        picker_diags = [d for d in diagnostics if d["check"] == "model picker patch"]
        self.assertTrue(any(d["status"] == "PASS" for d in picker_diags))
    finally:
      provider_mod._PROVIDER_DIAGNOSTICS[:] = original_diagnostics

  def test_install_with_registered_deferred_finder_avoids_double_patch_recursion(self):
    tmp_dir = tempfile.mkdtemp(prefix="test_v022_recursion_")
    modules_to_clean = [
      "hermes_cli",
      "hermes_cli.runtime_provider",
      "hermes_cli.auth",
      "agent",
      "agent.agent_runtime_helpers",
      "agent.auxiliary_client",
      "agent.gemini_native_adapter",
      "agent.gemini_cloudcode_adapter",
    ]
    try:
      self._create_fake_package_tree(Path(tmp_dir))
      sys.path.insert(0, tmp_dir)
      for mod in modules_to_clean:
        sys.modules.pop(mod, None)
      importlib.invalidate_caches()

      fake_auth = types.ModuleType("hermes_cli.auth")
      auth_spec = importlib.machinery.ModuleSpec("hermes_cli.auth", loader=None)
      auth_spec._initializing = False
      fake_auth.__spec__ = auth_spec
      sys.modules["hermes_cli.auth"] = fake_auth

      finder = interceptor._DeferredInstallFinder()
      interceptor._DEFERRED_FINDER = finder
      sys.meta_path.insert(0, finder)

      with patch("antigravity_auth.interceptor._install_global_httpx_hook"):
        self.assertTrue(interceptor.install())

      import agent.auxiliary_client as aux
      import hermes_cli.runtime_provider as rp

      self.assertEqual(interceptor._ORIGINAL_TO_ASYNC_CLIENT.__name__, "_to_async_client")
      self.assertNotEqual(interceptor._ORIGINAL_TO_ASYNC_CLIENT.__name__, "_patched_to_async_client")
      self.assertEqual(interceptor._ORIGINAL_RESOLVE_RUNTIME_PROVIDER.__name__, "resolve_runtime_provider")
      self.assertNotEqual(interceptor._ORIGINAL_RESOLVE_RUNTIME_PROVIDER.__name__, "_patched_resolve_runtime_provider")
      self.assertEqual(interceptor._ORIGINAL_RESOLVE_PROVIDER_CLIENT.__name__, "resolve_provider_client")
      self.assertNotEqual(interceptor._ORIGINAL_RESOLVE_PROVIDER_CLIENT.__name__, "_patched_resolve_provider_client")

      async_res = aux._to_async_client(object(), "m")
      self.assertEqual(async_res, ("original-async-result", "m"))

      runtime_res = rp.resolve_runtime_provider(requested="openrouter")
      self.assertEqual(runtime_res, {"provider": "original-unpatched"})
    finally:
      if tmp_dir in sys.path:
        sys.path.remove(tmp_dir)
      shutil.rmtree(tmp_dir, ignore_errors=True)
      for mod in modules_to_clean:
        sys.modules.pop(mod, None)
      importlib.invalidate_caches()

  def test_deferred_install_waits_for_outer_runtime_module_when_nested_import_occurs(self):
    tmp_dir = tempfile.mkdtemp(prefix="test_v022_nested_")
    modules_to_clean = [
      "hermes_cli",
      "hermes_cli.runtime_provider",
      "hermes_cli.auth",
      "agent",
      "agent.agent_runtime_helpers",
      "agent.auxiliary_client",
      "agent.gemini_native_adapter",
      "agent.gemini_cloudcode_adapter",
    ]
    try:
      self._create_fake_package_tree(Path(tmp_dir))
      (Path(tmp_dir) / "agent/auxiliary_client.py").write_text("""
import agent.agent_runtime_helpers

def resolve_provider_client(*args, **kwargs):
    return None, None

def _to_async_client(client, model, *args, **kwargs):
    return "original-async-result", model
""")
      sys.path.insert(0, tmp_dir)
      for mod in modules_to_clean:
        sys.modules.pop(mod, None)
      importlib.invalidate_caches()

      fake_auth = types.ModuleType("hermes_cli.auth")
      auth_spec = importlib.machinery.ModuleSpec("hermes_cli.auth", loader=None)
      auth_spec._initializing = False
      fake_auth.__spec__ = auth_spec
      sys.modules["hermes_cli.auth"] = fake_auth

      finder = interceptor._DeferredInstallFinder()
      interceptor._DEFERRED_FINDER = finder
      sys.meta_path.insert(0, finder)

      with patch("antigravity_auth.interceptor._install_global_httpx_hook"):
        aux = importlib.import_module("agent.auxiliary_client")

      self.assertTrue(interceptor.is_installed())
      self.assertTrue(interceptor._MODERN_RUNTIME_PATCHED)
      self.assertEqual(aux.resolve_provider_client.__name__, "_patched_resolve_provider_client")
      self.assertEqual(aux._to_async_client.__name__, "_patched_to_async_client")
    finally:
      if tmp_dir in sys.path:
        sys.path.remove(tmp_dir)
      shutil.rmtree(tmp_dir, ignore_errors=True)
      for mod in modules_to_clean:
        sys.modules.pop(mod, None)
      importlib.invalidate_caches()


if __name__ == "__main__":
  unittest.main()
