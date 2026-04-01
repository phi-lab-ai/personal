#!/usr/bin/env python3
import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path('.').resolve()
TODO = ROOT / '1 todo'
REVIEW = ROOT / '1 review'
REVIEW_ORIGINALS = REVIEW / 'originals'
RAW = TODO / 'raw'
STATE = ROOT / '0 system' / 'logs' / 'inbox_state.json'
INGEST_REPORT = ROOT / '0 system' / 'logs' / 'ingestion_report.jsonl'
SETTINGS = ROOT / '0 system' / 'settings' / 'system.yaml'
HUBS = ROOT / '3 hubs'

TEXT_EXT = {'.md', '.txt', '.csv', '.json', '.yaml', '.yml', '.xml', '.html'}
IMG_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.gif'}
AUDIO_EXT = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.aiff'}
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

INTENT_PLAYBOOK = {
    'campaign-idea': {
        'primary': 'Turn this into a campaign territory with one-line proposition and 3 execution routes.',
        'secondary': [
            'Extract a social-first angle and test headline variants.',
            'Convert into a creative brief starter for next sprint.',
        ],
        'actions': [
            'Draft Safe / Strong / Swing concept directions.',
            'Write one provocative thesis and one proof path.',
            'Map this idea to one active client brief.',
        ],
    },
    'research': {
        'primary': 'Convert this into a concise strategic insight card with implication for action.',
        'secondary': [
            'Pull 3 evidence-backed talking points for deck usage.',
            'Create a risk/opportunity summary for planning.',
        ],
        'actions': [
            'Extract 3 strongest data-backed claims.',
            'Write one recommendation and one risk.',
            'Link to relevant hub/project context.',
        ],
    },
    'copy': {
        'primary': 'Use this as copy inspiration to generate fresh lines in brand voice.',
        'secondary': [
            'Build a headline bank and CTA variants.',
            'Adapt copy into short-form social scripts.',
        ],
        'actions': [
            'Generate 10 headline options.',
            'Write 3 CTA lines for different funnel stages.',
            'Pick top 2 lines for A/B testing.',
        ],
    },
    'visual-reference': {
        'primary': 'Turn this into a visual direction reference with style notes and adaptation cues.',
        'secondary': [
            'Extract art-direction principles for next concept board.',
            'Generate image prompt variants for fast prototyping.',
        ],
        'actions': [
            'Write 5 visual cues (palette, framing, texture, pacing, mood).',
            'Draft one adaptation prompt for your current client context.',
            'Tag relevant style patterns in hubs.',
        ],
    },
    'ops': {
        'primary': 'Convert this into an executable workflow or checklist improvement.',
        'secondary': [
            'Turn into SOP notes for repeatability.',
            'Identify one automation candidate and owner.',
        ],
        'actions': [
            'Define current bottleneck in one sentence.',
            'Propose one automation step.',
            'Assign next action and due date.',
        ],
    },
    'transcript': {
        'primary': 'Turn transcript into key takeaways and reusable soundbites for creative strategy.',
        'secondary': [
            'Extract quotable lines for concept framing.',
            'Summarize argument arc for case-building.',
        ],
        'actions': [
            'Extract top 5 quotes.',
            'Summarize in one paragraph for sharing.',
            'Identify 2 routes to apply in current work.',
        ],
    },
}

STOPWORDS = {
    'the', 'and', 'for', 'that', 'with', 'this', 'from', 'you', 'your', 'are', 'was', 'were',
    'have', 'has', 'had', 'all', 'into', 'will', 'can', 'not', 'but', 'its', 'out', 'about',
    'what', 'when', 'where', 'why', 'how', 'just', 'they', 'them', 'their', 'our', 'ours',
}

DEFAULT_REQUIRED_REVIEW_FIELDS = [
    'id',
    'source_file',
    'source_hash',
    'raw_data',
    'content_type',
    'summary_1line',
    'intent',
    'candidate_hubs',
    'routing_reason',
    'understanding_confidence',
    'application_confidence',
    'actionability_score',
    'status',
]


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding='utf-8'))
    except Exception:
        return {}


def get_required_review_fields():
    settings = load_settings()
    fields = settings.get('contracts', {}).get('review_card', {}).get('required_fields', [])
    if isinstance(fields, list) and fields:
        return [str(f) for f in fields]
    return DEFAULT_REQUIRED_REVIEW_FIELDS


def has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run_cmd(cmd, timeout=120):
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=timeout,
        )
        return p.stdout.strip(), p.stderr.strip(), 0
    except subprocess.TimeoutExpired:
        return '', f'timeout after {timeout}s', 124
    except subprocess.CalledProcessError as exc:
        return '', exc.stderr.strip() or str(exc), exc.returncode


def add_warning(warnings, code: str, message: str, recoverable=True):
    warnings.append(
        {
            'warning_code': code,
            'warning_message': message,
            'recoverable': bool(recoverable),
        }
    )


def read_text_file(path: Path, warnings: list[dict]):
    try:
        return path.read_text(encoding='utf-8', errors='replace')
    except Exception as exc:
        add_warning(warnings, 'TEXT_READ_FAILED', str(exc), recoverable=False)
        return ''


def extract_image_text(path: Path, warnings: list[dict]):
    if not has_cmd('tesseract'):
        add_warning(warnings, 'OCR_TOOL_MISSING', 'tesseract not installed', recoverable=True)
        return ''
    out, err, rc = run_cmd(['tesseract', str(path), 'stdout'], timeout=180)
    if rc != 0:
        add_warning(warnings, 'OCR_FAILED', err or 'tesseract failed', recoverable=True)
        return ''
    return out


def resolve_whisper_cmd():
    if has_cmd('whisper'):
        return ['whisper']
    if has_cmd('openai-whisper'):
        return ['openai-whisper']
    return []


def extract_audio_video_text(path: Path, warnings: list[dict], digest: str):
    if not has_cmd('ffmpeg'):
        add_warning(warnings, 'FFMPEG_MISSING', 'ffmpeg not installed', recoverable=True)
        return ''

    whisper_cmd = resolve_whisper_cmd()
    if not whisper_cmd:
        add_warning(warnings, 'WHISPER_MISSING', 'whisper cli not installed', recoverable=True)
        return ''

    logs_dir = ROOT / '0 system' / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    tmp_wav = logs_dir / f'tmp_{path.stem}_{digest[:8]}.wav'

    _, err, rc = run_cmd(
        ['ffmpeg', '-y', '-i', str(path), '-vn', '-ac', '1', '-ar', '16000', str(tmp_wav)],
        timeout=600,
    )
    if rc != 0:
        add_warning(warnings, 'FFMPEG_EXTRACT_FAILED', err or 'audio extraction failed', recoverable=True)
        return ''

    whisper_model = os.getenv('RUN_WHISPER_MODEL', 'base').strip() or 'base'
    whisper_timeout = int(os.getenv('RUN_WHISPER_TIMEOUT', '1800'))

    _, werr, wrc = run_cmd(
        whisper_cmd
        + [
            str(tmp_wav),
            '--model',
            whisper_model,
            '--output_format',
            'txt',
            '--output_dir',
            str(logs_dir),
        ],
        timeout=whisper_timeout,
    )

    txt_path = logs_dir / f'{tmp_wav.stem}.txt'
    text = ''
    if wrc == 0 and txt_path.exists():
        text = txt_path.read_text(encoding='utf-8', errors='replace')
    else:
        add_warning(warnings, 'WHISPER_FAILED', werr or 'transcription failed', recoverable=True)

    try:
        tmp_wav.unlink(missing_ok=True)
        txt_path.unlink(missing_ok=True)
    except Exception:
        pass

    return text


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

    tokens = Counter(tokenize(f'{src.stem}\n{extracted_text[:10000]}'))
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
    counts = Counter(tokenize(f'{src.stem}\n{extracted_text[:12000]}'))
    return [token for token, _ in counts.most_common(limit)]


def score_candidate_hubs(src: Path, extracted_text: str, existing_hubs: list[str], top_n: int = 3):
    counts = Counter(tokenize(f'{src.stem}\n{extracted_text[:12000]}'))
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


def list_to_text(items: list[str]) -> str:
    return '; '.join([i for i in items if i]).strip()


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


def heuristic_enrichment(intent: str, summary: str, nuggets: list[str], candidate_str: str):
    play = INTENT_PLAYBOOK.get(intent, INTENT_PLAYBOOK['research'])
    reusable = nuggets[:3] if nuggets else [summary]
    return {
        'llm_summary': summary,
        'llm_intent': intent,
        'understanding_confidence': 0.62,
        'application_confidence': 0.58,
        'actionability_score': 0.60,
        'primary_use_case': play['primary'],
        'secondary_use_cases': play['secondary'][:2],
        'immediate_actions': play['actions'][:3],
        'reusable_assets': reusable,
        'project_relevance_candidates': ['active-creative-brief', 'strategy-deck'],
        'candidate_hubs_semantic': candidate_str,
        'routing_reason': f'Heuristic V2 enrichment from intent={intent} and keyword profile.',
        'routing_method': 'rule',
        'llm_used': False,
    }


def parse_json_object(text: str):
    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def clamp01(value, default=0.5):
    try:
        v = float(value)
        return max(0.0, min(0.99, v))
    except Exception:
        return default


def normalize_scored_hubs(raw):
    scored = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                hub = str(item.get('hub', '')).strip()
                try:
                    score = float(item.get('score', 0.0))
                except Exception:
                    score = 0.0
                if hub:
                    scored.append((hub, max(0.0, min(0.99, score))))
    elif isinstance(raw, str):
        for part in raw.split(','):
            part = part.strip()
            if ':' not in part:
                continue
            hub, score_s = part.split(':', 1)
            try:
                score = float(score_s)
            except Exception:
                score = 0.0
            if hub.strip():
                scored.append((hub.strip(), max(0.0, min(0.99, score))))

    dedup = {}
    for hub, score in scored:
        dedup[hub] = max(score, dedup.get(hub, 0.0))
    ranked = sorted(dedup.items(), key=lambda x: x[1], reverse=True)
    return ranked[:3]


def ollama_enrichment(payload: dict):
    model = os.getenv('RUN_INTEL_MODEL_LOCAL', '').strip()
    if not model:
        return None, 'ollama disabled (RUN_INTEL_MODEL_LOCAL not set)'
    if not has_cmd('ollama'):
        return None, 'ollama cli missing'

    prompt = (
        'Return strict JSON only. Analyze this asset and provide keys: '
        'llm_summary, llm_intent, understanding_confidence, application_confidence, '
        'actionability_score, primary_use_case, secondary_use_cases, immediate_actions, '
        'reusable_assets, project_relevance_candidates, candidate_hubs_semantic, routing_reason. '
        'candidate_hubs_semantic must be array of objects {hub, score}. '
        f'Input: {json.dumps(payload, ensure_ascii=False)}'
    )
    timeout = int(os.getenv('RUN_OLLAMA_TIMEOUT', '120'))
    out, err, rc = run_cmd(['ollama', 'run', model, prompt], timeout=timeout)
    if rc != 0:
        return None, f'ollama failed: {err or out}'

    parsed = parse_json_object(out)
    if not parsed:
        return None, 'ollama non-json response'
    return parsed, ''


def enrich_v2(src: Path, meta: dict, full_text: str, summary: str, intent: str, entities: list[str], keywords: list[str], candidate_hubs_rule: list[tuple[str, float]], nuggets: list[str], warnings: list[dict]):
    candidate_str = ', '.join(f'{n}:{s:.2f}' for n, s in candidate_hubs_rule)
    heuristic = heuristic_enrichment(intent, summary, nuggets, candidate_str)

    llm_input = {
        'filename': src.name,
        'mime': meta.get('mime', ''),
        'content_type': infer_content_type(src),
        'summary_1line': summary,
        'intent_hint': intent,
        'entities_hint': entities,
        'keywords_hint': keywords,
        'candidate_hubs_rule': [{'hub': h, 'score': s} for h, s in candidate_hubs_rule],
        'text_excerpt': full_text[:12000],
    }

    llm_obj, llm_err = ollama_enrichment(llm_input)
    if not llm_obj:
        add_warning(warnings, 'LLM_FALLBACK', llm_err, recoverable=True)
        return heuristic

    sem_hubs = normalize_scored_hubs(llm_obj.get('candidate_hubs_semantic', []))
    sem_str = ', '.join(f'{h}:{s:.2f}' for h, s in sem_hubs)

    secondary = llm_obj.get('secondary_use_cases', [])
    actions = llm_obj.get('immediate_actions', [])
    reusable = llm_obj.get('reusable_assets', [])
    projects = llm_obj.get('project_relevance_candidates', [])

    if not isinstance(secondary, list):
        secondary = [str(secondary)]
    if not isinstance(actions, list):
        actions = [str(actions)]
    if not isinstance(reusable, list):
        reusable = [str(reusable)]
    if not isinstance(projects, list):
        projects = [str(projects)]

    secondary = [str(x).strip() for x in secondary if str(x).strip()][:3] or heuristic['secondary_use_cases']
    actions = [str(x).strip() for x in actions if str(x).strip()][:3] or heuristic['immediate_actions']
    reusable = [str(x).strip() for x in reusable if str(x).strip()][:5] or heuristic['reusable_assets']
    projects = [str(x).strip() for x in projects if str(x).strip()][:3] or heuristic['project_relevance_candidates']

    return {
        'llm_summary': str(llm_obj.get('llm_summary', '')).strip() or summary,
        'llm_intent': str(llm_obj.get('llm_intent', '')).strip() or intent,
        'understanding_confidence': clamp01(llm_obj.get('understanding_confidence'), 0.75),
        'application_confidence': clamp01(llm_obj.get('application_confidence'), 0.72),
        'actionability_score': clamp01(llm_obj.get('actionability_score'), 0.70),
        'primary_use_case': str(llm_obj.get('primary_use_case', '')).strip() or heuristic['primary_use_case'],
        'secondary_use_cases': secondary,
        'immediate_actions': actions,
        'reusable_assets': reusable,
        'project_relevance_candidates': projects,
        'candidate_hubs_semantic': sem_str or candidate_str,
        'routing_reason': str(llm_obj.get('routing_reason', '')).strip() or 'Local Ollama semantic interpretation.',
        'routing_method': 'hybrid',
        'llm_used': True,
    }


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


def format_warnings_markdown(warnings: list[dict]):
    if not warnings:
        return '- none'
    return '\n'.join(
        f"- [{w['warning_code']}] {w['warning_message']} (recoverable={str(w['recoverable']).lower()})" for w in warnings
    )


def validate_review_frontmatter(frontmatter: dict, required_fields: list[str]):
    missing = []
    for field in required_fields:
        value = frontmatter.get(field, '')
        if str(value).strip() == '':
            missing.append(field)
    return missing


def to_review_md(src: Path, source_rel: str, digest: str, meta: dict, raw_rel: str, extracted_text: str, warnings: list[dict], required_fields: list[str]):
    date = datetime.now().strftime('%Y-%m-%d')
    stem_slug = src.stem.lower().replace(' ', '-').replace('_', '-')
    ext_slug = src.suffix.lower().lstrip('.') or 'file'
    slug = f'{stem_slug}-{ext_slug}'
    review_name = f'{date}_review-{slug}.md'
    review_path = unique_destination(REVIEW, review_name)

    full_text = (extracted_text or '').strip()
    sample = full_text[:5000]
    warning_md = format_warnings_markdown(warnings)
    warning_codes = ','.join(w['warning_code'] for w in warnings)

    content_type = infer_content_type(src)
    language = infer_language(full_text)
    summary = summarize_1line(src, full_text)
    intent = infer_intent(src, full_text)
    entities = extract_entities(full_text)
    keywords = extract_keywords(src, full_text)
    existing_hubs = [p.name for p in HUBS.iterdir() if p.is_dir() and not p.name.startswith('.')] if HUBS.exists() else []
    candidate_hubs_rule = score_candidate_hubs(src, full_text, existing_hubs)
    candidate_str = ', '.join(f'{name}:{score:.2f}' for name, score in candidate_hubs_rule)
    entities_str = ', '.join(entities)
    keywords_str = ', '.join(keywords)
    nuggets = reusable_nuggets(full_text)

    enrich = enrich_v2(src, meta, full_text, summary, intent, entities, keywords, candidate_hubs_rule, nuggets, warnings)

    review_frontmatter = {
        'id': f'REVIEW-AUTO-{digest[:8]}',
        'topic': f'Auto extraction: {src.name}',
        'project': '',
        'reviewer': 'Kit',
        'status': 'review_draft',
        'date': date,
        'inbox_file': str(src.relative_to(ROOT)),
        'source_file': source_rel,
        'source_hash': digest,
        'raw_data': raw_rel,
        'content_type': content_type,
        'language': language,
        'summary_1line': summary,
        'intent': intent,
        'client': '',
        'market': '',
        'entities': entities_str,
        'keywords': keywords_str,
        'candidate_hubs': candidate_str,
        'candidate_hubs_semantic': enrich['candidate_hubs_semantic'],
        'llm_summary': enrich['llm_summary'],
        'llm_intent': enrich['llm_intent'],
        'understanding_confidence': f"{enrich['understanding_confidence']:.2f}",
        'application_confidence': f"{enrich['application_confidence']:.2f}",
        'actionability_score': f"{enrich['actionability_score']:.2f}",
        'primary_use_case': enrich['primary_use_case'],
        'secondary_use_cases': list_to_text(enrich['secondary_use_cases']),
        'immediate_actions': list_to_text(enrich['immediate_actions']),
        'reusable_assets': list_to_text(enrich['reusable_assets']),
        'project_relevance_candidates': list_to_text(enrich['project_relevance_candidates']),
        'routing_method': enrich['routing_method'],
        'routing_reason': enrich['routing_reason'],
        'routing_decision': '',
        'routing_confidence': '0.00',
        'needs_human_review': 'true',
        'human_override': 'false',
        'override_reason': '',
        'warning_codes': warning_codes,
        'warning_count': str(len(warnings)),
    }

    missing_required = validate_review_frontmatter(review_frontmatter, required_fields)
    if missing_required:
        review_frontmatter['status'] = 'blocked'
        add_warning(
            warnings,
            'REVIEW_SCHEMA_MISSING_FIELDS',
            f"missing required fields: {', '.join(missing_required)}",
            recoverable=False,
        )
        warning_md = format_warnings_markdown(warnings)
        review_frontmatter['warning_codes'] = ','.join(w['warning_code'] for w in warnings)
        review_frontmatter['warning_count'] = str(len(warnings))

    fm_lines = ['---']
    for key, value in review_frontmatter.items():
        fm_lines.append(f'{key}: "{q(value)}"')
    fm_lines.append('---')

    why_lines = [
        f"- Primary intent detected: `{intent}`",
        f"- Source type: `{content_type}` ({meta['mime']})",
        f"- Understanding confidence: `{enrich['understanding_confidence']:.2f}`",
        f"- Application confidence: `{enrich['application_confidence']:.2f}`",
    ]
    why_block = '\n'.join(why_lines)
    secondary_lines = '\n'.join(f'- {x}' for x in enrich['secondary_use_cases']) or '- none'
    action_lines = '\n'.join(f'- {x}' for x in enrich['immediate_actions']) or '- none'
    reuse_lines = '\n'.join(f'- {x}' for x in enrich['reusable_assets']) or '- none'

    body = f"""
## File Metadata
- path: `{meta['path']}`
- mime: `{meta['mime']}`
- size_bytes: `{meta['size_bytes']}`
- modified: `{meta['modified']}`

## Understanding
{why_block}
- LLM summary: `{enrich['llm_summary']}`

## Use This Now
- Primary use case: {enrich['primary_use_case']}
- Secondary use cases:
{secondary_lines}

## Immediate Actions (24h)
{action_lines}

## Reusable Assets
{reuse_lines}

## Routing Rationale
- Method: `{enrich['routing_method']}`
- Rule candidates: `{candidate_str}`
- Semantic candidates: `{enrich['candidate_hubs_semantic']}`
- Reason: {enrich['routing_reason']}

## Extraction Warnings
{warning_md}

## Full Extracted Text
```
{sample}
```

## Review Decision
- Approve / Request changes
"""

    review_path.write_text('\n'.join(fm_lines) + '\n' + body.strip() + '\n', encoding='utf-8')
    return review_path, review_frontmatter


def append_ingestion_report(record: dict):
    INGEST_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with INGEST_REPORT.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description='Process inbox files from 1 todo into 1 review')
    parser.add_argument('--force', action='store_true', help='Reprocess all files in 1 todo even if hashes are unchanged')
    parser.add_argument('--strict', action='store_true', help='Exit non-zero if any review card is blocked by schema validation')
    parser.add_argument('--report', action='store_true', help='Print ingestion report summary path and counts')
    args = parser.parse_args()

    required_fields = get_required_review_fields()

    RAW.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    REVIEW_ORIGINALS.mkdir(parents=True, exist_ok=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    INGEST_REPORT.parent.mkdir(parents=True, exist_ok=True)
    INGEST_REPORT.touch(exist_ok=True)

    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding='utf-8'))
        except Exception:
            state = {}

    files = [p for p in TODO.iterdir() if p.is_file() and not p.name.startswith('.')]
    processed = 0
    blocked = 0
    failed = 0

    for path in sorted(files):
        started = time.time()
        digest = sha256_file(path)
        ext = path.suffix.lower()
        meta = generic_meta(path)
        warnings = []

        content_type = infer_content_type(path)
        is_supported = ext in TEXT_EXT or ext in IMG_EXT or ext in AUDIO_EXT or ext in VIDEO_EXT
        expects_text = is_supported
        extractor = 'metadata-only'
        text = ''

        if ext in TEXT_EXT:
            extractor = 'native-text'
            text = read_text_file(path, warnings)
        elif ext in IMG_EXT:
            extractor = 'tesseract-ocr'
            text = extract_image_text(path, warnings)
        elif ext in AUDIO_EXT or ext in VIDEO_EXT:
            extractor = 'whisper-asr'
            text = extract_audio_video_text(path, warnings, digest)
        else:
            add_warning(warnings, 'UNSUPPORTED_TYPE', 'unsupported file type; metadata only', recoverable=True)

        if expects_text and not text.strip():
            add_warning(warnings, 'EXTRACTION_EMPTY', 'no text was extracted', recoverable=True)

        raw_slug = f"{path.stem}_{path.suffix.lower().lstrip('.') or 'file'}_{digest[:8]}"
        raw_base = RAW / raw_slug
        raw_base.mkdir(parents=True, exist_ok=True)
        (raw_base / 'raw.txt').write_text(text or '', encoding='utf-8')
        (raw_base / 'meta.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
        (raw_base / 'warnings.json').write_text(json.dumps(warnings, indent=2), encoding='utf-8')

        moved_dest = unique_destination(REVIEW_ORIGINALS, path.name)
        moved_ok = False
        source_rel = str(path.relative_to(ROOT))
        try:
            shutil.move(str(path), str(moved_dest))
            moved_ok = True
            source_rel = str(moved_dest.relative_to(ROOT))
        except Exception as move_exc:
            add_warning(warnings, 'MOVE_FAILED', f'failed to move source to review/originals: {move_exc}', recoverable=False)

        review_path = None
        review_meta = {}
        status = 'failed'

        if moved_ok:
            review_path, review_meta = to_review_md(
                path,
                source_rel,
                digest,
                meta,
                str(raw_base.relative_to(ROOT)),
                text,
                warnings,
                required_fields,
            )
            status = 'processed'
            processed += 1
            if review_meta.get('status') == 'blocked':
                blocked += 1
        else:
            failed += 1

        elapsed_ms = int((time.time() - started) * 1000)
        report_row = {
            'timestamp': datetime.now().isoformat(),
            'input_file': str(meta['path']),
            'source_hash': digest,
            'content_type': content_type,
            'is_supported': is_supported,
            'expects_text': expects_text,
            'extractor': extractor,
            'extracted_chars': len(text or ''),
            'warning_count': len(warnings),
            'warning_codes': [w['warning_code'] for w in warnings],
            'moved_source': moved_ok,
            'moved_path': source_rel if moved_ok else '',
            'review_file': str(review_path.relative_to(ROOT)) if review_path else '',
            'raw_dir': str(raw_base.relative_to(ROOT)),
            'status': status,
            'strict_blocked': review_meta.get('status') == 'blocked',
            'elapsed_ms': elapsed_ms,
        }
        append_ingestion_report(report_row)

        state[path.name] = {
            'hash': digest,
            'processed_at': datetime.now().isoformat(),
            'raw_dir': str(raw_base.relative_to(ROOT)),
            'status': status,
        }

    STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')

    mode = ' (force)' if args.force else ''
    print(f'Processed {processed} file(s){mode}. Blocked={blocked}, Failed={failed}.')
    if args.report:
        print(f'Report log: {INGEST_REPORT.relative_to(ROOT)}')

    if args.strict and blocked > 0:
        print('Strict mode: blocked reviews found.')
        sys.exit(2)


if __name__ == '__main__':
    main()
