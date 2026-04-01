# Commands

- `run todo` -> `./0 system/scripts/kit run todo`
- `run todo --force` -> reprocess all files currently in `1 todo`
- `run todo --strict` -> fail if any review card is blocked by schema requirements
- `run todo --report` -> print ingestion report location
- `run review --prepare` -> generate route proposals and manual approval files
- `run review --apply` -> apply only manually approved review decisions
- `kit validate` -> validate schema contracts and required log presence
- `kit quality-check` -> evaluate maturity thresholds and update `maturity_score.json`

## Maturity Gate Notes
- `watch` remains disabled until quality gate passes for 2 consecutive runs.
- Use `1 review/approvals/*.md` to approve or override proposed routes.
