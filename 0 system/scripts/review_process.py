#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path('.').resolve()
REVIEW = ROOT / '1 review'
REVIEW_ORIGINALS = REVIEW / 'originals'
APPROVALS = REVIEW / 'approvals'
HUBS = ROOT / '3 hubs'
ARCHIVE = ROOT / '1 archive'
ARCHIVE_ORIGINALS = ARCHIVE / 'originals'
ARCHIVE_REVIEWS = ARCHIVE / 'reviews'
STATE = ROOT / '0 system' / 'logs' / 'review_state.json'
AUDIT_LOG = ROOT / '0 system' / 'logs' / 'routing_audit.jsonl'

TEXT_EXT = {'.md', '.txt', '.csv', '.json', '.yaml', '.yml', '.xml', '.html'}
IMG_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.gif'}
AUDIO_EXT = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.aiff'}
VIDEO_EXT = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v'}

AUTO_ROUTE_THRESHOLD = 0.80
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
    keys = list(fm.keys())
    lines = ['---']
    for key in keys:
        val = str(fm[key]).replace('"', '\\"')
        lines.append(f'{key}: "{val}"')
    lines.append('---')
    return '\n'.join(lines) + '\n' + body


def to_bool(value: str) -> bool:
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y'}


def tokenize(text: str):
    tokens = re.findall(r'[a-z0-9]+', text.lower())
    return [t for t in tokens if len(t) > 2 and t not in STOPWORDS]


def clamp01(value, default=0.5):
    try:
        v = float(value)
        return max(0.0, min(0.99, v))
    except Exception:
        return default


def split_semicolon(value: str):
    return [x.strip() for x in value.split(';') if x.strip()]


def parse_scored_hubs(raw: str):
    entries = []
    for part in raw.split(','):
        part = part.strip()
        if not part or ':' not in part:
            continue
        name, score = part.split(':', 1)
        try:
            s = float(score.strip())
        except Exception:
            s = 0.0
        if name.strip():
            entries.append((name.strip(), max(0.0, min(0.99, s))))

    dedup = {}
    for name, score in entries:
        dedup[name] = max(score, dedup.get(name, 0.0))
    return sorted(dedup.items(), key=lambda x: x[1], reverse=True)


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
        if p.is_dir() and not p.name.startswith('.'):
            names.append(p.name)
    return sorted(names)


def score_hubs_rule(text: str, hub_names: list[str]):
    tokens = Counter(tokenize(text[:12000]))
    scores = {}
    for name in hub_names:
        score = 0
        for tok in tokenize(name.replace('-', ' ')):
            score += tokens.get(tok, 0) * 3
        for kw in HUB_KEYWORDS.get(name, set()):
            score += tokens.get(kw, 0) * 2
        scores[name] = score

    if not scores:
        return []
    max_score = max(scores.values()) or 1
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(name, min(0.99, score / max_score)) for name, score in ranked]


def infer_theme_folder(meta: dict):
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


def unique_destination(dest_dir: Path, filename: str) -> Path:
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    i = 1
    while True:
        candidate = dest_dir / f'{stem}_{i}{suffix}'
        if not candidate.exists():
            return candidate
        i += 1


def append_audit(record: dict):
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def build_hub_doc(review_file: Path, review_meta: dict, review_text: str, folder_name: str):
    source_file = review_meta.get('source_file', '')
    source_ext = Path(source_file).suffix.lower()
    source_name = Path(source_file).name or review_file.stem
    source_hash = review_meta.get('source_hash', '')
    review_rel = review_meta.get('archived_review', '').strip() or str(review_file.relative_to(ROOT))
    date_tag = datetime.now().strftime('%Y-%m-%d')
    slug = slugify(Path(source_file).stem or review_file.stem)
    hub_dir = HUBS / folder_name
    hub_dir.mkdir(parents=True, exist_ok=True)

    out_file = hub_dir / f'{date_tag}_{slug}.md'
    if out_file.exists():
        short = source_hash[:8] if source_hash else sha256_file(review_file)[:8]
        out_file = hub_dir / f'{date_tag}_{slug}_{short}.md'

    excerpt = review_text[:20000].strip() or '(No extractable text found; see review source for details.)'
    entry_type = infer_entry_type(source_ext)
    summary = review_meta.get('llm_summary', '').strip() or review_meta.get('summary_1line', '').strip()
    primary_use_case = review_meta.get('primary_use_case', '').strip()
    immediate_actions = split_semicolon(review_meta.get('immediate_actions', ''))
    reusable_assets = split_semicolon(review_meta.get('reusable_assets', ''))
    routing_reason = review_meta.get('routing_reason', '').strip()

    action_lines = '\n'.join(f'- {a}' for a in immediate_actions[:3]) or '- (add manually)'
    reusable_lines = '\n'.join(f'- {r}' for r in reusable_assets[:5]) or '- (none captured)'

    content = f"""---
id: HUB-AUTO-{(source_hash or sha256_file(review_file))[:8]}
title: \"{source_name.replace('"', '\\"')}\"
type: \"{entry_type}\"
domain: \"{folder_name}\"
summary_1line: \"{summary.replace('"', '\\"')}\"
primary_use_case: \"{primary_use_case.replace('"', '\\"')}\"
source_file: \"{source_file}\"
source_review: \"{review_rel}\"
source_hash: \"{source_hash}\"
created_at: \"{datetime.now().isoformat()}\"
---

# {source_name}

## Summary
- {summary or 'Auto-curated review artifact.'}

## How To Use
- {primary_use_case or 'Use as a reference and adaptation input for active work.'}

## Immediate Actions
{action_lines}

## Reusable Assets
{reusable_lines}

## Routing Rationale
- {routing_reason or 'Manual-reviewed route selected from proposals.'}

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


def build_approval_file(review_file: Path, meta: dict, proposed_route: str, final_conf: float, method: str):
    APPROVALS.mkdir(parents=True, exist_ok=True)
    approval = APPROVALS / f'{review_file.stem}.md'
    default = {
        'approval_id': f'APPROVAL-{sha256_file(review_file)[:8]}',
        'review_file': str(review_file.relative_to(ROOT)),
        'source_file': meta.get('source_file', ''),
        'source_hash': meta.get('source_hash', ''),
        'proposed_route': proposed_route,
        'proposed_confidence': f'{final_conf:.2f}',
        'proposed_method': method,
        'approved': 'false',
        'approved_route': '',
        'reviewer': '',
        'reviewed_at': '',
        'notes': '',
        'applied': 'false',
        'applied_at': '',
    }

    if approval.exists():
        old_fm, _ = parse_frontmatter(approval.read_text(encoding='utf-8', errors='replace'))
        if old_fm:
            default.update(old_fm)
            default['proposed_route'] = proposed_route
            default['proposed_confidence'] = f'{final_conf:.2f}'
            default['proposed_method'] = method

    lines = ['---']
    for key, value in default.items():
        lines.append(f'{key}: "{str(value).replace("\"", "\\\"")}"')
    lines.append('---')
    body = (
        '## Manual Review\n'
        '- Set `approved: "true"` to allow apply mode.\n'
        '- Optional: set `approved_route` to override proposed route.\n'
        '- Optional: add reviewer and notes.\n'
    )
    approval.write_text('\n'.join(lines) + '\n' + body, encoding='utf-8')


def prepare_mode(state: dict):
    REVIEW.mkdir(parents=True, exist_ok=True)
    APPROVALS.mkdir(parents=True, exist_ok=True)
    HUBS.mkdir(parents=True, exist_ok=True)

    prepared = 0
    skipped = 0

    for review_file in sorted(REVIEW.glob('*.md')):
        text = review_file.read_text(encoding='utf-8', errors='replace')
        meta, body = parse_frontmatter(text)
        if not meta:
            skipped += 1
            continue

        status = meta.get('status', '').strip().lower()
        if status in {'archived', 'curated'}:
            skipped += 1
            continue
        if status == 'blocked':
            skipped += 1
            continue

        raw_text = load_text_from_raw(meta)
        combined_text = raw_text.strip() or extract_text_from_review_body(body)

        existing_hubs = [name for name in get_existing_hubs() if name != TRIAGE_FOLDER]
        semantic = parse_scored_hubs(meta.get('candidate_hubs_semantic', ''))
        rule = parse_scored_hubs(meta.get('candidate_hubs', ''))
        if not rule:
            rule = score_hubs_rule(combined_text, existing_hubs)[:3]

        best_sem_name, best_sem_score = semantic[0] if semantic else ('', 0.0)
        best_rule_name, best_rule_score = rule[0] if rule else ('', 0.0)

        if best_sem_score >= best_rule_score and best_sem_name:
            selected_name, selected_score, method = best_sem_name, best_sem_score, 'semantic'
        elif best_rule_name:
            selected_name, selected_score, method = best_rule_name, best_rule_score, 'rule'
        else:
            selected_name = INTENT_TO_HUB.get(meta.get('intent', '').strip().lower(), '')
            selected_score = 0.45 if selected_name else 0.0
            method = 'intent-fallback'

        understanding = clamp01(meta.get('understanding_confidence'), 0.55)
        application = clamp01(meta.get('application_confidence'), 0.55)
        actionability = clamp01(meta.get('actionability_score'), 0.50)
        final_conf = min(0.99, selected_score * 0.55 + understanding * 0.2 + application * 0.2 + actionability * 0.05)

        suggested = infer_theme_folder(meta)
        if selected_name and selected_name in existing_hubs and final_conf >= AUTO_ROUTE_THRESHOLD:
            proposed_route = selected_name
        elif selected_name:
            proposed_route = slugify(selected_name)
        else:
            proposed_route = suggested or TRIAGE_FOLDER

        if not proposed_route:
            proposed_route = TRIAGE_FOLDER

        rationale = meta.get('routing_reason', '').strip()
        if rationale:
            rationale += ' '
        rationale += (
            f'PROPOSAL route={proposed_route}; method={method}; '
            f'selected={selected_name or "none"}; confidence={final_conf:.2f}.'
        )

        meta['status'] = 'review_draft'
        meta['routing_decision'] = proposed_route
        meta['routing_confidence'] = f'{final_conf:.2f}'
        meta['routing_method'] = f'hybrid-{method}'
        meta['routing_reason'] = rationale
        meta['needs_human_review'] = 'true'
        meta['human_override'] = 'false'
        meta['override_reason'] = ''
        meta['prepared_at'] = datetime.now().isoformat()

        review_file.write_text(dump_frontmatter(meta, body), encoding='utf-8')
        build_approval_file(review_file, meta, proposed_route, final_conf, method)

        state[review_file.name] = {
            'hash': sha256_file(review_file),
            'status': 'review_draft',
            'proposed_route': proposed_route,
            'prepared_at': datetime.now().isoformat(),
        }
        prepared += 1

    print(f'Prepared {prepared} review proposal(s), skipped {skipped}.')


def apply_mode(state: dict):
    APPROVALS.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    ARCHIVE_ORIGINALS.mkdir(parents=True, exist_ok=True)
    ARCHIVE_REVIEWS.mkdir(parents=True, exist_ok=True)
    HUBS.mkdir(parents=True, exist_ok=True)

    approvals = sorted(APPROVALS.glob('*.md'))
    applied = 0
    skipped = 0
    errors = 0

    for approval_file in approvals:
        approval_text = approval_file.read_text(encoding='utf-8', errors='replace')
        approval_fm, approval_body = parse_frontmatter(approval_text)
        if not approval_fm:
            skipped += 1
            continue
        if not to_bool(approval_fm.get('approved', 'false')):
            skipped += 1
            continue
        if to_bool(approval_fm.get('applied', 'false')):
            skipped += 1
            continue

        review_rel = approval_fm.get('review_file', '').strip()
        if not review_rel:
            errors += 1
            print(f'ERROR approval missing review_file: {approval_file.name}')
            continue

        review_file = ROOT / review_rel
        if not review_file.exists():
            errors += 1
            print(f'ERROR review file not found: {review_rel}')
            continue

        try:
            original = review_file.read_text(encoding='utf-8', errors='replace')
            meta, body = parse_frontmatter(original)
            if not meta:
                raise RuntimeError('invalid review frontmatter')

            proposed_route = approval_fm.get('proposed_route', '').strip()
            approved_route = approval_fm.get('approved_route', '').strip() or proposed_route
            route_folder = approved_route or meta.get('routing_decision', '').strip() or TRIAGE_FOLDER
            reviewer = approval_fm.get('reviewer', '').strip()

            meta['status'] = 'review_approved'
            meta['routing_decision'] = route_folder
            if route_folder != proposed_route and proposed_route:
                meta['human_override'] = 'true'
                if approval_fm.get('notes', '').strip():
                    meta['override_reason'] = approval_fm.get('notes', '').strip()

            archived_source = ''
            source_path = ROOT / meta.get('source_file', '')
            if source_path.exists() and source_path.is_file():
                archived_source_path = unique_destination(ARCHIVE_ORIGINALS, source_path.name)
                source_path.rename(archived_source_path)
                archived_source = str(archived_source_path.relative_to(ROOT))
                meta['source_file'] = archived_source

            review_archive_path = unique_destination(ARCHIVE_REVIEWS, review_file.name)
            meta['archived_source'] = archived_source
            meta['archived_review'] = str(review_archive_path.relative_to(ROOT))

            rationale = meta.get('routing_reason', '').strip()
            if rationale:
                rationale += ' '
            rationale += (
                f'APPLIED route={route_folder}; reviewer={reviewer or "manual"}; '
                f'proposed={proposed_route or "none"}; approved={approved_route or "none"}.'
            )
            meta['routing_reason'] = rationale

            raw_text = load_text_from_raw(meta)
            combined_text = raw_text.strip() or extract_text_from_review_body(body)
            hub_file = build_hub_doc(review_file, meta, combined_text, route_folder)

            meta['status'] = 'archived'
            meta['needs_human_review'] = 'false'
            meta['curated_hub'] = str(hub_file.relative_to(ROOT))
            meta['curated_at'] = datetime.now().isoformat()
            meta['routing_confidence'] = meta.get('routing_confidence', '0.00')

            review_file.write_text(dump_frontmatter(meta, body), encoding='utf-8')
            review_file.rename(review_archive_path)

            state[review_archive_path.name] = {
                'hash': sha256_file(review_archive_path),
                'status': 'archived',
                'hub_file': str(hub_file.relative_to(ROOT)),
                'archived_review': str(review_archive_path.relative_to(ROOT)),
                'archived_source': archived_source,
                'curated_at': datetime.now().isoformat(),
                'routing_method': meta.get('routing_method', ''),
                'routing_confidence': meta.get('routing_confidence', '0.00'),
            }

            append_audit(
                {
                    'timestamp': datetime.now().isoformat(),
                    'mode': 'apply',
                    'approval_file': str(approval_file.relative_to(ROOT)),
                    'review_file': str(review_archive_path.relative_to(ROOT)),
                    'source_file': meta.get('source_file', ''),
                    'routing_decision': route_folder,
                    'routing_confidence': float(meta.get('routing_confidence', '0.00')),
                    'routing_method': meta.get('routing_method', ''),
                    'human_override': to_bool(meta.get('human_override', 'false')),
                    'reviewer': reviewer,
                }
            )

            approval_fm['applied'] = 'true'
            approval_fm['applied_at'] = datetime.now().isoformat()
            approval_fm['reviewed_at'] = approval_fm.get('reviewed_at', '') or datetime.now().isoformat()
            approval_lines = ['---']
            for key, value in approval_fm.items():
                approval_lines.append(f'{key}: "{str(value).replace("\"", "\\\"")}"')
            approval_lines.append('---')
            approval_file.write_text('\n'.join(approval_lines) + '\n' + approval_body, encoding='utf-8')

            applied += 1
        except Exception as exc:
            errors += 1
            print(f'ERROR {approval_file.name}: {exc}')

    print(f'Applied {applied} approved review(s), skipped {skipped}, errors {errors}.')


def main():
    parser = argparse.ArgumentParser(description='Review curation with manual approval gate')
    parser.add_argument('--prepare', action='store_true', help='Generate routing proposals and approval artifacts only')
    parser.add_argument('--apply', action='store_true', help='Apply approved routing decisions and archive files')
    args = parser.parse_args()

    if args.prepare and args.apply:
        print('Choose one mode: --prepare or --apply')
        raise SystemExit(1)

    if not args.prepare and not args.apply:
        args.prepare = True

    STATE.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding='utf-8'))
        except Exception:
            state = {}

    if args.prepare:
        prepare_mode(state)
    elif args.apply:
        apply_mode(state)

    STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
