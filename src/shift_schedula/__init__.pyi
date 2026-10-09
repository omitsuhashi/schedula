from os import PathLike
from typing import Literal

from .types import (
    Assembly,
    Baseline,
    ConfirmationState,
    Diagnostic,
    InputSource,
    RecordVerification,
    RecordView,
    RequestDraft,
    RunRecord,
    SchemaVersion,
    Solution,
    SourceLocation,
)
from .types import (
    JSONValue as JSONValue,
)
from .types import (
    Request as Request,
)
from .types import (
    Response as Response,
)
from .types import (
    Validation as Validation,
)
from .types import (
    Verification as Verification,
)

class InvalidInput(ValueError):
    diagnostics: list[Diagnostic]
    def __init__(self, diagnostics: list[Diagnostic]) -> None: ...

def solve(request: Request, *, num_workers: int = 2) -> Response: ...
def verify(request: Request, solution: Solution) -> Verification: ...
def validate(request: object) -> Validation: ...
def load_json(text: str) -> JSONValue: ...
def get_schema(
    kind: Literal["request", "response", "solution", "verification"],
    schema_version: SchemaVersion = "0.15",
) -> dict[str, JSONValue]: ...
def make_baseline(
    request: Request,
    solution: Solution,
    plan_id: str,
) -> Baseline: ...
def get_adapter_schema(kind: Literal["draft", "manifest", "record"]) -> dict[str, JSONValue]: ...
def split_request(request: Request) -> RequestDraft: ...
def import_request(request: Request) -> RequestDraft: ...
def confirmation_state(draft: RequestDraft) -> list[ConfirmationState]: ...
def confirm_source(draft: RequestDraft, source_id: str) -> RequestDraft: ...
def assemble(draft: RequestDraft) -> Assembly: ...
def read_draft(path: str | PathLike[str]) -> RequestDraft: ...
def run_draft(draft: RequestDraft, *, num_workers: int = 2) -> RunRecord: ...
def create_record(
    request: Request,
    response: Response,
    provenance: dict[str, list[SourceLocation]] | None = None,
    sources: list[InputSource] | tuple[()] = (),
    *,
    num_workers: int = 2,
    draft: RequestDraft | None = None,
) -> RunRecord: ...
def check_record(record: RunRecord) -> RunRecord: ...
def reverify_record(
    record: RunRecord, *, solution: Solution | None = None
) -> RecordVerification: ...
def record_view(record: RunRecord, *, solution: Solution | None = None) -> RecordView: ...
def save_json(
    path: str | PathLike[str],
    value: object,
    *,
    overwrite: bool = False,
    protected: list[str | PathLike[str]] | tuple[()] = (),
) -> None: ...
