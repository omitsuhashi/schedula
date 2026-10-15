"""一つの公開教材を子プロセスで実行する。入力や結果は保存しない。"""

import json
import sys

from shift_schedula import load_json, solve, verify

if __name__ == "__main__":
    value = load_json(sys.stdin.read())
    result = (
        verify(value["request"], value["solution"])
        if sys.argv[1] == "verify"
        else solve(value, num_workers=1)
    )
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False))
