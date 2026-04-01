#!/usr/bin/env python3
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path('.').resolve()
SETTINGS = ROOT / '0 system' / 'settings' / 'system.yaml'
LOGS = ROOT / '0 system' / 'logs'
INGEST_LOG = LOGS / 'ingestion_report.jsonl'
MATURE_LOG = LOGS / 'maturity_score.json'
ARCHIVE_REVIEW = ROOT / '1 archive' / 'reviews'
ARCHIVE_ORIGINALS = ROOT / '1 archive' / 'originals'
REVIEW = ROOT / '1 review'
HUBS = ROOT / '3 hubs'
APPROVALS = REVIEW / 'approvals'


def parse_frontmatter(text: str):
    if not text.startswith('---\n'):
        return {}
    end = text.find('\n---\n', 4)
    if end == -1:
        return {}
    fm = {}
    for line in text[4:end].splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        fm[key.strip()] = value.strip().strip('"')
    return fm


def read_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding='utf-8'))
    except Exception as exc:
        print(f'ERROR: failed to parse {SETTINGS}: {exc}')
        sys.exit(1)


def to_bool(value: str):
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y'}


def compute_determinism_snapshot():
    targets = []
    for p in sorted(ARCHIVE_REVIEW.glob('*.md')):
        targets.append(p)
    for p in sorted(HUBS.rglob('*.md')):
        if p.name == 'README.md':
            continue
        targets.append(p)
    digest = hashlib.sha256()
    for p in targets:
        try:
            digest.update(str(p.relative_to(ROOT)).encode('utf-8', errors='replace'))
            digest.update(b'\n')
            digest.update(p.read_text(encoding='utf-8', errors='replace').encode('utf-8', errors='replace'))
            digest.update(b'\n')
        except Exception:
            continue
    return digest.hexdigest()


def main():
    cfg = load_settings()
    thresholds = cfg.get('quality_thresholds', {})
    required_fields = cfg.get('contracts', {}).get('review_card', {}).get('required_fields', [])
    lifecycle_states = {str(x) for x in cfg.get('lifecycle_states', [])}
    required_passes = cfg.get('automation_gate', {}).get('required_consecutive_quality_passes', 2)

    review_files = sorted(REVIEW.glob('*.md')) + sorted(ARCHIVE_REVIEW.glob('*.md'))
    valid_cards = 0
    actionable_cards = 0
    eligible_cards = 0
    for file in review_files:
        text = file.read_text(encoding='utf-8', errors='replace')
        fm = parse_frontmatter(text)
        if not fm:
            continue
        status = str(fm.get('status', '')).strip()
        if status and lifecycle_states and status not in lifecycle_states:
            continue
        if status == 'curated':
            # Legacy status from pre-maturity flow.
            continue
        if file.parent == REVIEW and status in {'curated', 'archived'}:
            # Legacy placement from older workflow should not count against maturity scores.
            continue

        eligible_cards += 1

        missing = [f for f in required_fields if not str(fm.get(f, '')).strip()]
        if not missing:
            valid_cards += 1

        has_use_case = bool(str(fm.get('primary_use_case', '')).strip())
        has_actions = bool(str(fm.get('immediate_actions', '')).strip())
        has_assets = bool(str(fm.get('reusable_assets', '')).strip())
        if has_use_case and has_actions and has_assets:
            actionable_cards += 1

    schema_completeness = valid_cards / eligible_cards if eligible_cards else 1.0
    actionability_quality = actionable_cards / eligible_cards if eligible_cards else 1.0

    archive_files = sorted(ARCHIVE_REVIEW.glob('*.md'))
    movement_ok = 0
    for file in archive_files:
        fm = parse_frontmatter(file.read_text(encoding='utf-8', errors='replace'))
        src = fm.get('archived_source', '')
        rev = fm.get('archived_review', '')
        if src.startswith('1 archive/originals/') and rev.startswith('1 archive/reviews/') and (ROOT / src).exists():
            movement_ok += 1
    source_movement_integrity = movement_ok / len(archive_files) if archive_files else 1.0

    ingest_rows = read_jsonl(INGEST_LOG)
    supported_total = 0
    processed_count = 0
    failed_count = 0
    silent_failures = 0
    extraction_nonempty_hits = 0
    extraction_expected = 0
    for row in ingest_rows:
        if not row.get('is_supported', False):
            continue
        supported_total += 1
        status = row.get('status', '')
        if status == 'processed':
            processed_count += 1
        if status == 'failed':
            failed_count += 1
            if int(row.get('warning_count', 0)) == 0:
                silent_failures += 1

        if row.get('expects_text', False):
            extraction_expected += 1
            if int(row.get('extracted_chars', 0)) > 0:
                extraction_nonempty_hits += 1

    ingestion_success = processed_count / supported_total if supported_total else 1.0
    no_silent_failures = 1.0 if failed_count == 0 else (1 - (silent_failures / max(failed_count, 1)))
    extraction_nonempty_rate = extraction_nonempty_hits / extraction_expected if extraction_expected else 1.0

    approval_files = sorted(APPROVALS.glob('*.md')) if APPROVALS.exists() else []
    judged = 0
    matched = 0
    for file in approval_files:
        fm = parse_frontmatter(file.read_text(encoding='utf-8', errors='replace'))
        if not to_bool(fm.get('approved', 'false')):
            continue
        proposed = fm.get('proposed_route', '').strip()
        approved_route = fm.get('approved_route', '').strip() or proposed
        if not proposed:
            continue
        judged += 1
        if proposed == approved_route:
            matched += 1
    routing_precision = matched / judged if judged else 1.0

    current_snapshot = compute_determinism_snapshot()
    previous = {}
    if MATURE_LOG.exists():
        try:
            previous = json.loads(MATURE_LOG.read_text(encoding='utf-8'))
        except Exception:
            previous = {}

    prev_snapshot = previous.get('determinism_snapshot', '')
    prev_passed = bool(previous.get('passed', False)) if isinstance(previous, dict) else False
    if not prev_snapshot or not prev_passed:
        determinism = 1.0
    else:
        determinism = 1.0 if prev_snapshot == current_snapshot else 0.0

    metrics = {
        'schema_completeness': round(schema_completeness, 4),
        'source_movement_integrity': round(source_movement_integrity, 4),
        'no_silent_failures': round(no_silent_failures, 4),
        'ingestion_success': round(ingestion_success, 4),
        'actionability_quality': round(actionability_quality, 4),
        'routing_precision': round(routing_precision, 4),
        'determinism': round(determinism, 4),
        'extraction_nonempty_rate': round(extraction_nonempty_rate, 4),
    }

    checks = {}
    for key in (
        'schema_completeness',
        'source_movement_integrity',
        'no_silent_failures',
        'ingestion_success',
        'actionability_quality',
        'routing_precision',
        'determinism',
    ):
        checks[key] = metrics.get(key, 0.0) >= float(thresholds.get(key, 1.0))

    passed = all(checks.values())
    prev_passes = int(previous.get('consecutive_passes', 0)) if isinstance(previous, dict) else 0
    consecutive_passes = prev_passes + 1 if passed else 0
    automation_ready = passed and consecutive_passes >= int(required_passes)

    result = {
        'timestamp': datetime.now().isoformat(),
        'metrics': metrics,
        'thresholds': thresholds,
        'checks': checks,
        'passed': passed,
        'consecutive_passes': consecutive_passes,
        'required_consecutive_passes': int(required_passes),
        'automation_ready': automation_ready,
        'determinism_snapshot': current_snapshot,
    }

    LOGS.mkdir(parents=True, exist_ok=True)
    MATURE_LOG.write_text(json.dumps(result, indent=2), encoding='utf-8')

    print('Maturity quality check:')
    for key, val in metrics.items():
        print(f'- {key}: {val:.4f} (threshold {float(thresholds.get(key, 0.0)):.4f})')
    print(f'- passed: {passed}')
    print(f'- consecutive_passes: {consecutive_passes}/{required_passes}')
    print(f'- automation_ready: {automation_ready}')

    if not passed:
        sys.exit(2)


if __name__ == '__main__':
    main()
