"""固定したアプリの保存境界で照合し、旧JSON/SQLiteの一セッションを別JSONへ移す。"""

import argparse
import copy
import json
import sqlite3
import sys
from pathlib import Path

if __package__:
    from .migrate_adapter import migrate_draft, migrate_record
    from .migrate_contract import migrate, migrate_request
else:
    from migrate_adapter import migrate_draft, migrate_record
    from migrate_contract import migrate, migrate_request

from shift_schedula import InvalidInput, load_json, validate
from shift_schedula.records import read_json_file, save_json


def migrate_document(document, source_engine, target_engine, restore):
    """原本・元証拠を保ち、確認と採用は既存アプリの境界へ委ねる。"""
    restore(copy.deepcopy(document), source_engine)
    target = copy.deepcopy(document)
    target["engine"] = {
        key: target_engine[key] for key in ("version", "schema_version", "commit", "sha256")
    }
    for plan in target["plans"]:
        original = copy.deepcopy(plan)
        if "record" in plan:
            result = migrate_record(plan.pop("record"))
        else:
            result = migrate(plan["request"], solution=plan["result"].get("solution"))
        plan["request"] = result["request"]
        checked = result["current_verification"]
        plan["result"] = (
            {**checked, "solution": result["solution"]}
            if checked is not None
            else {"status": "NO_PLAN", "solution": None}
        )
        # 元run_idを新Requestの実行記録に付け替えない。
        evidence = original.get("evidence", original["result"])
        plan["evidence"] = {
            **(evidence if isinstance(evidence, dict) else {}),
            "migration": {"source_engine": document["engine"], "original_plan": original},
        }
        plan["evidence"].pop("solution", None)
        plan["current_verification"] = checked
    if target.get("request_draft") is not None:
        target["request_draft"] = migrate_draft(target["request_draft"])["draft"]
    # 未完成文字列は原文のまま。実行可能な入力だけ明示変換する。
    try:
        draft_input = load_json(target["input"])
    except InvalidInput:
        draft_input = None
    if isinstance(draft_input, dict) and validate(draft_input)["status"] == "VALID":
        target["input"] = json.dumps(migrate_request(draft_input), ensure_ascii=False, indent=2)
    if target["edit"] is not None:
        target["edit"]["request"] = migrate_request(target["edit"]["request"])
        # 対象のアプリ勤務計画0.2以降はsegments形式。修正途中を検証済みへ昇格しない。
    target.update(format="schedula-app/2", request_draft=target.get("request_draft"))
    return restore(target, target_engine)


def read_session(path, session_id):
    """DB Schema 1/2を読取専用トランザクションでJSON境界へ取り出す。"""
    path = Path(path).resolve(strict=True)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (1, 2) or db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("DB Schemaまたは整合性を確認できません。")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("DBの参照が不正です。")
        metadata = db.execute("SELECT engine FROM metadata").fetchall()
        if len(metadata) != 1:
            raise ValueError("エンジン固定情報が不正です。")
        columns = "input,selected,baseline,edit" + (",request_draft" if version == 2 else "")
        row = db.execute(f"SELECT {columns} FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise ValueError("指定したセッションがありません。")
        names = ["id", "label", "request", "result", "evidence"]
        if version == 2:
            names += ["record", "current_verification"]
        plans = []
        for values in db.execute(
            f"SELECT {','.join(names)} FROM plans WHERE session_id=? ORDER BY rowid", (session_id,)
        ):
            plans.append(
                {
                    key: value if key in ("id", "label") else load_json(value)
                    for key, value in zip(names, values, strict=True)
                    if value is not None
                }
            )
        result = {
            "format": f"schedula-app/{version}",
            "engine": load_json(metadata[0][0]),
            "input": row[0],
            "selected": row[1],
            "baseline": row[2],
            "edit": load_json(row[3]),
            "plans": plans,
        }
        if version == 2:
            result["request_draft"] = load_json(row[4])
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file")
    parser.add_argument("--session-id", help="SQLiteを入力にする場合の明示セッションID")
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--app-source", type=Path, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        sys.path.insert(0, str(args.app_source.resolve() / "backend"))
        from server import MAX_BODY_BYTES, runtime
        from workflow import restore

        source_engine, _ = read_json_file(args.source_manifest)
        target_engine = runtime()
        document = (
            read_session(args.input_file, args.session_id)
            if args.session_id is not None
            else read_json_file(args.input_file)[0]
        )
        result = migrate_document(document, source_engine, target_engine, restore)
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_BODY_BYTES:
            raise ValueError("移行JSONがアプリの本文上限を超えます。")
        save_json(args.output, result, protected=[args.input_file, args.source_manifest])
    except Exception:
        # 保存値・診断に含まれる個人情報をCLIへ展開しない。
        print(
            "移行できません。原本を保持して固定情報・入力・確認・出力先を確認してください。",
            file=sys.stderr,
        )
        return 2
    print(json.dumps({"status": "MIGRATED", "output": args.output, "plans": len(result["plans"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
