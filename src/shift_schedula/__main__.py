import argparse
import json
import sys
from pathlib import Path

from . import get_schema, solve, verify
from .contract import SCHEMA_VERSIONS, InvalidInput, diagnostic, load_json, schema_version_of
from .engine import response, validate_response


def main():
    parser = argparse.ArgumentParser(prog="python -m shift_schedula")
    commands = parser.add_subparsers(dest="command", required=True)
    solve_parser = commands.add_parser("solve")
    solve_parser.add_argument("input_file")
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("input_file")
    verify_parser.add_argument("solution_file")
    schema_parser = commands.add_parser("schema")
    schema_parser.add_argument("kind", choices=["request", "response", "solution", "verification"])
    schema_parser.add_argument("--schema-version", choices=SCHEMA_VERSIONS, default="0.1")
    args = parser.parse_args()
    if args.command == "schema":
        result, exit_code = get_schema(args.kind, args.schema_version), 0
    else:
        if args.command == "verify" and args.input_file == args.solution_file == "-":
            parser.error("標準入力は Request または Solution の一方だけに指定します。")

        def read(path):
            return load_json(
                sys.stdin.buffer.read().decode("utf-8")
                if path == "-"
                else Path(path).read_text(encoding="utf-8")
            )

        request = None
        try:
            request = read(args.input_file)
            result = (
                verify(request, read(args.solution_file))
                if args.command == "verify"
                else solve(request)
            )
        except (InvalidInput, OSError, UnicodeError) as error:
            diagnostics = (
                error.diagnostics
                if isinstance(error, InvalidInput)
                else [diagnostic("INPUT_READ_ERROR", "UTF-8 の入力ファイルを読み取れません。")]
            )
            if args.command == "verify":
                result = verify(None, None)
                result.update(
                    schema_version=schema_version_of(request),
                    diagnostics=diagnostics,
                    request_id=request.get("request_id")
                    if isinstance(request, dict) and isinstance(request.get("request_id"), str)
                    else None,
                )
                if result["schema_version"] in {"0.5", "0.6"}:
                    result["priority_summary"] = None
                if result["schema_version"] == "0.6":
                    result["continuity_summary"] = None
            else:
                result = response(None, "INVALID_INPUT", diagnostics)
        if args.command != "verify":
            validate_response(result)
        exit_code = 0 if result["status"] in {"OPTIMAL", "FEASIBLE", "VALID"} else 2
    print(json.dumps(result, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
