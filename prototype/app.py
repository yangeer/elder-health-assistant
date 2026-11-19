"""Serve the contest reminder prototype with local OCR."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from recognition import read_medication, read_metrics, recognize
from qwen_voice import configured, synthesize, validate_text

HERE = Path(__file__).resolve().parent
ASSETS = {
    '/': (HERE / 'index.html', 'text/html; charset=utf-8'),
    '/style.css': (HERE / 'style.css', 'text/css; charset=utf-8'),
    '/app.js': (HERE / 'app.js', 'text/javascript; charset=utf-8'),
    '/scan.css': (HERE / 'scan.css', 'text/css; charset=utf-8'),
    '/scan.js': (HERE / 'scan.js', 'text/javascript; charset=utf-8'),
    '/demo-report-photo.png': (HERE / 'demo-report-photo.png', 'image/png'),
    '/demo-med-photo.png': (HERE / 'demo-med-photo.png', 'image/png'),
    '/voice.js': (HERE / 'voice.js', 'text/javascript; charset=utf-8'),
    '/cards.js': (HERE / 'cards.js', 'text/javascript; charset=utf-8'),
    '/knowledge.json': (HERE / 'data' / 'knowledge.json',
                        'application/json; charset=utf-8'),
    '/schedule.mjs': (HERE / 'schedule.mjs', 'text/javascript; charset=utf-8'),
    '/scan-demo.wav': (HERE / 'scan-demo.wav', 'audio/wav'),
    '/demo.mp3': (HERE.parent / 'care-reminder-demo.mp3', 'audio/mpeg'),
    '/demo-result.json': (HERE / 'demo-result.json', 'application/json; charset=utf-8'),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        asset = ASSETS.get(urlsplit(self.path).path)
        if not asset:
            self.send_error(404)
            return
        path, mime = asset
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == '/api/reminder/voice':
            self.reminder_voice()
            return
        if path not in ('/api/scan/report', '/api/scan/medication'):
            self.send_error(404)
            return
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            self.send_error(403)
            return
        status = 200
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 12_000_000 or self.headers.get_content_type() not in {
                'image/jpeg', 'image/png', 'image/webp',
            }:
                raise ValueError('请选择不超过 12 MB 的 JPG、PNG 或 WebP 照片。')
            # Process in memory. Never log the image, recognized text or result.
            photo = self.rfile.read(length)
            text = recognize(photo)
            if path.endswith('/report'):
                result = read_metrics(text)
                if not result:
                    try:
                        result = read_metrics(recognize(photo, report_retry=True))
                    except ValueError:
                        # First pass read text but neither pass recovered a complete row.
                        pass
            else:
                result = read_medication(text)
            payload = {'result': result}
        except ValueError as exc:
            status, payload = 422, {'error': str(exc)}
        except RuntimeError as exc:
            status, payload = 503, {'error': str(exc)}
        self.send_payload(status, json.dumps(payload, ensure_ascii=False).encode())

    def reminder_voice(self):
        origin = self.headers.get('Origin')
        if (self.client_address[0] != '127.0.0.1'
                or (origin and urlsplit(origin).netloc != self.headers.get('Host'))
                or self.headers.get('X-Care-Voice') != '1'):
            self.send_payload(403, b'{"error":"Use the local prototype for cloud voice."}')
            return
        if not configured():
            self.send_payload(503, b'{"error":"Cloud voice is not configured."}')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096 or self.headers.get_content_type() != 'application/json':
                raise ValueError('请提交短提醒文稿。')
            payload = json.loads(self.rfile.read(length))
            text = validate_text(payload.get('text') if isinstance(payload, dict) else None)
            audio = synthesize(text)
        except ValueError as exc:
            self.send_payload(422, json.dumps({'error': str(exc)}, ensure_ascii=False).encode())
            return
        except RuntimeError as exc:
            self.send_payload(502, json.dumps({'error': str(exc)}, ensure_ascii=False).encode())
            return
        self.send_payload(200, audio, 'audio/wav')

    def send_payload(self, status, body, mime='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The browser may navigate away while the model renders audio.


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8791)
    parser.add_argument('--host', default='127.0.0.1', help='同一 Wi-Fi 演示时可绑定局域网地址')
    args = parser.parse_args()
    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        print(f'语音提醒原型 http://{args.host}:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
