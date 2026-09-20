# ADX Analysis Skill

A portable skill for investigating VM health, disk I/O events and mapping quality through
a read-only metrics API. It is independent of QM and contains no KQL or Azure credentials.

## Install

Get a tagged release of this repository and install the complete `skills/adx-analysis`
directory into your agent's supported skill location. Python 3.10+ is the only runtime dependency.
Configure `ADX_QUERY_API_URL` for an API implementing the bundled contract reference.
The endpoint is supplied by your operator; this repository does not host the API.

```bash
export ADX_QUERY_API_URL=http://127.0.0.1:8080
python3 skills/adx-analysis/scripts/query.py vm-health/reasons \
  --from 2026-01-01T00:00:00Z --to 2026-01-02T00:00:00Z --top 10
```

The URL and dates above are examples. No data is bundled. Inspect returned freshness before
interpreting results. See [the skill](skills/adx-analysis/SKILL.md) for analysis rules.

## Authenticated APIs

Version 0.1.2 supports an optional `ADX_QUERY_API_CREDENTIAL_FILE` environment variable.
The operator provisions a JSON object with `api_url` (the exact HTTPS base URL, no trailing
slash) and `token` (43-128 base64url characters). Use a regular file owned by the execution
user with mode `0600`, no symlinks in its path, and a restricted directory outside source
control and published assets. Only the file path belongs in environment configuration.
The client sends a Bearer header only to that bound service, rejects redirects, and ignores
ambient HTTP proxies. Without the variable, existing private unauthenticated callers remain
compatible. Never put credentials in CLI arguments, browser code, prompts or logs.

For rotation, the operator first enables old and new server credentials, atomically replaces
the protected client file, verifies queries, and then retires the old server credential.
HTTP 401/403 requires operator action; the client never falls back to anonymous access.

## Development

```bash
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy skills/adx-analysis/scripts
```

Tests use synthetic responses and require neither Azure nor QM. Release versions are independent
of the API; version 0.1.2 requires API contract 1.

## QM Registration

After publishing to GitHub, use the target QM version's supported GitHub skill import mechanism.
Select this repository and `skills/adx-analysis`, record the release tag and resolved commit,
and configure the API URL in the execution environment. Verify network access from that environment.
Registration is a separate operation; publishing this repository does not install it in QM.
If the importer cannot pin a version, verify its resolved commit and reproducible rollback before use.

Fixes are developed and tested here, published as a new version, then re-registered by consumers.
Do not maintain a divergent edited copy inside an agent platform.
