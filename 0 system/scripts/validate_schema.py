#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path('.').resolve()
SETTINGS = ROOT / '0 system' / 'settings' / 'system.yaml'
REVIEW = ROOT / '1 review'
ARCHIVE_REVIEWS = ROOT / '1 archive' / 'reviews'
HUBS = ROOT / '3 hubs'
LOGS = ROOT / '0 system' / 'logs'


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding='utf-8'))
    except Exception as exc:
        print(f'ERROR: failed to parse {SETTINGS}: {exc}')
        sys.exit(1)


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


def iter_markdown_files(base: Path):
    if not base.exists():
        return []
    files = []
    for p in base.rglob('*.md'):
        if p.name == 'README.md':
            continue
        files.append(p)
    return sorted(files)


def missing_fields(frontmatter: dict, required: list[str]):
    missing = []
    for key in required:
        value = frontmatter.get(key, '').strip() if isinstance(frontmatter.get(key, ''), str) else frontmatter.get(key)
        if value in ('', None):
            missing.append(key)
    return missing


def validate_files(files: list[Path], required: list[str], label: str, lifecycle_states: list[str] | None = None):
    issues = []
    warnings = []
    checked = 0
    for file in files:
        checked += 1
        text = file.read_text(encoding='utf-8', errors='replace')
        fm = parse_frontmatter(text)
        if not fm:
            issues.append(f'{label}: {file.relative_to(ROOT)} missing/invalid frontmatter')
            continue
        if lifecycle_states is not None:
            status = str(fm.get('status', '')).strip()
            if label == 'review_card' and status == 'curated':
                warnings.append(
                    f'{label}: {file.relative_to(ROOT)} legacy status `{status}` (skipped strict check)'
                )
                continue
            if label == 'review_card' and file.parent == REVIEW and status in {'curated', 'archived'}:
                warnings.append(
                    f'{label}: {file.relative_to(ROOT)} legacy placement for status `{status}` (skipped strict check)'
                )
                continue
            if status and status not in lifecycle_states:
                warnings.append(
                    f'{label}: {file.relative_to(ROOT)} legacy status `{status}` (skipped strict check)'
                )
                continue
        missing = missing_fields(fm, required)
        if missing:
            issues.append(f"{label}: {file.relative_to(ROOT)} missing fields: {', '.join(missing)}")
    return checked, issues, warnings


def main():
    cfg = load_settings()
    contracts = cfg.get('contracts', {})
    lifecycle = cfg.get('lifecycle_states', [])
    required_logs = contracts.get('state_logs', {}).get('required_fields', [])

    issues = []
    warnings = []

    if len(lifecycle) < 5:
        issues.append('config: lifecycle_states is incomplete')

    review_required = contracts.get('review_card', {}).get('required_fields', [])
    hub_required = contracts.get('hub_card', {}).get('required_fields', [])
    archive_required = contracts.get('archive_record', {}).get('required_fields', [])

    if not review_required:
        issues.append('config: contracts.review_card.required_fields missing')
    if not hub_required:
        issues.append('config: contracts.hub_card.required_fields missing')
    if not archive_required:
        issues.append('config: contracts.archive_record.required_fields missing')

    for log_key in required_logs:
        log_path = LOGS / f'{log_key}.jsonl'
        if log_key in ('inbox_state', 'review_state', 'maturity_score'):
            log_path = LOGS / f'{log_key}.json'
        if not log_path.exists():
            if log_key == 'maturity_score':
                warnings.append(f'logs: missing optional pre-check log {log_path.relative_to(ROOT)}')
            else:
                issues.append(f'logs: missing required log file {log_path.relative_to(ROOT)}')

    review_files = sorted(REVIEW.glob('*.md')) + sorted(ARCHIVE_REVIEWS.glob('*.md'))
    review_checked, review_issues, review_warnings = validate_files(
        review_files, review_required, 'review_card', lifecycle_states=lifecycle
    )
    issues.extend(review_issues)
    warnings.extend(review_warnings)

    hub_files = iter_markdown_files(HUBS)
    hub_checked, hub_issues, hub_warnings = validate_files(hub_files, hub_required, 'hub_card')
    issues.extend(hub_issues)
    warnings.extend(hub_warnings)

    archive_files = sorted(ARCHIVE_REVIEWS.glob('*.md'))
    archive_checked, archive_issues, archive_warnings = validate_files(archive_files, archive_required, 'archive_record')
    issues.extend(archive_issues)
    warnings.extend(archive_warnings)

    print(f'Checked review cards: {review_checked}')
    print(f'Checked hub cards: {hub_checked}')
    print(f'Checked archive cards: {archive_checked}')

    if warnings:
        print('\nValidation warnings:')
        for warn in warnings:
            print(f'- {warn}')

    if issues:
        print('\nValidation failed:')
        for issue in issues:
            print(f'- {issue}')
        sys.exit(1)

    print('Validation passed.')


if __name__ == '__main__':
    main()
