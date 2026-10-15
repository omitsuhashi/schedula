"""公開prefixとLambdaイベントをlocalhostで結合確認するテスト用サーバー。"""

import argparse
import json
import mimetypes
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from web.build import build
from web.handler import PREFIX, lambda_handler


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        target = self.server.directory / path.lstrip("/")
        if path.endswith("/"):
            target /= "index.html"
        if not target.is_file() or not target.resolve().is_relative_to(self.server.directory):
            self.send_error(404)
            return
        content = target.read_bytes()
        media = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if not self.path.startswith(PREFIX):
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
        host = "example.lambda-url.ap-northeast-1.on.aws"
        headers = {key.lower(): value for key, value in self.headers.items()}
        # localhost上だけでCloudFrontの転送を模擬する。公開handlerの検査は変更しない。
        headers.update(host=host, origin="https://the3.co.jp")
        result = lambda_handler(
            {
                "rawPath": self.path,
                "requestContext": {"http": {"method": "POST"}, "domainName": host},
                "headers": headers,
                "body": body,
            },
            None,
        )
        content = result["body"].encode()
        self.send_response(result["statusCode"])
        for key, value in result["headers"].items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="schedula-public-") as directory:
        build(directory)
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            server.directory = Path(directory).resolve()
            print(json.dumps({"port": server.server_port}), flush=True)
            server.serve_forever()
