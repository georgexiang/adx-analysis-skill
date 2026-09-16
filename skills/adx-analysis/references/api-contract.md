# API Contract 1

All routes are read-only GET requests under `/api/v1/`. Configure the server base URL
through `ADX_QUERY_API_URL`; the client appends the route. HTTP is intended only for a
trusted private network or loopback. Use HTTPS across untrusted networks.

| Endpoint | Result |
| --- | --- |
| overview | Current rows, previous equal-length window, record change percentages |
| vm-health/trend | Time bucket, impact dimension, record and affected VM counts |
| vm-health/reasons | Top N reason counts |
| disk-blips/trend | Time bucket, cumulative I/O counts, per-record I/O percentiles |
| disk-blips/rca | Top N level1/level2/level3 RCA combinations |
| data-quality | All-time mapping metrics and window-scoped name-only coverage |

Required: `from`, `to`, explicit UTC, `[from,to)`, maximum 30 days. Common optional filters:
`region`, `az`, `vm`. Only health endpoints accept `rg`, `impact`. Only trends accept
`bin` (`1h`, `6h`, `1d`); only rankings accept `top` (1 to 50, default 10).
Filters are exact, single-valued, nonempty strings. Unspecified filters mean all values.

Success: `data.rows` plus `meta` containing contract version, generated time, query window,
per-source freshness and cache status. Counts are decimal strings. Undefined metrics are null.
Overview additionally includes `data.previous`; a zero prior count makes percent change null.
Ranking results omit categories beyond Top N; they do not include a residual Other bucket.
Trend buckets are ADX UTC-aligned; the first bucket can start before `from`, but its counts
include only records inside the selected window. Missing buckets are absent, not fabricated.

Errors: 422 invalid input, 429 capacity, 502 query/partial failure, 503 unavailable service,
504 timeout. Only complete successful responses are cached; failures never become zero metrics.
The client follows no redirects, uses no ambient proxy, sends no cookies or Azure credentials,
and limits response size to 2 MiB. A service requiring interactive authentication is not supported.
