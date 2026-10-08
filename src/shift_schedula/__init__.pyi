from typing import Literal

from .types import (
    Baseline,
    ContinuitySolution,
    Diagnostic,
    ExtendedSolution,
    Request010,
    Request011,
    Request012,
    Request04,
    Request05,
    Request06,
    Request07,
    Request08,
    Request09,
    SchemaVersion,
    Solution,
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
    schema_version: SchemaVersion = "0.1",
) -> dict[str, JSONValue]: ...
def make_baseline(
    request: Request04
    | Request05
    | Request06
    | Request07
    | Request08
    | Request09
    | Request010
    | Request011
    | Request012,
    solution: ExtendedSolution | ContinuitySolution,
    plan_id: str,
) -> Baseline: ...
