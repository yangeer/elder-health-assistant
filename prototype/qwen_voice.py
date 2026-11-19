"""Server-side, short Mandarin reminder audio via Qwen Audio Next."""
from functools import lru_cache
from io import BytesIO
import json
import os
import re
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import wave

ENDPOINT = 'https://cn-beijing.maas.qianwenaiapi.com/api/v1/services/audio/tts/SpeechSynthesizer'
MODEL = 'qwen-audio-3.1-tts-next'
MAX_BYTES = 3_000_000
MAX_TEXT = 180
INFLIGHT = threading.BoundedSemaphore(2)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


HTTP = build_opener(NoRedirect)


def configured():
    return bool(os.environ.get('CARE_QWEN_TTS_KEY') or os.environ.get('DASHSCOPE_API_KEY'))


def validate_text(text):
    if (not isinstance(text, str) or not 0 < len(text.strip()) <= MAX_TEXT
            or re.search(r'[@<>{}\x00-\x1f]', text)):
        raise ValueError('提醒文稿应为 1 到 180 字的纯文本。')
    return text.strip()


def secure_audio_url(value):
    if not isinstance(value, str):
        raise RuntimeError('语音模型未返回下载地址。')
    url = urlsplit(value)
    host = url.hostname or ''
    if (url.scheme not in ('http', 'https') or url.username or url.password
            or not any(host.endswith(suffix) for suffix in (
                '.aliyuncs.com', '.qianwenaiapi.com', '.alibabacloud.com',
            ))):
        raise RuntimeError('语音下载地址不属于已知服务域名。')
    return urlunsplit(url._replace(scheme='https'))


def finalized_wave(audio, reported_duration):
    """Validate PCM length and finalize Qwen's streaming-style WAV header."""
    with wave.open(BytesIO(audio), 'rb') as wav:
        frame_size = wav.getnchannels() * wav.getsampwidth()
        declared = wav.getnframes()
        # Cap at the amount that could fit in this response, even with a sentinel header.
        pcm = wav.readframes(min(declared, len(audio) // frame_size))
        frames, partial = divmod(len(pcm), frame_size)
        duration = frames / wav.getframerate()
        if partial or not 0 < duration <= 60:
            raise RuntimeError('生成语音无效或超过一分钟，请使用更短的提醒。')
        if frames == declared:
            return audio
        if (declared * frame_size < 0x7F000000 or not isinstance(reported_duration, (int, float))
                or not abs(duration - reported_duration) <= 0.25):
            raise RuntimeError('生成的音频不完整。')
        output = BytesIO()
        with wave.open(output, 'wb') as target:
            target.setparams(wav.getparams()._replace(nframes=frames))
            target.writeframes(pcm)
    return output.getvalue()


@lru_cache(maxsize=12)
def synthesize(text):
    text = validate_text(text)
    key = os.environ.get('CARE_QWEN_TTS_KEY') or os.environ.get('DASHSCOPE_API_KEY')
    if not key:
        raise RuntimeError('云语音未配置，请使用本机语音。')
    if not INFLIGHT.acquire(blocking=False):
        raise RuntimeError('云语音正在合成，请稍后重试。')
    try:
        request = Request(
            ENDPOINT,
            data=json.dumps({'model': MODEL, 'input': {
                'text_prompt': '一位普通话女声，语气温和、清楚，只逐字朗读引号内的文本，不加任何内容：“'
                + text.replace('“', '‘').replace('”', '’') + '”',
                'format': 'wav', 'sample_rate': 24000, 'channels': 1,
                'rate': 0.9,
            }}, ensure_ascii=False).encode(),
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        )
        with HTTP.open(request, timeout=50) as response:
            output = json.loads(response.read(128_000))['output']
        if output.get('finish_reason') != 'stop':
            raise RuntimeError('云语音未返回完整音频。')
        # Fetch only from the service's storage domains and omit credentials.
        with HTTP.open(secure_audio_url(output['audio']['url']), timeout=20) as response:
            audio = response.read(MAX_BYTES + 1)
        if len(audio) > MAX_BYTES:
            raise RuntimeError('生成音频超出本地大小限制。')
        return finalized_wave(audio, output['audio'].get('duration'))
    except HTTPError as exc:
        raise RuntimeError(f'云语音请求失败（HTTP {exc.code}）。') from None
    except (URLError, TimeoutError, KeyError, TypeError, ValueError, wave.Error, EOFError) as exc:
        raise RuntimeError('云语音未能生成或下载可播放的音频。') from exc
    finally:
        INFLIGHT.release()
