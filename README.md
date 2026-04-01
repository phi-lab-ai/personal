# kitOS Personal Workspace

This workspace is organized as an AI production system.

## Flow
Capture -> Build -> Review -> Ship -> Learn -> Reuse

## Structure
- `0 system`: rules, settings, commands, agents, skills, templates, scripts
- `1 todo`: intake and active items
- `1 review`: review drafts + approvals
- `1 archive`: archived reviews + original source artifacts
- `2 team`: ownership, routing, handoffs
- `3 projects`: active projects
- `3 hubs`: reusable knowledge and insights

## Maturity-First Mode (Automation Deferred)
- Automation is blocked until quality gates pass.
- Use local/manual flow to harden functions first.

## Core Commands
- `./0 system/scripts/kit run todo [--force --strict --report]`
- `./0 system/scripts/kit run review --prepare`
- `./0 system/scripts/kit run review --apply`
- `./0 system/scripts/kit validate`
- `./0 system/scripts/kit quality-check`

## Review Gate
1. `run review --prepare` creates routing proposals and approval artifacts in `1 review/approvals/`.
2. Manually set `approved: "true"` in approval files.
3. `run review --apply` applies only approved items and moves outputs to archive/hubs.

## Quality Gate
- Score log: `0 system/logs/maturity_score.json`
- Requires 2 consecutive passes before enabling automation.
