import argparse
import json
import sys
from pathlib import Path

from . import solve
from .contract import InvalidInput, diagnostic, get_schema, load_json
from .engine import response, validate_response


def main():
    parser = argparse.ArgumentParser(prog="python -m schedula")
    commands = parser.add_subparsers(dest="command", required=True)
    solve_parser = commands.add_parser("solve")
    solve_parser.add_argument("input_file")
    schema_parser = commands.add_parser("schema")
    schema_parser.add_argument("kind", choices=["request", "response"])
    args = parser.parse_args()
    if args.command == "schema":
        result, exit_code = get_schema(args.kind), 0
    else:
        try:
            text = (
                sys.stdin.buffer.read().decode("utf-8")
                if args.input_file == "-"
                else Path(args.input_file).read_text(encoding="utf-8")
            )
            result = solve(load_json(text))
        except InvalidInput as error:
            result = response(None, "INVALID_INPUT", error.diagnostics)
        except OSError, UnicodeError:
            result = response(
                None,
                "INVALID_INPUT",
                [diagnostic("INPUT_READ_ERROR", "UTF-8 の入力ファイルを読み取れません。")],
            )
        validate_response(result)
        exit_code = 0 if result["status"] in {"OPTIMAL", "FEASIBLE"} else 2
    print(json.dumps(result, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
