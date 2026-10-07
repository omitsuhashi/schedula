"""担当配置・勤務計画を試す loopback 専用の実行入口。"""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

from shift_schedula import solve
from shift_schedula.contract import InvalidInput, load_json

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "examples" / "playground"
BASELINE = load_json((SAMPLES / "lunch.json").read_text(encoding="utf-8"))
TIMES = sorted({value for item in BASELINE["demand"] for value in item["interval"].values()})
FILES = {
    "/": (ROOT / "demo" / "index.html", "text/html; charset=utf-8"),
    "/app.js": (ROOT / "demo" / "app.js", "text/javascript; charset=utf-8"),
    "/style.css": (ROOT / "demo" / "style.css", "text/css; charset=utf-8"),
    "/samples/lunch.json": (SAMPLES / "lunch.json", "application/json; charset=utf-8"),
    "/samples/scenarios.json": (SAMPLES / "scenarios.json", "application/json; charset=utf-8"),
    "/samples/partial_assignment.json": (
        ROOT / "examples" / "partial_assignment.json",
        "application/json; charset=utf-8",
    ),
    "/samples/partial_roster.json": (
        ROOT / "examples" / "partial_roster.json",
        "application/json; charset=utf-8",
    ),
    "/samples/roster.json": (ROOT / "examples" / "roster.json", "application/json; charset=utf-8"),
    "/samples/roster-100-30.json": (
        SAMPLES / "roster-100-30.json",
        "application/json; charset=utf-8",
    ),
}
MAX_BODY = 64 * 1024
MAX_JSON_BODY = 2 * 1024 * 1024
READ_TIMEOUT = 5


class DemoInputError(ValueError):
    def __init__(self, pointer):
        self.pointer = pointer


def require(condition, pointer):
    if not condition:
        raise DemoInputError(pointer)


def fixed(value, expected, pointer):
    """固定値・未知フィールドを、補正せず照合する。"""
    require(type(value) is type(expected), pointer)
    if isinstance(expected, dict):
        require(value.keys() == expected.keys(), pointer)
        for key in expected:
            fixed(value[key], expected[key], f"{pointer}/{key}")
    elif isinstance(expected, list):
        require(len(value) == len(expected), pointer)
        for index, item in enumerate(expected):
            fixed(value[index], item, f"{pointer}/{index}")
    else:
        require(value == expected, pointer)


def validate_demo(request):
    require(isinstance(request, dict) and request.keys() == BASELINE.keys(), "")
    for key in BASELINE.keys() - {"request_id", "employees", "demand"}:
        fixed(request[key], BASELINE[key], f"/{key}")
    require(
        isinstance(request["request_id"], str) and 1 <= len(request["request_id"]) <= 100,
        "/request_id",
    )
    for collection in ("employees", "demand"):
        items = request[collection]
        expected = {item["id"]: item for item in BASELINE[collection]}
        require(isinstance(items, list) and len(items) == len(expected), f"/{collection}")
        seen = set()
        for index, item in enumerate(items):
            pointer = f"/{collection}/{index}"
            require(isinstance(item, dict), pointer)
            item_id = item.get("id")
            require(isinstance(item_id, str) and item_id in expected, pointer + "/id")
            require(item_id not in seen, pointer + "/id")
            seen.add(item_id)
            original = expected[item_id]
            require(item.keys() == original.keys(), pointer)
            if collection == "demand":
                for key in original.keys() - {"required_people"}:
                    fixed(item[key], original[key], f"{pointer}/{key}")
                people = item["required_people"]
                require(type(people) is int and 0 <= people <= 6, pointer + "/required_people")
                continue
            label = item["label"]
            require(isinstance(label, str) and 1 <= len(label.strip()) <= 20, pointer + "/label")
            skills = item["skills"]
            require(isinstance(skills, list) and len(skills) <= 3, pointer + "/skills")
            skill_ids = set()
            for skill_index, skill in enumerate(skills):
                skill_pointer = f"{pointer}/skills/{skill_index}"
                require(isinstance(skill, dict), skill_pointer)
                require(skill.keys() == {"skill_id", "level"}, skill_pointer)
                skill_id = skill["skill_id"]
                require(
                    isinstance(skill_id, str)
                    and skill_id in {value["id"] for value in BASELINE["skills"]}
                    and skill_id not in skill_ids,
                    skill_pointer + "/skill_id",
                )
                require(
                    type(skill["level"]) is int and skill["level"] == 1, skill_pointer + "/level"
                )
                skill_ids.add(skill_id)
            availability = item["availability"]
            require(
                isinstance(availability, list) and len(availability) <= 1, pointer + "/availability"
            )
            if availability:
                interval = availability[0]
                interval_pointer = pointer + "/availability/0"
                require(
                    isinstance(interval, dict) and interval.keys() == {"start", "end"},
                    interval_pointer,
                )
                for key in ("start", "end"):
                    require(interval[key] in TIMES, f"{interval_pointer}/{key}")
                require(interval["start"] < interval["end"], interval_pointer + "/end")


class DemoServer(ThreadingHTTPServer):
    def __init__(self, port=8765):
        self.solve_lock = Lock()
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(READ_TIMEOUT)
        super().setup()

    def log_message(self, *_):
        pass

    def send_error(self, code, message=None, explain=None):
        if code == 501:
            self.unsupported()
        else:
            self.error(code, "INVALID_HTTP_REQUEST", "HTTP リクエストを確認してください。")

    def send_content(self, status, content, media_type):
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(content)
        except BrokenPipeError, ConnectionResetError, TimeoutError:
            pass

    def send_json(self, status, value):
        self.send_content(
            status,
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def error(self, status, code, message, pointer=None):
        self.send_json(
            status, {"error": {"code": code, "message": message, "json_pointer": pointer}}
        )

    def allowed_origin(self):
        host = f"127.0.0.1:{self.server.server_port}"
        origins = self.headers.get_all("Origin", [])
        if self.headers.get_all("Host", []) != [host] or origins not in ([], [f"http://{host}"]):
            self.error(403, "FORBIDDEN_ORIGIN", "このローカル画面からのみ利用できます。")
            return False
        return True

    def do_GET(self):
        if not self.allowed_origin():
            return
        if self.path not in FILES:
            self.error(404, "NOT_FOUND", "配信対象のファイルではありません。")
            return
        path, media_type = FILES[self.path]
        try:
            self.send_content(200, path.read_bytes(), media_type)
        except OSError:
            self.error(500, "SERVER_ERROR", "画面ファイルを読み取れませんでした。")

    def do_POST(self):
        if not self.allowed_origin():
            return
        if self.path not in {"/solve", "/solve-json"}:
            self.error(404, "NOT_FOUND", "計算入口は /solve または /solve-json です。")
            return
        if self.headers.get_all("Transfer-Encoding"):
            self.error(400, "INVALID_BODY", "転送エンコーディングは受理できません。")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
            self.error(400, "INVALID_BODY", "Content-Length を一つ指定してください。")
            return
        length = int(lengths[0])
        limit = MAX_JSON_BODY if self.path == "/solve-json" else MAX_BODY
        if length > limit:
            self.error(413, "BODY_TOO_LARGE", f"本文は{limit // 1024} KiB以下にしてください。")
            return
        if (
            len(self.headers.get_all("Content-Type", [])) != 1
            or self.headers.get_content_type() != "application/json"
            or self.headers.get_content_charset("utf-8") != "utf-8"
        ):
            self.error(
                415, "UNSUPPORTED_MEDIA_TYPE", "UTF-8 の application/json を指定してください。"
            )
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                self.error(400, "INVALID_BODY", "本文を最後まで読み取れませんでした。")
                return
            request = load_json(body.decode("utf-8"))
            if self.path == "/solve":
                validate_demo(request)
        except UnicodeError, RecursionError:
            self.error(400, "INVALID_JSON", "UTF-8 JSON を読み取れません。")
            return
        except TimeoutError:
            self.error(400, "READ_TIMEOUT", "本文の読み取り期限を超えました。")
            return
        except InvalidInput as error:
            item = error.diagnostics[0]
            self.error(400, item["code"], item["message"], item["json_pointer"])
            return
        except DemoInputError as error:
            self.error(
                400,
                "DEMO_INPUT_OUT_OF_RANGE",
                "編集範囲と固定値を確認してください。",
                error.pointer,
            )
            return
        # ponytail: ローカル試用では同時1件。公開・並列実行時はプロセス分離を設計する。
        if not self.server.solve_lock.acquire(blocking=False):
            self.error(503, "BUSY", "別の計算を実行中です。少し待って再計算してください。")
            return
        try:
            try:
                result = solve(request)
            finally:
                self.server.solve_lock.release()
            self.send_json(200, result)
        except Exception:
            self.error(500, "SERVER_ERROR", "実行入口で計算に失敗しました。再計算してください。")

    def unsupported(self):
        if self.allowed_origin():
            self.error(405, "METHOD_NOT_ALLOWED", "GET または POST を指定してください。")

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = unsupported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port は1〜65535で指定してください。")
    with DemoServer(args.port) as server:
        print(
            f"http://127.0.0.1:{server.server_port} を開いてください。終了は Ctrl+C。", flush=True
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
