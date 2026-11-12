# dashboards

Grafana dashboards for Claude's telemetry, provisioned from files by the
telemetry stack, which mounts this folder from the checkout at `$CLAUDE_CHECKOUT`.
Change the JSON here, never in the Grafana UI.

They expect these data sources, by uid:

| uid | Type | Reads |
|---|---|---|
| `victoriametrics` | `victoriametrics-metrics-datasource` | Claude Code's OTel metrics |
| `claude-sqlite` | `frser-sqlite-datasource` | `metrics.db` from `bin/metrics-db`, read-only |
