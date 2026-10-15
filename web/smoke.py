"""実コンテナー内で3教材の公開APIと独立検証を確認する。"""

import argparse
import hashlib
import json
from urllib.request import Request, urlopen

from web.handler import PREFIX, lambda_handler
from web.lessons import PUBLIC_IDS, SAMPLES, sample

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", action="store_true")
    options = parser.parse_args()
    for lesson_id in PUBLIC_IDS:
        value = sample(lesson_id)
        if lesson_id == "verify":
            value = {
                "request": value,
                "solution": json.loads((SAMPLES / "manual-verify.solution.json").read_text()),
            }
        body = json.dumps(value, ensure_ascii=False)
        host = "example.lambda-url.ap-northeast-1.on.aws"
        if not options.public:
            result = lambda_handler(
                {
                    "rawPath": PREFIX + ("verify-json" if lesson_id == "verify" else "solve-json"),
                    "requestContext": {"http": {"method": "POST"}, "domainName": host},
                    "headers": {
                        "host": host,
                        "origin": "https://the3.co.jp",
                        "content-type": "application/json",
                        "x-demo-lesson": lesson_id,
                        "x-amz-content-sha256": hashlib.sha256(body.encode()).hexdigest(),
                    },
                    "body": body,
                },
                None,
            )
        if options.public:
            request = Request(
                "https://the3.co.jp"
                + PREFIX
                + ("verify-json" if lesson_id == "verify" else "solve-json"),
                data=body.encode(),
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://the3.co.jp",
                    "X-Demo-Lesson": lesson_id,
                    "X-Amz-Content-Sha256": hashlib.sha256(body.encode()).hexdigest(),
                },
            )
            with urlopen(request, timeout=40) as received:
                result = {"statusCode": received.status, "body": received.read().decode()}
        assert result["statusCode"] == 200, result
        assert json.loads(result["body"])["verification"]["valid"], result
        print(f"{lesson_id}: verified")
