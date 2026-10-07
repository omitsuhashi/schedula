from typing import Literal

from .types import (
    Baseline,
    Diagnostic,
    ExtendedSolution,
    Request04,
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

def solve(request: Request) -> Response: ...
def verify(request: Request, solution: Solution) -> Verification: ...
def validate(request: object) -> Validation: ...
def load_json(text: str) -> JSONValue: ...
def get_schema(
    kind: Literal["request", "response", "solution", "verification"],
    schema_version: SchemaVersion = "0.1",
) -> dict[str, JSONValue]: ...
def make_baseline(request: Request04, solution: ExtendedSolution, plan_id: str) -> Baseline: ...
