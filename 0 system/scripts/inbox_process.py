#!/usr/bin/env python3
import argparse
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path('.').resolve()
TODO = ROOT / '1 todo'
REVIEW = ROOT / '1 review'
RAW = TODO / 'raw'
STATE = ROOT / '0 system' / 'logs' / 'inbox_state.json'
HUBS = ROOT / '3 hubs'

TEXT_EXT = {'.md', '.txt', '.csv', '.json', '.yaml', '.yml', '.xml', '.html'}
IMG_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.gif'}
AUDIO_EXT = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}
VIDEO_EXT = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v'}

INTENT_KEYWORDS = {
    'campaign-idea': {'campaign', 'concept', 'positioning', 'brief', 'launch', 'tagline', 'brand'},
    'research': {'research', 'study', 'report', 'analysis', 'trend', 'insight', 'stat'},
    'copy': {'headline', 'copy', 'script', 'slogan', 'caption', 'tagline'},
    'visual-reference': {'visual', 'design', 'layout', 'poster', 'look', 'style', 'image'},
    'ops': {'process', 'workflow', 'automation', 'system', 'pipeline', 'operation'},
    'transcript': {'transcript', 'speech', 'interview', 'audio', 'voice', 'podcast'},
}

HUB_KEYWORDS = {
    'campaign-ideas': {'campaign', 'concept', 'brand', 'strategy', 'positioning', 'brief', 'insight'},
    'copywriting': {'copy', 'headline', 'tagline', 'script', 'slogan', 'caption'},
    'video-storytelling': {'video', 'film', 'tvc', 'reel', 'storyboard', 'scene'},
    'visual-references': {'visual', 'image', 'photo', 'poster', 'design', 'layout'},
    'research-insights': {'research', 'report', 'data', 'trend', 'analysis', 'insight'},
    'workflow-systems': {'workflow', 'process', 'system', 'automation', 'ops', 'tool'},
    'media-transcripts': {'transcript', 'voice', 'audio', 'podcast', 'interview'},
    'notes-and-docs': {'note', 'document', 'memo', 'doc'},
}

STOPWORDS = {
    'the', 'and', 'for', 'that', 'with', 'this', 'from', 'you', 'your', 'are', 'was', 'were',
    'have', 'has', 'had', 'all', 'into', 'will', 'can', 'not', 'but', 'its', 'out', 'about',
    'what', 'when', 'where', 'why', 'how', 'just', 'they', 'them', 'their', 'our', 'ours',
}


def has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def has_python_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run(cmd):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return p.stdout.strip(), ''
    except subprocess.CalledProcessError as e:
        return '', e.stderr.strip() or str(e)


def read_text_file(path: Path):
    try:
        return path.read_text(encoding='utf-8', errors='replace'), ''
    except Exception as e:
        return '', str(e)


def extract_image_text(path: Path):
    if not has_cmd('tesseract'):
        return '', 'tesseract not installed'
    out, err = run(['tesseract', str(path), 'stdout'])
    return out, err


def resolve_whisper_cmd():
    if has_cmd('whisper'):
        return ['whisper']
    if has_cmd('openai-whisper'):
        return ['openai-whisper']
    if has_python_module('whisper'):
        return [sys.executable, '-m', 'whisper']
    return []


def extract_audio_video_text(path: Path):
    if not has_cmd('ffmpeg'):
        return '', 'ffmpeg not installed'

    whisper_cmd = resolve_whisper_cmd()
    if not whisper_cmd:
        return '', 'whisper not installed (cli or python module)'

    tmp_wav = ROOT / '0 system' / 'logs' / f"tmp_{path.stem}.wav"
    _, err = run(['ffmpeg', '-y', '-i', str(path), '-vn', '-ac', '1', '-ar', '16000', str(tmp_wav)])
    if err:
        return '', f'ffmpeg extraction failed: {err}'

    txt_out, werr = run(
        whisper_cmd + [
            str(tmp_wav),
            '--model',
            'base',
            '--output_format',
            'txt',
            '--output_dir',
            str(ROOT / '0 system' / 'logs'),
        ]
    )
    txt_path = ROOT / '0 system' / 'logs' / f"{tmp_wav.stem}.txt"
    if txt_path.exists():
        text = txt_path.read_text(encoding='utf-8', errors='replace')
        try:
            tmp_wav.unlink(missing_ok=True)
            txt_path.unlink(missing_ok=True)
        except Exception:
            pass
        return text, ''
    return '', f'whisper failed: {werr or txt_out}'


def generic_meta(path: Path):
    st = path.stat()
    mime, _ = mimetypes.guess_type(str(path))
    return {
        'path': str(path.relative_to(ROOT)),
        'size_bytes': st.st_size,
        'modified': datetime.fromtimestamp(st.st_mtime).isoformat(),
        'mime': mime or 'unknown',
    }


def tokenize(text: str):
    tokens = re.findall(r'[a-z0-9]+', text.lower())
    return [tok for tok in tokens if len(tok) > 2 and tok not in STOPWORDS]


def infer_content_type(path: Path):
    ext = path.suffix.lower()
    if ext in IMG_EXT:
        return 'image'
    if ext in AUDIO_EXT:
        return 'audio'
    if ext in VIDEO_EXT:
        return 'video'
    return 'doc'


def infer_language(text: str):
    if re.search(r'[\u4e00-\u9fff]', text):
        return 'zh'
    return 'en'


def summarize_1line(src: Path, extracted_text: str):
    lines = [line.strip() for line in extracted_text.splitlines() if line.strip()]
    if not lines:
        return f'Extracted from {src.name}'
    one = lines[0]
    if len(one) > 140:
        one = one[:137].rstrip() + '...'
    return one


def infer_intent(src: Path, extracted_text: str):
    ext = src.suffix.lower()
    if ext in AUDIO_EXT or ext in VIDEO_EXT:
        return 'transcript'
    if ext in IMG_EXT:
        return 'visual-reference'

    tokens = Counter(tokenize(f"{src.stem}\n{extracted_text[:10000]}"))
    best_intent = 'research'
    best_score = 0
    for intent, kws in INTENT_KEYWORDS.items():
        score = sum(tokens.get(kw, 0) for kw in kws)
        if score > best_score:
            best_score = score
            best_intent = intent

    if best_score == 0:
        return 'ops' if any(k in src.stem.lower() for k in ['workflow', 'process', 'system']) else 'research'
    return best_intent


def extract_entities(text: str, limit: int = 8):
    matches = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b', text)
    entities = []
    seen = set()
    for m in matches:
        clean = m.strip()
        if clean.lower() in STOPWORDS:
            continue
        if clean not in seen:
            seen.add(clean)
            entities.append(clean)
        if len(entities) >= limit:
            break
    return entities


def extract_keywords(src: Path, extracted_text: str, limit: int = 10):
    counts = Counter(tokenize(f"{src.stem}\n{extracted_text[:12000]}"))
    return [token for token, _ in counts.most_common(limit)]


def score_candidate_hubs(src: Path, extracted_text: str, existing_hubs: list[str], top_n: int = 3):
    counts = Counter(tokenize(f"{src.stem}\n{extracted_text[:12000]}"))
    candidates = set(existing_hubs) | set(HUB_KEYWORDS.keys())
    raw_scores = {}
    for name in candidates:
        score = 0
        for tok in tokenize(name.replace('-', ' ')):
            score += counts.get(tok, 0) * 3
        for kw in HUB_KEYWORDS.get(name, set()):
            score += counts.get(kw, 0) * 2
        raw_scores[name] = score

    ranked = sorted(raw_scores.items(), key=lambda x: x[1], reverse=True)
    if not ranked:
        return []

    top = ranked[0][1] or 1
    output = []
    for name, score in ranked[:top_n]:
        conf = min(0.99, score / max(top, 1)) if score > 0 else 0.0
        output.append((name, conf))
    return output


def q(val: str):
    return str(val).replace('"', '\\"')


def reusable_nuggets(extracted_text: str, limit: int = 3):
    lines = [line.strip() for line in extracted_text.splitlines() if line.strip()]
    picks = []
    for line in lines:
        if len(line) < 8:
            continue
        if line in picks:
            continue
        picks.append(line)
        if len(picks) >= limit:
            break
    return picks


def to_review_md(src: Path, digest: str, meta: dict, raw_rel: str, extracted_text: str, warnings: list[str]):
    date = datetime.now().strftime('%Y-%m-%d')
    slug = src.stem.lower().replace(' ', '-').replace('_', '-')
    review_name = f"{date}_review-{slug}.md"
    review_path = REVIEW / review_name

    full_text = (extracted_text or '').strip()
    sample = full_text[:5000]
    warns = '\n'.join(f"- {w}" for w in warnings) if warnings else '- none'

    content_type = infer_content_type(src)
    language = infer_language(full_text)
    summary = summarize_1line(src, full_text)
    intent = infer_intent(src, full_text)
    entities = extract_entities(full_text)
    keywords = extract_keywords(src, full_text)
    existing_hubs = [p.name for p in HUBS.iterdir() if p.is_dir() and not p.name.startswith('.')]
    candidates = score_candidate_hubs(src, full_text, existing_hubs)
    candidate_str = ', '.join(f"{name}:{score:.2f}" for name, score in candidates)
    entities_str = ', '.join(entities)
    keywords_str = ', '.join(keywords)
    nuggets = reusable_nuggets(full_text)
    nugget_lines = '\n'.join(f"- {n}" for n in nuggets) if nuggets else '- (none captured)'

    why_lines = [
        f"- Primary intent detected: `{intent}`",
        f"- Source type: `{content_type}` ({meta['mime']})",
        '- Candidate hubs are pre-scored to speed routing decisions',
    ]
    why_block = '\n'.join(why_lines)

    body = f"""---
id: "REVIEW-AUTO-{digest[:8]}"
topic: "Auto extraction: {q(src.name)}"
project: ""
reviewer: "Kit"
status: "review"
date: "{date}"
source_file: "{q(src.relative_to(ROOT))}"
source_hash: "{digest}"
raw_data: "{q(raw_rel)}"
content_type: "{content_type}"
language: "{language}"
summary_1line: "{q(summary)}"
intent: "{intent}"
client: ""
market: ""
entities: "{q(entities_str)}"
keywords: "{q(keywords_str)}"
candidate_hubs: "{q(candidate_str)}"
routing_decision: ""
routing_confidence: "0.00"
needs_human_review: "true"
---

## File Metadata
- path: `{meta['path']}`
- mime: `{meta['mime']}`
- size_bytes: `{meta['size_bytes']}`
- modified: `{meta['modified']}`

## Why This Matters
{why_block}

## Reusable Nuggets
{nugget_lines}

## Extraction Warnings
{warns}

## Full Extracted Text
```
{sample}
```

## Review Decision
- Approve / Request changes
"""
    review_path.write_text(body, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='Process inbox files from 1 todo into 1 review')
    parser.add_argument('--force', action='store_true', help='Reprocess all files in 1 todo even if hashes are unchanged')
    args = parser.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)

    state = {}
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding='utf-8'))

    files = [p for p in TODO.iterdir() if p.is_file() and not p.name.startswith('.')]
    processed = 0

    for path in sorted(files):
        digest = sha256_file(path)
        prev = state.get(path.name)
        if (not args.force) and prev and prev.get('hash') == digest:
            continue

        ext = path.suffix.lower()
        meta = generic_meta(path)
        text = ''
        warnings = []

        if ext in TEXT_EXT:
            text, err = read_text_file(path)
            if err:
                warnings.append(err)
        elif ext in IMG_EXT:
            text, err = extract_image_text(path)
            if err:
                warnings.append(err)
        elif ext in AUDIO_EXT or ext in VIDEO_EXT:
            text, err = extract_audio_video_text(path)
            if err:
                warnings.append(err)
        else:
            warnings.append('unsupported file type for text extraction; metadata only')

        raw_base = RAW / f"{path.stem}_{digest[:8]}"
        raw_base.mkdir(parents=True, exist_ok=True)
        raw_txt = raw_base / 'raw.txt'
        raw_json = raw_base / 'meta.json'
        raw_txt.write_text(text or '', encoding='utf-8')
        raw_json.write_text(json.dumps(meta, indent=2), encoding='utf-8')

        to_review_md(path, digest, meta, str(raw_base.relative_to(ROOT)), text, warnings)

        state[path.name] = {
            'hash': digest,
            'processed_at': datetime.now().isoformat(),
            'raw_dir': str(raw_base.relative_to(ROOT)),
        }
        processed += 1

    STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    mode = ' (force)' if args.force else ''
    print(f"Processed {processed} file(s){mode}.")


if __name__ == '__main__':
    main()
