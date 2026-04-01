# Trigger Words (Quick Actions)

Use these trigger words to run useful actions quickly.

| Trigger Word | Action | What It Does |
|---|---|---|
| `run todo` | Process inbox to review | Reads all files in `1 todo`, extracts text/transcripts, and writes review markdown to `1 review`. |
| `run todo --force` | Rebuild inbox extraction | Reprocesses all files in `1 todo` and refreshes corresponding review markdown. |
| `run review` | Curate review to hubs | Reads all markdown in `1 review`, infers relevant folders in `3 hubs`, creates missing folders, and writes curated notes. |
| `kickoff` | Create project scaffold | Creates a new project folder from template under `3 projects/`. |
| `capture` | Create task | Adds a new task card into `1 todo`. |
| `next` | Show next task | Shows the highest-priority pending task to work on. |
| `review` | Send to review | Moves a task from `1 todo` to `1 review`. |
| `archive` | Close task/project | Moves completed item into `1 archive`. |
| `digest` | Weekly snapshot | Prints quick counts for todo/review/archive/projects. |
| `insight` | Process inbox | Scans `1 todo`, extracts raw data, and exports review markdowns to `1 review`. |
| `backup` | Backup state | Creates a dated backup of key dashboard/system files. |
| `cleanup` | Hygiene audit | Finds stale tasks, broken links, and orphan files. |

## Suggested Usage
- Keep this list open while working.
- Start with: `capture` -> `next` -> `review` -> `archive`.
