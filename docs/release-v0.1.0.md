# Release 0.1.0

Post-publication verification: all 29 unit/HTTP tests pass in a fresh GitHub clone, but
the live-test file lacks its final newline and fails the formatting gate. Version 0.1.1
corrects only that formatting issue and release metadata. Use v0.1.1 for installation;
the original v0.1.0 tag is preserved. There is no runtime or contract change.

## Compatibility

- API contract: `1`; runtime: Python 3.10 or newer, standard library only.
- Install the complete `skills/adx-analysis` directory from tag `v0.1.0`.
- Configure `ADX_QUERY_API_URL` in the consumer environment, not in source control.
- The API is operated separately; this repository neither deploys it nor supplies credentials.

## Included

- Six read-only operational metrics endpoints with validated UTC windows and exact filters.
- Exact count strings, response window/provenance checks and overview comparison checks.
- Bounded response size, no redirects or ambient proxy, sanitized network/protocol errors.
- Analysis instructions distinguish records, affected resources, cumulative I/O and mapping quality.

## Verification

- 23 synthetic unit tests pass, including malformed responses and interrupted reads.
- Ruff lint/format and strict mypy pass.
- Six opt-in HTTP endpoint tests pass against a separately operated real API.
- Independent review findings are resolved; follow-up review finds no release blocker.
- Live tests are disabled by default and require operator-supplied configuration.

```bash
uv sync --locked
uv run pytest -q
uv run ruff check skills tests
uv run ruff format --check skills tests
uv run mypy skills/adx-analysis/scripts
```

## Installation And Rollback

Fetch the release tag, record `git rev-parse HEAD`, then install the complete skill directory.
Keep the previously installed version before updating. To roll back, restore that directory
and verify API contract compatibility. Version 0.1.0 is the initial release, not evidence of
an already-tested prior-version rollback.

QM registration and network access from its execution environment remain separate acceptance
steps. A GitHub release does not imply installation in any agent platform. No license grant is
added by this release; public visibility alone is not an open-source license.
