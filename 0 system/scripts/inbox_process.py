#!/usr/bin/env python3
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path('.').resolve()
TODO = ROOT / '1 todo'
REVIEW = ROOT / '1 review'
RAW = TODO / 'raw'
STATE = ROOT / '0 system' / 'logs' / 'inbox_state.json'

TEXT_EXT = {'.md', '.txt', '.csv', '.json', '.yaml', '.yml', '.xml', '.html'}
IMG_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.gif'}
AUDIO_EXT = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}
VIDEO_EXT = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v'}


def has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


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


def extract_audio_video_text(path: Path):
    # Requires ffmpeg + whisper CLI (openai-whisper)
    if not has_cmd('ffmpeg'):
        return '', 'ffmpeg not installed'
    if not has_cmd('whisper'):
        return '', 'whisper CLI not installed'

    tmp_wav = ROOT / '0 system' / 'logs' / f"tmp_{path.stem}.wav"
    out, err = run(['ffmpeg', '-y', '-i', str(path), '-vn', '-ac', '1', '-ar', '16000', str(tmp_wav)])
    if err:
        return '', f'ffmpeg extraction failed: {err}'

    txt_out, werr = run(['whisper', str(tmp_wav), '--model', 'base', '--output_format', 'txt', '--output_dir', str(ROOT / '0 system' / 'logs')])
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


def to_review_md(src: Path, digest: str, meta: dict, raw_rel: str, extracted_text: str, warnings: list[str]):
    date = datetime.now().strftime('%Y-%m-%d')
    slug = src.stem.lower().replace(' ', '-').replace('_', '-')
    review_name = f"{date}_review-{slug}.md"
    review_path = REVIEW / review_name

    sample = extracted_text[:5000] if extracted_text else ''
    warns = '\n'.join(f"- {w}" for w in warnings) if warnings else '- none'

    body = f"""---
id: REVIEW-AUTO-{digest[:8]}
topic: "Auto extraction: {src.name}"
project: ""
reviewer: "Kit"
status: review
date: "{date}"
source_file: "{src.relative_to(ROOT)}"
source_hash: "{digest}"
raw_data: "{raw_rel}"
---

## File Metadata
- path: `{meta['path']}`
- mime: `{meta['mime']}`
- size_bytes: `{meta['size_bytes']}`
- modified: `{meta['modified']}`

## Extraction Warnings
{warns}

## Raw Text (Sample)
```
{sample}
```

## Review Decision
- Approve / Request changes
"""
    review_path.write_text(body, encoding='utf-8')


def main():
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
        if prev and prev.get('hash') == digest:
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
    print(f"Processed {processed} file(s).")


if __name__ == '__main__':
    main()
