"""公開型による、分割入力・確認・実行記録と再検証の利用例。"""

from shift_schedula import (
    assemble,
    confirm_source,
    confirmation_state,
    record_view,
    reverify_record,
    run_draft,
    split_request,
)
from shift_schedula.types import Request, RequestDraft, RunRecord


def confirmed_input(request: Request) -> RequestDraft:
    draft = split_request(request)
    for source in draft["sources"]:
        draft = confirm_source(draft, source["id"])
    return draft


def execute(request: Request) -> RunRecord:
    draft = confirmed_input(request)
    print(confirmation_state(draft))
    assembled = assemble(draft)
    if assembled["request"] is None:
        raise ValueError(assembled["diagnostics"])
    record = run_draft(draft)
    checked = reverify_record(record)
    if checked["current_verification"] is not None:
        print(checked["current_verification"]["status"])
    print(record_view(record)["current_status"])
    return record
