#!/usr/bin/env python3
"""Synthesize a reviewed reminder with the Model Studio CosyVoice HTTP API."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
import wave

MAX_WAV_BYTES = 4 * 1024 * 1024
MODELS = ('cosyvoice-v3-plus', 'cosyvoice-v3-flash', 'cosyvoice-v3.5-plus',
          'cosyvoice-v3.5-flash', 'cosyvoice-v2')


def call_api(workspace, key, endpoint, body, timeout=60):
    if not re.fullmatch(r'[a-zA-Z0-9-]+', workspace):
        raise ValueError('请填写百炼北京地域的业务空间 ID。')
    url = f'https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/{endpoint}'
    request = Request(url, data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                      headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result.get('output'), dict):
        raise ValueError('百炼未返回有效结果，请检查业务空间、模型和音色。')
    return result['output']


def enroll_voice(sample, profile, workspace, key, model):
    mime = {'.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4'}
    if sample.suffix.lower() not in mime:
        raise ValueError('参考录音须为 WAV、MP3 或 M4A。')
    with sample.open('rb') as source:
        data = source.read(10_000_001)
    if not 0 < len(data) <= 10_000_000:
        raise ValueError('参考录音不能为空，文件须不超过 10 MB。')
    audio = f"data:{mime[sample.suffix.lower()]};base64," + base64.b64encode(data).decode('ascii')
    # Reserve the profile before submitting to avoid accidental duplicate enrollment.
    with profile.open('x', encoding='utf-8') as file:
        try:
            output = call_api(workspace, key, 'customization', {
                'model': 'voice-enrollment',
                'input': {'action': 'create_voice', 'target_model': model,
                          'prefix': 'care', 'audio': audio},
            })
            voice = output.get('voice_id')
            if not isinstance(voice, str) or not voice:
                raise ValueError('创建请求未返回音色 ID，请先核对服务端结果。')
        except Exception:
            json.dump({'workspace': workspace, 'state': 'check-provider-result'}, file)
            raise
        json.dump({'workspace': workspace, 'model': model, 'voice': voice}, file)
    return voice


def wait_for_voice(workspace, key, model, voice):
    deadline = monotonic() + 45
    while True:
        output = call_api(workspace, key, 'customization', {
            'model': 'voice-enrollment',
            'input': {'action': 'query_voice', 'voice_id': voice},
        }, timeout=10)
        status = output.get('status')
        if status == 'OK':
            if output.get('target_model') != model:
                raise ValueError('音色绑定的模型和本地记录不一致。')
            return
        if status == 'UNDEPLOYED':
            raise ValueError('百炼未通过这次音色审核。请检查录音后为新样本指定新的档案。')
        if status != 'DEPLOYING':
            raise ValueError('百炼返回了未知的音色状态。')
        if monotonic() >= deadline:
            raise ValueError('音色仍在审核，档案已保存。稍后移除 --sample，使用同一档案继续生成。')
        sleep(3)


def synthesize(text, workspace, key, model, voice, rate):
    body = {'model': model, 'input': {'text': text, 'voice': voice,
            'format': 'wav', 'sample_rate': 24000, 'rate': rate,
            'language_hints': ['zh']}}
    result = call_api(workspace, key, 'SpeechSynthesizer', body)
    try:
        url = urlsplit(result['audio']['url'])
        if result['finish_reason'] != 'stop':
            raise ValueError('语音合成尚未完成。')
    except (KeyError, TypeError):
        raise ValueError('百炼未返回音频地址，请检查音色与模型是否匹配。') from None
    if (url.scheme not in {'http', 'https'} or not url.hostname
            or not url.hostname.endswith('.aliyuncs.com') or url.username):
        raise ValueError('百炼返回了无法验证的音频下载地址。')
    # The documented OSS URL can use HTTP. Fetch it over TLS instead.
    with urlopen(urlunsplit(url._replace(scheme='https')), timeout=60) as response:
        audio = response.read(MAX_WAV_BYTES + 1)
    if len(audio) > MAX_WAV_BYTES:
        raise ValueError('音频过大，请缩短文稿后重新合成。')
    with wave.open(io.BytesIO(audio), 'rb') as wav:
        frames = wav.getnframes()
        seconds = frames / wav.getframerate()
        if not 0 < seconds <= 60:
            raise ValueError(f'实际时长 {seconds:.2f} 秒，请精简文稿后重新合成。')
        if len(wav.readframes(frames)) != frames * wav.getnchannels() * wav.getsampwidth():
            raise ValueError('音频数据不完整。')
    return audio, seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('script', type=Path)
    parser.add_argument('output', type=Path, help='WAV，或在已安装 FFmpeg 时选择 MP3')
    parser.add_argument('--voice', help='百炼音色 ID。默认使用预置音色 longanyang')
    parser.add_argument('--model', choices=MODELS)
    parser.add_argument('--sample', type=Path, help='首次创建家人音色所用的本地录音')
    parser.add_argument('--voice-profile', type=Path, help='本地音色档案 JSON，仅保存音色 ID、模型和业务空间')
    parser.add_argument('--speaker-consent', action='store_true',
                        help='仅在录音人已明确同意上传并用于家人提醒时使用')
    parser.add_argument('--rate', type=float, default=0.92)
    args = parser.parse_args()
    key = os.getenv('DASHSCOPE_API_KEY', '').strip()
    workspace = os.getenv('DASHSCOPE_WORKSPACE_ID', '').strip()
    if not key or not workspace:
        parser.error('请先通过环境变量配置 DASHSCOPE_API_KEY 和 DASHSCOPE_WORKSPACE_ID。')
    suffix = args.output.suffix.lower()
    if suffix not in {'.wav', '.mp3'} or not 0.5 <= args.rate <= 2:
        parser.error('输出文件须为 WAV 或 MP3，语速须在 0.5 到 2 之间。')
    if suffix == '.mp3' and not shutil.which('ffmpeg'):
        parser.error('导出 MP3 需要本机 FFmpeg，也可以直接保存为 WAV。')
    if args.sample and (not args.voice_profile or not args.speaker_consent):
        parser.error('创建音色需要 --voice-profile 和已获得录音人同意的 --speaker-consent。')
    if args.voice_profile and args.voice:
        parser.error('--voice-profile 和 --voice 不能同时使用。')
    if args.sample and args.voice_profile.exists():
        parser.error('该音色档案已存在。请移除 --sample 继续使用已有档案。')

    try:
        lines = args.script.read_text(encoding='utf-8-sig').splitlines()
        if lines and lines[0].startswith('【'):
            lines.pop(0)
        script = '\n'.join(lines).strip()
        if not script:
            raise ValueError('语音稿为空。')
        disclosure = '这是一段人工智能合成的提醒。'
        model = args.model or 'cosyvoice-v3-plus'
        voice = args.voice or 'longanyang'
        if args.sample:
            voice = enroll_voice(args.sample, args.voice_profile, workspace, key, model)
        elif args.voice_profile:
            profile = json.loads(args.voice_profile.read_text(encoding='utf-8'))
            if profile.get('workspace') != workspace or not profile.get('voice'):
                raise ValueError('音色档案与当前业务空间不匹配，或上次创建结果尚待核对。')
            if args.model and args.model != profile.get('model'):
                raise ValueError('指定的模型与音色档案不一致。')
            model, voice = profile['model'], profile['voice']
        elif not args.voice and model != 'cosyvoice-v3-plus':
            raise ValueError('更换模型时请通过 --voice 指定匹配的音色。')
        if args.voice_profile:
            wait_for_voice(workspace, key, model, voice)
        audio, seconds = synthesize(disclosure + '\n' + script, workspace, key,
                                    model, voice, args.rate)
        if suffix == '.mp3':
            audio = subprocess.run(
                ['ffmpeg', '-v', 'error', '-i', 'pipe:0', '-f', 'mp3', 'pipe:1'],
                input=audio, stdout=subprocess.PIPE, check=True,
            ).stdout
        args.output.write_bytes(audio)
    except HTTPError as exc:
        parser.exit(1, f'语音接口或下载请求失败（HTTP {exc.code}）。请检查北京地域业务空间、API Key 和音色。\n')
    except (URLError, TimeoutError):
        parser.exit(1, '无法连接百炼语音服务，请检查网络后重试。\n')
    except (ValueError, OSError, wave.Error, EOFError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'未生成音频：{exc}\n')
    print(f'已保存 {args.output}，原始音频时长 {seconds:.2f} 秒。请试听后分享。')


if __name__ == '__main__':
    main()
