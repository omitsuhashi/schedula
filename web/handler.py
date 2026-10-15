"""Lambda Function URLの公開デモ入口。AWSリソースへのアクセスは行わない。"""

import base64
import binascii
import hashlib
import json
import re
import subprocess
import sys

from shift_schedula import load_json
from shift_schedula.contract import InvalidInput
from web.lessons import LESSONS, ROOT, validate_public

PREFIX = "/products/schedula/api/"
MAX_BODY = 64 * 1024
MAX_RESPONSE = 1024 * 1024
WORKER_TIMEOUT = 20


def response(status, value):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
        "body": json.dumps(value, ensure_ascii=False, allow_nan=False),
        "isBase64Encoded": False,
    }


def error(status, code, message):
    return response(status, {"error": {"code": code, "message": message}})


def lambda_handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    path = event.get("rawPath", "")
    if path not in {PREFIX + "solve-json", PREFIX + "verify-json"}:
        return error(404, "NOT_FOUND", "公開していない実行入口です。")
    if http.get("method") != "POST":
        return error(405, "METHOD_NOT_ALLOWED", "POSTで送信してください。")
    headers = {key.lower(): value for key, value in event.get("headers", {}).items()}
    host = event.get("requestContext", {}).get("domainName", "")
    if (
        not re.fullmatch(r"[a-z0-9]+\.lambda-url\.ap-northeast-1\.on\.aws", host)
        or headers.get("host") != host
        or headers.get("origin") != "https://the3.co.jp"
    ):
        return error(403, "FORBIDDEN_ORIGIN", "公開デモから送信してください。")
    lesson_id = headers.get("x-demo-lesson")
    if lesson_id not in LESSONS or (lesson_id == "verify") != path.endswith("verify-json"):
        return error(400, "INVALID_LESSON", "公開教材と操作を指定してください。")
    if headers.get("content-type", "").lower() not in {
        "application/json",
        "application/json; charset=utf-8",
    }:
        return error(415, "UNSUPPORTED_MEDIA_TYPE", "UTF-8のJSONで送信してください。")
    try:
        body = event.get("body", "")
        if not isinstance(body, str) or len(body) > MAX_BODY * 2:
            return error(413, "BODY_TOO_LARGE", "本文は64 KiB以下にしてください。")
        raw = (
            base64.b64decode(body, validate=True)
            if event.get("isBase64Encoded")
            else body.encode("utf-8")
        )
        if len(raw) > MAX_BODY:
            return error(413, "BODY_TOO_LARGE", "本文は64 KiB以下にしてください。")
        if headers.get("x-amz-content-sha256") != hashlib.sha256(raw).hexdigest():
            return error(400, "INVALID_BODY_HASH", "本文のSHA-256を確認してください。")
        value = load_json(raw.decode("utf-8"))
        validate_public(lesson_id, value)
    except (
        UnicodeError,
        binascii.Error,
        InvalidInput,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        RecursionError,
    ):
        return error(400, "DEMO_INPUT_OUT_OF_RANGE", "公開教材の編集範囲とJSONを確認してください。")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "web.worker", LESSONS[lesson_id]["operation"]],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=ROOT,
            timeout=WORKER_TIMEOUT,
            check=True,
        )
        if len(completed.stdout) > MAX_RESPONSE:
            return error(502, "RESPONSE_TOO_LARGE", "公開デモの応答上限を超えました。")
        return response(200, load_json(completed.stdout.decode("utf-8")))
    except subprocess.TimeoutExpired:
        # subprocess.runは期限超過時に子をkillし、waitしてから例外を返す。
        return error(504, "DEADLINE_EXCEEDED", "計算の総期限を超えました。再実行できます。")
    except OSError, subprocess.CalledProcessError, InvalidInput, UnicodeError:
        return error(502, "WORKER_ERROR", "計算を完了できませんでした。再実行できます。")
