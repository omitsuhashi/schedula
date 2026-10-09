import argparse
import json
import sys
from pathlib import Path

from . import adapter_cli, get_schema, solve, verify
from .contract import SCHEMA_VERSIONS, InvalidInput, diagnostic, load_json
from .engine import response, validate_response
from .verify import verification_response


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
    schema_parser.add_argument("--schema-version", choices=SCHEMA_VERSIONS, default="0.15")
    adapter_cli.register(commands)
    args = parser.parse_args()
    if args.command == "adapter":
        return adapter_cli.handle(args)
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
                result = verification_response(request, diagnostics)
            else:
                result = response(None, "INVALID_INPUT", diagnostics)
        if args.command != "verify":
            validate_response(result)
        exit_code = 0 if result["status"] in {"OPTIMAL", "FEASIBLE", "VALID"} else 2
    print(json.dumps(result, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
