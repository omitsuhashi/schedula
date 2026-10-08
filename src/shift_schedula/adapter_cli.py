"""分割入力の明示操作を提供するCLI。従来のコマンドは変更しない。"""

import json

from .adapter import (
    assemble,
    confirm_source,
    get_adapter_schema,
    import_request,
    split_request,
)
from .contract import InvalidInput, diagnostic
from .records import (
    draft_paths,
    read_draft,
    read_json_file,
    record_view,
    reverify_record,
    run_draft,
    save_json,
)


def register(commands):
    parser = commands.add_parser("adapter")
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("split", "import", "confirm", "assemble", "solve", "verify-record", "view"):
        command = actions.add_parser(name)
        command.add_argument("input_file")
        command.add_argument("--output")
        command.add_argument("--overwrite", action="store_true")
        if name == "confirm":
            command.add_argument("source_id")
        if name == "assemble":
            command.add_argument("--request-only", action="store_true")
        if name == "solve":
            command.add_argument("--num-workers", type=int, default=2)
        if name in {"verify-record", "view"}:
            command.add_argument("--solution")
    command = actions.add_parser("schema")
    command.add_argument("kind", choices=["draft", "manifest", "record"])


def handle(args):
    try:
        protected = []
        if args.action == "schema":
            result, status = get_adapter_schema(args.kind), "VALID"
        else:
            protected = draft_paths(args.input_file)
            if args.action in {"split", "import"}:
                request, _ = read_json_file(args.input_file)
                result = (split_request if args.action == "split" else import_request)(request)
                status = "VALID"
            elif args.action in {"confirm", "assemble", "solve"}:
                draft = read_draft(args.input_file)
                if args.action == "confirm":
                    result, status = confirm_source(draft, args.source_id), "VALID"
                elif args.action == "assemble":
                    result = assemble(draft)
                    status = result["status"]
                    if args.request_only and status == "VALID":
                        result = result["request"]
                else:
                    result = run_draft(draft, num_workers=args.num_workers)
                    status = result["response"]["status"]
            else:
                if args.input_file == args.solution == "-":
                    raise InvalidInput(
                        [diagnostic("STDIN_CONFLICT", "標準入力は一件に指定します。")]
                    )
                record, _ = read_json_file(args.input_file)
                solution = None
                if args.solution:
                    solution, _ = read_json_file(args.solution)
                    protected.extend(draft_paths(args.solution))
                if args.action == "view":
                    result = record_view(record, solution=solution)
                    status = result["current_status"]
                else:
                    result = reverify_record(record, solution=solution)
                    current = result["current_verification"]
                    status = current["status"] if current else "NOT_PERFORMED"
            if args.output:
                save_json(args.output, result, overwrite=args.overwrite, protected=protected)
        exit_code = 0 if status in {"VALID", "OPTIMAL", "FEASIBLE"} else 2
    except (InvalidInput, OSError, UnicodeError, RecursionError) as error:
        result = {
            "status": "INVALID_INPUT",
            "diagnostics": error.diagnostics
            if isinstance(error, InvalidInput)
            else [diagnostic("ADAPTER_IO_ERROR", "UTF-8の読み取り/安全な保存に失敗しました。")],
        }
        exit_code = 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return exit_code
