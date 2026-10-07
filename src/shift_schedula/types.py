"""JSON契約の公開型。範囲・参照・業務上の整合はvalidateで確認する。"""

from typing import Literal, NotRequired, TypedDict

type SchemaVersion = Literal["0.1", "0.2", "0.3", "0.4"]
type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
type FailureStatus = Literal[
    "INFEASIBLE", "UNKNOWN", "INVALID_INPUT", "BACKEND_UNAVAILABLE", "INTERNAL_ERROR"
]


class Interval(TypedDict):
    start: str
    end: str


class PlanningWindow(Interval):
    timezone: str
    slot_minutes: Literal[5, 10, 15, 20, 30, 60]


class Skill(TypedDict):
    id: str
    label: str


class RequiredSkill(TypedDict):
    skill_id: str
    min_level: int


class EmployeeSkill(TypedDict):
    skill_id: str
    level: int


class Role(Skill):
    required_skills: list[RequiredSkill]


class History01(TypedDict):
    last_shift_end: str | None
    consecutive_work_days_before_window: int


class History(History01):
    last_work_day: str | None


class EmployeeFields(Skill):
    skills: list[EmployeeSkill]
    availability: list[Interval]


class Employee01(EmployeeFields):
    history: NotRequired[History01]


class Employee(EmployeeFields):
    history: NotRequired[History]


class Demand(TypedDict):
    id: str
    role_id: str
    interval: Interval
    required_people: int


class Segment(TypedDict):
    interval: Interval
    breaks: list[Interval]


class CandidateFields(TypedDict):
    id: str
    employee_id: str


class ShiftCandidate01(CandidateFields, Segment):
    pass


class ShiftCandidate(CandidateFields):
    segments: list[Segment]


class BreakOption(TypedDict):
    offset_minutes: int
    duration_minutes: int


class SegmentOption(BreakOption):
    breaks: list[BreakOption]


class TemplateFields(TypedDict):
    id: str
    employee_ids: list[str]
    dates: list[str]
    start_times: list[str]


class ShiftTemplate01(TemplateFields):
    duration_minutes_options: list[int]
    break_options: list[BreakOption]


class ShiftTemplate(TemplateFields):
    segment_options: list[list[SegmentOption]]


class ConstraintFields(TypedDict):
    id: str
    employee_ids: list[str]


class MinutesConstraint(ConstraintFields):
    type: Literal["max_assigned_minutes", "max_scheduled_minutes", "min_rest_minutes"]
    limit_minutes: int


class ConsecutiveDaysConstraint(ConstraintFields):
    type: Literal["max_consecutive_days"]
    limit_days: int


class RoleSwitchConstraint(ConstraintFields):
    type: Literal["max_role_switches"]
    limit_count: int


class SplitGapConstraint(ConstraintFields):
    type: Literal["min_split_gap_minutes"]
    limit_minutes: int


class ScheduledMinutesBounds(ConstraintFields):
    type: Literal["scheduled_minutes_bounds"]
    interval: Interval
    min_minutes: NotRequired[int]
    max_minutes: NotRequired[int]


type Constraint01 = MinutesConstraint | ConsecutiveDaysConstraint | RoleSwitchConstraint
type Constraint = Constraint01 | SplitGapConstraint
type Constraint04 = Constraint | ScheduledMinutesBounds


class PreferenceFields(TypedDict):
    id: str
    employee_ids: list[str]
    penalty_per_minute: int


class AvoidRole(PreferenceFields):
    type: Literal["avoid_role"]
    role_id: str


class WorkPreference(PreferenceFields):
    type: Literal["prefer_work", "avoid_work"]
    interval: Interval


class Objective01(TypedDict):
    id: str
    metric: Literal["preference_penalty", "scheduled_minutes", "role_switches"]


class Objective(TypedDict):
    id: str
    metric: Literal[
        "preference_penalty",
        "scheduled_minutes",
        "role_switches",
        "fairness_deviation_minutes",
        "plan_changes",
    ]


class SolverOptions(TypedDict):
    backend: Literal["auto", "min_cost_flow", "cp_sat"]
    time_limit_seconds: float
    seed: int


class EmployeeTarget(TypedDict):
    employee_id: str
    target_minutes: int


class Fairness(TypedDict):
    evaluation_period: Interval
    employee_targets: list[EmployeeTarget]


class FixedPart(TypedDict):
    id: str
    employee_id: str
    interval: Interval
    components: list[Literal["work", "role"]]


class FixedState(TypedDict):
    employee_id: str
    interval: Interval
    work: NotRequired[Literal["off", "work", "break"]]
    role: NotRequired[str | None]


class SnapshotOrigin(TypedDict):
    request_id: str
    baseline_plan_id: str | None
    replan_mode: Literal["preserve_assigned", "rebuild"] | None


class Baseline(TypedDict):
    plan_id: str
    source_request: Request
    source_solution: Solution
    source_fixed_states: NotRequired[list[FixedState]]
    snapshot_origin: NotRequired[SnapshotOrigin]


class ConditionEdit(TypedDict):
    json_pointer: str
    value: int


class AllowedChange(TypedDict):
    id: str
    edits: list[ConditionEdit]


class DiagnosisOptions(TypedDict):
    time_limit_seconds: float
    max_suggestions: int
    allowed_changes: list[AllowedChange]


class RequestFields(TypedDict):
    request_id: str
    problem_type: Literal["assignment", "roster"]
    planning_window: PlanningWindow
    skills: list[Skill]
    roles: list[Role]
    demand: list[Demand]
    solver: SolverOptions


class Request01(RequestFields):
    schema_version: Literal["0.1"]
    employees: list[Employee01]
    shift_candidates: list[ShiftCandidate01]
    shift_templates: NotRequired[list[ShiftTemplate01]]
    constraints: list[Constraint01]
    preferences: list[AvoidRole]
    objectives: list[Objective01]


class ExtendedRequestFields(RequestFields):
    employees: list[Employee]
    shift_candidates: list[ShiftCandidate]
    shift_templates: NotRequired[list[ShiftTemplate]]
    objectives: list[Objective]
    fairness: NotRequired[Fairness]
    baseline: NotRequired[Baseline]
    fixed_parts: NotRequired[list[FixedPart]]
    diagnosis: NotRequired[DiagnosisOptions]


class Request02(ExtendedRequestFields):
    schema_version: Literal["0.2"]
    constraints: list[Constraint]
    preferences: list[AvoidRole]


class Request03(ExtendedRequestFields):
    schema_version: Literal["0.3"]
    constraints: list[Constraint]
    preferences: list[AvoidRole]


class Request04(ExtendedRequestFields):
    schema_version: Literal["0.4"]
    constraints: list[Constraint04]
    preferences: list[AvoidRole | WorkPreference]
    replan_mode: NotRequired[Literal["preserve_assigned", "rebuild"]]


type Request = Request01 | Request02 | Request03 | Request04


class Assignment(TypedDict):
    employee_id: str
    role_id: str
    interval: Interval


class ShiftFields(TypedDict):
    candidate_id: str
    employee_id: str


class Shift01(ShiftFields, Segment):
    pass


class Shift(ShiftFields):
    work_day: str
    segments: list[Segment]


class Solution01(TypedDict):
    assignments: list[Assignment]
    shifts: list[Shift01]


class ExtendedSolution(TypedDict):
    assignments: list[Assignment]
    shifts: list[Shift]


type Solution = Solution01 | ExtendedSolution


class Fact(TypedDict):
    name: str
    value: str | float | bool | None


class Diagnostic(TypedDict):
    code: str
    message: str
    json_pointer: str
    related_ids: list[str]
    facts: list[Fact]


class VerificationDetails(TypedDict):
    performed: bool
    valid: bool | None
    violations: list[Diagnostic]


class Stats(TypedDict):
    elapsed_seconds: float


class SolverDetails(TypedDict):
    backend: Literal["none", "min_cost_flow", "cp_sat"]
    engine_version: str
    library_version: str | None
    selection_reason: str


class ObjectiveValue(TypedDict):
    id: str
    metric: str
    value: int
    proven_optimal: bool


class EmployeeFairness(EmployeeTarget):
    scheduled_minutes: int
    deviation_minutes: int


class FairnessSummary(TypedDict):
    evaluation_period: Interval
    scale: Literal["absolute_minutes"]
    normalized: Literal[False]
    employees: list[EmployeeFairness]


class ChangeSummary(TypedDict):
    plan_id: str
    unit: Literal["slot_components"]
    work_changes: int
    role_changes: int
    total_changes: int


class Shortage(TypedDict):
    demand_id: str
    role_id: str
    interval: Interval
    required_people: int
    assigned_people: int
    missing_people: int


class ShortageSummary(TypedDict):
    total_person_minutes: int
    proven_minimal: bool
    shortages: list[Shortage]


class ConflictCondition(TypedDict):
    code: str
    json_pointer: str
    related_ids: list[str]
    interval: Interval | None


class Conflict(TypedDict):
    conditions: list[ConflictCondition]
    infeasibility_proven: Literal[True]
    minimality: Literal["not_proven"]


class Suggestion(TypedDict):
    option_id: str
    modified_request: Request
    response: Response


class DiagnosisResult(TypedDict):
    status: Literal["COMPLETE", "TIME_LIMIT", "ERROR", "UNSUPPORTED", "NOT_APPLICABLE"]
    reason: str | None
    conflict: Conflict | None
    suggestions: list[Suggestion]
    suggestion_minimality: Literal["not_proven"]
    time_limit_seconds: float
    elapsed_seconds: float
    diagnostics: list[Diagnostic]


class ResponseFields(TypedDict):
    request_id: str | None
    solver: SolverDetails
    objectives: list[ObjectiveValue]
    diagnostics: list[Diagnostic]
    verification: VerificationDetails
    stats: Stats


class ExtendedResponseFields(ResponseFields):
    fairness_summary: FairnessSummary | None
    change_summary: ChangeSummary | None
    diagnosis_result: DiagnosisResult | None


class PartialResponseFields(ExtendedResponseFields):
    shortage_summary: ShortageSummary | None


class Response01Success(ResponseFields):
    schema_version: Literal["0.1"]
    status: Literal["OPTIMAL", "FEASIBLE"]
    solution: Solution01


class Response01Failure(ResponseFields):
    schema_version: Literal["0.1"]
    status: FailureStatus
    solution: None


class Response02Success(ExtendedResponseFields):
    schema_version: Literal["0.2"]
    status: Literal["OPTIMAL", "FEASIBLE"]
    solution: ExtendedSolution


class Response02Failure(ExtendedResponseFields):
    schema_version: Literal["0.2"]
    status: FailureStatus
    solution: None


class Response03Success(PartialResponseFields):
    schema_version: Literal["0.3"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ExtendedSolution


class Response03Failure(PartialResponseFields):
    schema_version: Literal["0.3"]
    status: FailureStatus
    solution: None


class Response04Success(PartialResponseFields):
    schema_version: Literal["0.4"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ExtendedSolution


class Response04Failure(PartialResponseFields):
    schema_version: Literal["0.4"]
    status: FailureStatus
    solution: None


type Response = (
    Response01Success
    | Response01Failure
    | Response02Success
    | Response02Failure
    | Response03Success
    | Response03Failure
    | Response04Success
    | Response04Failure
)


class Verification(TypedDict):
    schema_version: SchemaVersion
    request_id: str | None
    status: Literal["VALID", "PARTIAL", "INVALID_INPUT", "INVALID_PLAN", "INTERNAL_ERROR"]
    verification: VerificationDetails
    demand_satisfied: bool | None
    objectives: list[ObjectiveValue]
    shortage_summary: ShortageSummary | None
    fairness_summary: FairnessSummary | None
    change_summary: ChangeSummary | None
    diagnostics: list[Diagnostic]
    stats: Stats


class Validation(TypedDict):
    schema_version: SchemaVersion
    request_id: str | None
    status: Literal["VALID", "INVALID_INPUT", "INTERNAL_ERROR"]
    diagnostics: list[Diagnostic]
    stats: Stats
