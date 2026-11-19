#!/usr/bin/env python3
"""Local command-line tools for the DeepSeek Harness health-card skill."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
import wave


def prepare_reminder(text_file):
    """Prepare one WAV before its task exists and return a safe reference."""
    from qwen_voice import configured, synthesize
    if not configured():
        raise RuntimeError('请在 Harness 启动环境配置千问 API Key，再准备提醒语音。')
    root = Path(__file__).resolve().parents[4]
    directory = root / 'outputs/harness/reminder-audio'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    audio_id = str(uuid.uuid4())
    text = text_file.read_text(encoding='utf-8').strip()
    if text.startswith('【') and '\n' in text:
        text = text.split('\n', 1)[1].strip()
    if not 0 < len(text) <= 180:
        raise ValueError('提醒文稿应为 1 到 180 字。')
    with tempfile.TemporaryDirectory(dir=directory) as work:
        temp = Path(work)
        wav = temp / 'prepared.wav'
        wav.write_bytes(synthesize(text))
        with wave.open(str(wav), 'rb') as audio:
            seconds = audio.getnframes() / audio.getframerate()
            if not 0 < seconds <= 60 or not audio.readframes(1):
                raise ValueError('提醒音频为空或超过一分钟。')
        wav.chmod(0o600)
        output = directory / (audio_id + '.wav')
        os.replace(wav, output)
    return {'audio_id': audio_id, 'marker': f'[[elder-health-audio:{audio_id}]]',
            'output': str(output), 'seconds': round(seconds, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    scan = commands.add_parser('scan', help='OCR a local image; returns unconfirmed candidates')
    scan.add_argument('--image', required=True, type=Path)
    scan.add_argument('--kind', required=True, choices=['report', 'medication'])
    scan.add_argument('--output', required=True, type=Path)
    speech = commands.add_parser('speech', help='Synthesize an authorized reminder with existing Qwen settings')
    speech.add_argument('--text', required=True, type=Path)
    speech.add_argument('--output', required=True, type=Path)
    prepare = commands.add_parser('prepare-reminder', help='Pre-render a WAV and issue a Harness task marker')
    prepare.add_argument('--text', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'prepare-reminder':
        print(json.dumps(prepare_reminder(args.text), ensure_ascii=False))
        return
    if args.command == 'scan':
        from recognition import recognize, read_medication, read_metrics
        photo = args.image.read_bytes()
        if len(photo) > 12_000_000:
            raise ValueError('图片不能超过 12 MB。')
        raw = recognize(photo)
        candidates = read_metrics(raw) if args.kind == 'report' else read_medication(raw)
        if args.kind == 'report' and not candidates:
            raw = recognize(photo, report_retry=True)
            candidates = read_metrics(raw)
        payload = {'kind': args.kind, 'image': str(args.image.resolve()),
                   'raw_text': raw, 'candidates': candidates, 'confirmed': False,
                   'notice': 'OCR 候选值，须对照原图核对；不是排版输入，不可直接生成服药安排。'}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        from qwen_voice import synthesize
        text = args.text.read_text(encoding='utf-8').strip()
        # The renderer's first line is metadata, not part of the narration.
        if text.startswith('【') and '\n' in text:
            text = text.split('\n', 1)[1].strip()
        audio = synthesize(text)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(audio)
    print(json.dumps({'output': str(args.output.resolve())}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, wave.Error) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
