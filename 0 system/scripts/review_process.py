#!/usr/bin/env python3
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(".").resolve()
REVIEW = ROOT / "1 review"
HUBS = ROOT / "3 hubs"
STATE = ROOT / "0 system" / "logs" / "review_state.json"

TEXT_EXT = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".xml", ".html"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

KEYWORD_FOLDERS = {
    "campaign-ideas": {
        "campaign",
        "concept",
        "brand",
        "strategy",
        "positioning",
        "brief",
        "insight",
    },
    "copywriting": {"copy", "headline", "tagline", "script", "slogan", "line"},
    "video-storytelling": {"video", "film", "tvc", "reel", "storyboard", "scene"},
    "visual-references": {"visual", "image", "photo", "poster", "design", "layout"},
    "research-insights": {"research", "report", "data", "trend", "analysis"},
    "workflow-systems": {"workflow", "process", "system", "automation", "ops", "tool"},
    "media-transcripts": {"transcript", "voice", "audio", "podcast", "interview"},
    "notes-and-docs": {"note", "document", "memo"},
}

STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "with",
    "this",
    "from",
    "you",
    "your",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "all",
    "into",
    "will",
    "can",
    "not",
    "but",
    "its",
    "out",
    "about",
    "what",
    "when",
    "where",
    "why",
    "how",
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_frontmatter(text: str):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text

    fm_text = text[4:end]
    body = text[end + 5 :]
    fm = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fm[key.strip()] = value.strip().strip('"')
    return fm, body


def dump_frontmatter(fm: dict, body: str) -> str:
    order = [
        "id",
        "topic",
        "project",
        "reviewer",
        "status",
        "date",
        "source_file",
        "source_hash",
        "raw_data",
        "curated_hub",
        "curated_at",
    ]
    keys = [k for k in order if k in fm] + sorted([k for k in fm if k not in order])
    lines = ["---"]
    for key in keys:
        val = str(fm[key]).replace('"', '\\"')
        lines.append(f'{key}: "{val}"')
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def tokenize(text: str):
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if len(t) > 2 and t not in STOPWORDS]


def load_text_from_raw(review_meta: dict):
    raw_data = review_meta.get("raw_data", "").strip()
    if not raw_data:
        return ""
    raw_txt = ROOT / raw_data / "raw.txt"
    if raw_txt.exists():
        return raw_txt.read_text(encoding="utf-8", errors="replace")
    return ""


def extract_text_from_review_body(body: str):
    pattern = re.compile(r"## Raw Text \(Sample\)\s*```(.*?)```", re.DOTALL | re.IGNORECASE)
    match = pattern.search(body)
    if match:
        return match.group(1).strip()
    return ""


def infer_folder(review_meta: dict, review_text: str):
    source_file = review_meta.get("source_file", "")
    source_ext = Path(source_file).suffix.lower()
    source_name = Path(source_file).stem
    text = f"{source_name}\n{review_text[:10000]}"
    tokens = tokenize(text)
    counts = Counter(tokens)

    existing = [p.name for p in HUBS.iterdir() if p.is_dir() and not p.name.startswith(".")]
    candidate_names = set(existing) | set(KEYWORD_FOLDERS.keys())
    scores = {name: 0 for name in candidate_names}

    for name in candidate_names:
        folder_tokens = tokenize(name.replace("-", " "))
        for tok in folder_tokens:
            scores[name] += counts.get(tok, 0) * 3
        for kw in KEYWORD_FOLDERS.get(name, set()):
            scores[name] += counts.get(kw, 0) * 2

    if candidate_names:
        best = max(candidate_names, key=lambda n: scores.get(n, 0))
        if scores.get(best, 0) > 0:
            return best

    if source_ext in IMG_EXT:
        return "visual-references"
    if source_ext in AUDIO_EXT or source_ext in VIDEO_EXT:
        return "media-transcripts"
    if source_ext in TEXT_EXT:
        return "notes-and-docs"
    return "misc"


def infer_entry_type(source_ext: str):
    if source_ext in IMG_EXT:
        return "visual-note"
    if source_ext in AUDIO_EXT or source_ext in VIDEO_EXT:
        return "transcript"
    if source_ext in TEXT_EXT:
        return "note"
    return "reference"


def build_hub_doc(review_file: Path, review_meta: dict, review_text: str, folder_name: str):
    source_file = review_meta.get("source_file", "")
    source_ext = Path(source_file).suffix.lower()
    source_name = Path(source_file).name or review_file.stem
    source_hash = review_meta.get("source_hash", "")
    review_rel = review_file.relative_to(ROOT)
    date_tag = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(Path(source_file).stem or review_file.stem)
    hub_dir = HUBS / folder_name
    hub_dir.mkdir(parents=True, exist_ok=True)

    out_file = hub_dir / f"{date_tag}_{slug}.md"
    if out_file.exists():
        short = source_hash[:8] if source_hash else sha256_file(review_file)[:8]
        out_file = hub_dir / f"{date_tag}_{slug}_{short}.md"

    excerpt = review_text[:20000].strip()
    if not excerpt:
        excerpt = "(No extractable text found; see review source for details.)"

    entry_type = infer_entry_type(source_ext)
    title = source_name
    content = f"""---
id: HUB-AUTO-{(source_hash or sha256_file(review_file))[:8]}
title: "{title}"
type: "{entry_type}"
domain: "{folder_name}"
source_file: "{source_file}"
source_review: "{review_rel}"
source_hash: "{source_hash}"
created_at: "{datetime.now().isoformat()}"
---

# {title}

## Summary
- Auto-curated from `1 review` using `run review`.

## Source
- Review file: `{review_rel}`
- Original file: `{source_file}`

## Extracted Content
```
{excerpt}
```
"""
    out_file.write_text(content, encoding="utf-8")
    return out_file


def main():
    REVIEW.mkdir(parents=True, exist_ok=True)
    HUBS.mkdir(parents=True, exist_ok=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)

    state = {}
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding="utf-8"))

    curated = 0
    skipped = 0
    errors = 0

    for review_file in sorted(REVIEW.glob("*.md")):
        try:
            original = review_file.read_text(encoding="utf-8", errors="replace")
            meta, body = parse_frontmatter(original)
            status = meta.get("status", "").strip().lower()
            if status == "curated":
                skipped += 1
                continue

            digest = sha256_file(review_file)
            prev = state.get(review_file.name)
            if prev and prev.get("hash") == digest and prev.get("status") == "curated":
                skipped += 1
                continue

            raw_text = load_text_from_raw(meta)
            combined_text = raw_text.strip() or extract_text_from_review_body(body)
            folder = infer_folder(meta, combined_text)
            hub_file = build_hub_doc(review_file, meta, combined_text, folder)

            meta["status"] = "curated"
            meta["curated_hub"] = str(hub_file.relative_to(ROOT))
            meta["curated_at"] = datetime.now().isoformat()
            review_file.write_text(dump_frontmatter(meta, body), encoding="utf-8")

            state[review_file.name] = {
                "hash": sha256_file(review_file),
                "status": "curated",
                "hub_file": str(hub_file.relative_to(ROOT)),
                "curated_at": datetime.now().isoformat(),
            }
            curated += 1
        except Exception as exc:
            errors += 1
            print(f"ERROR {review_file.name}: {exc}")

    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"Curated {curated} file(s), skipped {skipped}, errors {errors}.")


if __name__ == "__main__":
    main()
