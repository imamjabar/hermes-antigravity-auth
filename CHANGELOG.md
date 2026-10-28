# Changelog

All notable changes to hermes-antigravity-auth.

## [1.9.0] — 2026-10-28

Hermes Agent v0.22 compatibility. Verified live on Hermes v0.22.5 (gateway,
WhatsApp, CLI fast launch, `hermes -z`, Gemini 3.8 and Claude Sonnet 4.6,
tool calls, title generation and compression).

### Added
- Gemini 3.7/3.8 Flash models in the provider catalog (upstream PR #16).
- `hermes-antigravity-install` supports PM-managed Hermes (v0.22+): it vendors
  the package into `~/.hermes/plugins/antigravity-cli/` with a `pyproject.toml`
  and re-admits the plugin so `hermes update` keeps it.

### Fixed
- Default config chat (`model.provider: google-gemini-cli`) fell back to
  OpenRouter: Hermes v0.22 calls `resolve_runtime_provider()` without
  `requested`; the runtime patch now reads `model.provider` the same way Hermes does.
- CLI fast launch resolved the runtime before plugin discovery, so the patch was
  never active: Hermes v0.22 imports provider plugins while `hermes_cli.auth` is
  still initializing. The interceptor now defers its install to an import hook
  that fires right after Hermes' runtime modules finish importing.
- Async auxiliary calls (compression, vision) failed with "Connection error":
  Hermes v0.22 rebuilt the Antigravity client as a plain `AsyncOpenAI` on the
  virtual `cloudcode-pa://` URL. `_to_async_client` now wraps it in
  `AsyncAntigravityCloudCodeClient`.
- "Too little data for declared Content-Length" after request rewrites
  (upstream PR #13).
- Auxiliary tasks defaulted to `gemini-3.5-flash`, which now returns HTTP 404;
  they use the configured model, else `gemini-3.8-flash-low`.
- Doctor no longer reports bogus circular-import / missing `ProviderEntry` /
  grouping-table warnings on Hermes v0.22; the model picker patch works without
  `ProviderEntry` and grouping tables.

## [1.8.0] — 2026-08-21

### Added
- Single-source packaging metadata via `antigravity_auth/_version.py`.
- Runtime hardening for Antigravity auth diagnostics and wrapper drift detection.
- Clean-install pipeline with source-archive smoke test in CI.
- Selftest smoke command for offline verification.

### Changed
- Enforced canonical Hermes install path and tightened auth diagnostics.
- Hardened quota check state handling.
- Diagnosed installed antigravity wrappers for version drift.

### Fixed
- Hardened Antigravity auth runtime safety.
- Hardened Hermes v0.18 Antigravity routing.

## [1.7.0] — 2026-05-31

### Added
- Package build guard rejects local `antigravity_auth/_credentials.py` so wheels/sdists cannot accidentally include private OAuth client credentials.
- Safe OAuth credential resolver supports environment variables and external `~/.hermes/antigravity-credentials.json` without relying on package-tree secrets.
- Account-manager helper resolves the request-selected account by safe index for response-hook bookkeeping.
- Process file locks serialize account-store writes and `auth.json` read-modify-write updates across Hermes processes.
- Test suite mocks bundled credentials fallback so tests pass reliably in CI checkouts.

### Changed
- GitHub Actions CI now uses Node 24-capable `actions/checkout@v6` and `actions/setup-python@v6`.
- Response hooks apply 403/429 handling to the request-selected account rather than whichever account is current later.
- 429 handling uses reason-aware backoff data from Cloud Code error responses.
- Runtime request headers reuse stored per-account Antigravity fingerprints instead of generating random selected-account fallback headers.
- Provider wrapper installs the interceptor best-effort/idempotently.
- Streaming SSE behavior is documented and tested as passthrough for Hermes' native Cloud Code parser.

### Fixed
- Request authorization now fails closed when account selection cannot provide a token, preventing stale bearer reuse.
- Managed runtime refreshes persist `invalid_grant` cleanup and avoid resurrecting revoked accounts from stale managers.
- Anthropic-style content-array `tool_use` / `tool_result` IDs are preserved during message transforms.
- Nullable JSON Schema fields no longer get removed from `required` solely because they allow `null`.
- Debug logs are written with private permissions and redact additional token/key shapes.
- Existing YAML config files now warn visibly when PyYAML is unavailable.

## [1.6.0] — 2026-05-21

### Added
- 403 handling: shadow-banned/ineligible accounts placed on 24h cooldown with auto-rotation
- Rate limit marking for both header styles (antigravity + gemini-cli) on 429 responses
- Account quota cache: soft threshold rotation before hard rate limits
- `token_watchdog.py`: background daemon for proactive access token refresh

### Changed
- Interceptor rewritten as headers-only httpx event hooks (removed broken `_HttpProxy`)
- Endpoint routing defaults to PROD — daily sandbox rejects free-tier Claude accounts
- Gemini CLI header style only uses PROD endpoint (sandbox endpoints skipped)
- `transform/__init__.py` explicitly exports all submodule symbols

### Fixed
- Account rotation actually skips exhausted accounts (both header styles marked)
- Token refresh persists refreshed tokens to both auth.json and google_oauth.json stores

## [1.5.0] — 2026-05-20

### Added
- Multi-account management with health-score-based rotation
- Dual quota pool tracking (Antigravity + Gemini CLI)
- Device fingerprint generation per account
- `antigravity login`, `antigravity accounts`, `antigravity check` CLI commands
- Hermes provider profile with Antigravity branding in `/model` picker
- Google Search tool registration (`google_antigravity_search`)
- Session recovery: tool_result_missing, thinking_block_order detection

### Changed
- Python port from TypeScript: complete rewrite as pip-installable package
- Stdlib-only (urllib, json, dataclasses) — no heavy framework dependencies

## [1.0.0] — 2026-05-19

### Added
- Initial release: port of opencode-antigravity-auth (NoeFabris)
- PKCE OAuth 2.0 flow for Google Antigravity
- Request/response transformation pipeline (messages, schema, envelope, thinking)
- Claude thinking block stripping and signature handling
- JSON Schema sanitization for Antigravity API compatibility
