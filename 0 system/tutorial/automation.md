# Automation Quickstart

## Local-only command launcher
Run from workspace root only:

```bash
./0\ system/scripts/kit <trigger> [args]
```

## Triggers
- `kickoff <slug>`: create a project
- `capture <title>`: create a todo task
- `run todo`: process all files in `1 todo` into review markdown in `1 review`
- `run todo --force`: reprocess all files in `1 todo` even if already processed
- `run review`: curate all review markdown in `1 review` into folders under `3 hubs`
- `next`: show next task
- `review <filename.md>`: move task to review
- `archive <filename.md>`: move review file to archive
- `digest`: weekly counts
- `insight`: process all files in `1 todo` and generate review markdown
- `backup`: backup key workspace folders
- `cleanup`: stale/orphan audit
- `watch [seconds]`: continuously process inbox

## Inbox automation behavior
When `run todo`, `insight`, or `watch` runs:
1. Scan all files in `1 todo`
2. Extract raw text/data
3. Save raw outputs under `1 todo/raw/...`
4. Export review-ready markdown into `1 review`
5. Track processed hashes in `0 system/logs/inbox_state.json`
6. If `--force` is used, ignore hash cache and rebuild all review outputs

## Review curation behavior
When `run review` runs:
1. Scan markdown review files in `1 review`
2. Read frontmatter + extracted content
3. Infer a relevant hub folder under `3 hubs`
4. Create the folder if it does not exist
5. Write curated markdown into that hub folder
6. Mark the review file as `status: curated`

## Media extraction dependencies
- Images OCR: `tesseract`
- Audio/video transcription: `ffmpeg` + `whisper` CLI

Without dependencies, metadata is still captured and review files are generated with warnings.
