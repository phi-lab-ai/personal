#!/usr/bin/env python3
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path('.').resolve()
REVIEW = ROOT / '1 review'
HUBS = ROOT / '3 hubs'
STATE = ROOT / '0 system' / 'logs' / 'review_state.json'

TEXT_EXT = {'.md', '.txt', '.csv', '.json', '.yaml', '.yml', '.xml', '.html'}
IMG_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.gif'}
AUDIO_EXT = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}
VIDEO_EXT = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v'}

NEW_THEME_MIN_COUNT = 3
EXISTING_SCORE_MIN = 3
TRIAGE_FOLDER = '_triage'

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

INTENT_TO_HUB = {
    'campaign-idea': 'campaign-ideas',
    'research': 'research-insights',
    'copy': 'copywriting',
    'visual-reference': 'visual-references',
    'ops': 'workflow-systems',
    'transcript': 'media-transcripts',
}

STOPWORDS = {
    'the', 'and', 'for', 'that', 'with', 'this', 'from', 'you', 'your', 'are', 'was', 'were',
    'have', 'has', 'had', 'all', 'into', 'will', 'can', 'not', 'but', 'its', 'out', 'about',
    'what', 'when', 'where', 'why', 'how', 'just', 'they', 'them', 'their', 'our', 'ours',
}


def slugify(value: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    return slug or 'untitled'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_frontmatter(text: str):
    if not text.startswith('---\n'):
        return {}, text
    end = text.find('\n---\n', 4)
    if end == -1:
        return {}, text

    fm_text = text[4:end]
    body = text[end + 5 :]
    fm = {}
    for line in fm_text.splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        fm[key.strip()] = value.strip().strip('"')
    return fm, body


def dump_frontmatter(fm: dict, body: str) -> str:
    order = [
        'id',
        'topic',
        'project',
        'reviewer',
        'status',
        'date',
        'source_file',
        'source_hash',
        'raw_data',
        'content_type',
        'language',
        'summary_1line',
        'intent',
        'client',
        'market',
        'entities',
        'keywords',
        'candidate_hubs',
        'routing_decision',
        'routing_confidence',
        'needs_human_review',
        'curated_hub',
        'curated_at',
    ]
    keys = [k for k in order if k in fm] + sorted([k for k in fm if k not in order])
    lines = ['---']
    for key in keys:
        val = str(fm[key]).replace('"', '\\"')
        lines.append(f'{key}: "{val}"')
    lines.append('---')
    return '\n'.join(lines) + '\n' + body


def tokenize(text: str):
    tokens = re.findall(r'[a-z0-9]+', text.lower())
    return [t for t in tokens if len(t) > 2 and t not in STOPWORDS]


def load_text_from_raw(review_meta: dict):
    raw_data = review_meta.get('raw_data', '').strip()
    if not raw_data:
        return ''
    raw_txt = ROOT / raw_data / 'raw.txt'
    if raw_txt.exists():
        return raw_txt.read_text(encoding='utf-8', errors='replace')
    return ''


def extract_text_from_review_body(body: str):
    patterns = [
        r'## Full Extracted Text\s*```(.*?)```',
        r'## Raw Text \(Sample\)\s*```(.*?)```',
    ]
    for p in patterns:
        match = re.search(p, body, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ''


def get_existing_hubs():
    if not HUBS.exists():
        return []
    names = []
    for p in HUBS.iterdir():
        if not p.is_dir():
            continue
        if p.name.startswith('.'):
            continue
        names.append(p.name)
    return sorted(names)


def score_hubs(text: str, hub_names: list[str]):
    tokens = Counter(tokenize(text[:12000]))
    scores = {}
    for name in hub_names:
        score = 0
        for tok in tokenize(name.replace('-', ' ')):
            score += tokens.get(tok, 0) * 3
        for kw in HUB_KEYWORDS.get(name, set()):
            score += tokens.get(kw, 0) * 2
        scores[name] = score
    return scores


def infer_theme_folder(meta: dict, review_text: str):
    intent = meta.get('intent', '').strip().lower()
    if intent in INTENT_TO_HUB:
        return INTENT_TO_HUB[intent]

    keywords = [k.strip() for k in meta.get('keywords', '').split(',') if k.strip()]
    if keywords:
        return slugify('-'.join(keywords[:2]))

    source_name = Path(meta.get('source_file', '')).stem
    if source_name:
        return slugify(source_name)
    return 'misc'


def infer_entry_type(source_ext: str):
    if source_ext in IMG_EXT:
        return 'visual-note'
    if source_ext in AUDIO_EXT or source_ext in VIDEO_EXT:
        return 'transcript'
    if source_ext in TEXT_EXT:
        return 'note'
    return 'reference'


def build_hub_doc(review_file: Path, review_meta: dict, review_text: str, folder_name: str):
    source_file = review_meta.get('source_file', '')
    source_ext = Path(source_file).suffix.lower()
    source_name = Path(source_file).name or review_file.stem
    source_hash = review_meta.get('source_hash', '')
    review_rel = review_file.relative_to(ROOT)
    date_tag = datetime.now().strftime('%Y-%m-%d')
    slug = slugify(Path(source_file).stem or review_file.stem)
    hub_dir = HUBS / folder_name
    hub_dir.mkdir(parents=True, exist_ok=True)

    out_file = hub_dir / f'{date_tag}_{slug}.md'
    if out_file.exists():
        short = source_hash[:8] if source_hash else sha256_file(review_file)[:8]
        out_file = hub_dir / f'{date_tag}_{slug}_{short}.md'

    excerpt = review_text[:20000].strip()
    if not excerpt:
        excerpt = '(No extractable text found; see review source for details.)'

    entry_type = infer_entry_type(source_ext)
    title = source_name
    summary = review_meta.get('summary_1line', '').strip() or f'Auto-curated from {source_name}'
    keywords = review_meta.get('keywords', '').strip()

    content = f"""---
id: HUB-AUTO-{(source_hash or sha256_file(review_file))[:8]}
title: "{title}"
type: "{entry_type}"
domain: "{folder_name}"
summary_1line: "{summary.replace('"', '\\"')}"
keywords: "{keywords.replace('"', '\\"')}"
source_file: "{source_file}"
source_review: "{review_rel}"
source_hash: "{source_hash}"
created_at: "{datetime.now().isoformat()}"
---

# {title}

## Summary
- {summary}

## Source
- Review file: `{review_rel}`
- Original file: `{source_file}`

## Extracted Content
```
{excerpt}
```
"""
    out_file.write_text(content, encoding='utf-8')
    return out_file


def parse_candidate_hubs(raw: str):
    entries = []
    for part in raw.split(','):
        part = part.strip()
        if not part or ':' not in part:
            continue
        name, score = part.split(':', 1)
        try:
            entries.append((name.strip(), float(score.strip())))
        except ValueError:
            continue
    return entries


def main():
    REVIEW.mkdir(parents=True, exist_ok=True)
    HUBS.mkdir(parents=True, exist_ok=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)

    state = {}
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding='utf-8'))

    pending = []
    skipped = 0

    for review_file in sorted(REVIEW.glob('*.md')):
        original = review_file.read_text(encoding='utf-8', errors='replace')
        meta, body = parse_frontmatter(original)
        status = meta.get('status', '').strip().lower()
        if status == 'curated':
            skipped += 1
            continue

        digest = sha256_file(review_file)
        prev = state.get(review_file.name)
        if prev and prev.get('hash') == digest and prev.get('status') == 'curated':
            skipped += 1
            continue

        raw_text = load_text_from_raw(meta)
        combined_text = raw_text.strip() or extract_text_from_review_body(body)

        existing_hubs = [name for name in get_existing_hubs() if name != TRIAGE_FOLDER]
        hub_scores = score_hubs(combined_text, existing_hubs)
        best_existing = ('', 0)
        if hub_scores:
            best_existing = max(hub_scores.items(), key=lambda x: x[1])

        candidate_hubs = parse_candidate_hubs(meta.get('candidate_hubs', ''))
        suggested_new_folder = infer_theme_folder(meta, combined_text)
        if candidate_hubs and candidate_hubs[0][0]:
            suggested_new_folder = slugify(candidate_hubs[0][0])

        pending.append(
            {
                'review_file': review_file,
                'meta': meta,
                'body': body,
                'text': combined_text,
                'digest': digest,
                'best_existing_name': best_existing[0],
                'best_existing_score': best_existing[1],
                'suggested_new_folder': suggested_new_folder,
            }
        )

    low_fit_groups = defaultdict(list)
    for item in pending:
        if item['best_existing_name'] and item['best_existing_score'] >= EXISTING_SCORE_MIN:
            item['route_folder'] = item['best_existing_name']
            item['routing_confidence'] = min(0.99, item['best_existing_score'] / 10)
        else:
            low_fit_groups[item['suggested_new_folder']].append(item)

    for folder_name, items in low_fit_groups.items():
        if len(items) >= NEW_THEME_MIN_COUNT:
            for item in items:
                item['route_folder'] = folder_name
                item['routing_confidence'] = 0.65
        else:
            for item in items:
                item['route_folder'] = TRIAGE_FOLDER
                item['routing_confidence'] = 0.30

    curated = 0
    errors = 0

    for item in pending:
        review_file = item['review_file']
        meta = item['meta']
        body = item['body']
        route_folder = item['route_folder']
        confidence = item['routing_confidence']

        try:
            hub_file = build_hub_doc(review_file, meta, item['text'], route_folder)
            meta['status'] = 'curated'
            meta['routing_decision'] = route_folder
            meta['routing_confidence'] = f'{confidence:.2f}'
            meta['needs_human_review'] = 'false' if route_folder != TRIAGE_FOLDER else 'true'
            meta['curated_hub'] = str(hub_file.relative_to(ROOT))
            meta['curated_at'] = datetime.now().isoformat()
            review_file.write_text(dump_frontmatter(meta, body), encoding='utf-8')

            state[review_file.name] = {
                'hash': sha256_file(review_file),
                'status': 'curated',
                'hub_file': str(hub_file.relative_to(ROOT)),
                'curated_at': datetime.now().isoformat(),
            }
            curated += 1
        except Exception as exc:
            errors += 1
            print(f'ERROR {review_file.name}: {exc}')

    STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    print(f'Curated {curated} file(s), skipped {skipped}, errors {errors}.')


if __name__ == '__main__':
    main()
