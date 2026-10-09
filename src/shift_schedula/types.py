"""JSON契約の公開型。範囲・参照・業務上の整合はvalidateで確認する。"""

from typing import Literal, NotRequired, TypedDict

type SchemaVersion = Literal["0.15"]


type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]


type FailureStatus = Literal[
    "INFEASIBLE", "UNKNOWN", "INVALID_INPUT", "BACKEND_UNAVAILABLE", "INTERNAL_ERROR"
]


class Interval(TypedDict):
    start: str
    end: str


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


class History(TypedDict):
    last_shift_end: str | None
    consecutive_work_days_before_window: int
    last_work_day: str | None


class EmployeeFields(Skill):
    skills: list[EmployeeSkill]
    availability: list[Interval]


class Employee(EmployeeFields):
    history: NotRequired[History]


class Demand(TypedDict):
    id: str
    role_id: str
    interval: Interval
    required_people: int


class PriorityDemand(Demand):
    priority: NotRequired[int]


class MinimumDemand(PriorityDemand):
    minimum_people: NotRequired[int]


class Segment(TypedDict):
    interval: Interval
    breaks: list[Interval]


class CandidateFields(TypedDict):
    id: str
    employee_id: str


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


class DayCountBounds(ConstraintFields):
    type: Literal["work_days_bounds", "days_off_bounds"]
    interval: Interval
    min_days: NotRequired[int]
    max_days: NotRequired[int]


class ShiftCategory(TypedDict):
    id: str
    label: str
    intervals: list[Interval]
    min_overlap_minutes: int


class PatternFields(ConstraintFields):
    evaluation_period: Interval


class ForbiddenShiftSuccessions(PatternFields):
    type: Literal["forbidden_shift_successions"]
    from_category_id: str
    to_category_id: str
    day_offset: int


class DaysOffAfterShift(PatternFields):
    type: Literal["days_off_after_shift"]
    category_id: str
    min_days: int


class MinConsecutiveDaysOff(PatternFields):
    type: Literal["min_consecutive_days_off"]
    min_days: int


class DateGroup(TypedDict):
    id: str
    dates: list[str]


class WorkedDateGroupsLimit(PatternFields):
    type: Literal["worked_date_groups_limit"]
    date_groups: list[DateGroup]
    max_groups: int


class RequiredCoworkers(ConstraintFields):
    type: Literal["required_coworkers"]
    interval: Interval
    coworker_ids: list[str]
    minimum_people: int


class IncompatibleEmployees(ConstraintFields):
    type: Literal["incompatible_employees"]
    interval: Interval


type Constraint = (
    MinutesConstraint
    | ConsecutiveDaysConstraint
    | RoleSwitchConstraint
    | SplitGapConstraint
    | ScheduledMinutesBounds
    | DayCountBounds
    | ForbiddenShiftSuccessions
    | DaysOffAfterShift
    | MinConsecutiveDaysOff
    | WorkedDateGroupsLimit
    | RequiredCoworkers
    | IncompatibleEmployees
)


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


class Objective(TypedDict):
    id: str
    metric: Literal[
        "preference_penalty",
        "scheduled_minutes",
        "role_switches",
        "fairness_deviation_minutes",
        "plan_changes",
    ]


class CostObjective(TypedDict):
    id: str
    metric: Literal["scheduled_cost"]


class DutyObjective(TypedDict):
    id: str
    metric: Literal["duty_deviation_minutes"]
    duty_id: str


class ShiftCountObjective(TypedDict):
    id: str
    metric: Literal["shift_count_deviation"]
    balance_id: str


class EmployeeCountTarget(TypedDict):
    employee_id: str
    target_count: int


class ShiftCountBalance(TypedDict):
    id: str
    label: str
    evaluation_period: Interval
    category_id: NotRequired[str]
    employee_targets: list[EmployeeCountTarget]


class EmployeeRate(TypedDict):
    employee_id: str
    units_per_minute: int


class Costs(TypedDict):
    currency: str
    units_per_currency: int
    employee_rates: list[EmployeeRate]


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


class DutyBalance(Fairness):
    id: str
    label: str
    intervals: list[Interval]


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


class ConflictRefinement(TypedDict):
    time_limit_seconds: float


class DiagnosisOptions(TypedDict):
    time_limit_seconds: float
    max_suggestions: int
    allowed_changes: list[AllowedChange]
    conflict_refinement: NotRequired[ConflictRefinement]


class ContinuityDuty(TypedDict):
    id: str
    segments: list[Segment]


class ContinuityEmployee(TypedDict):
    employee_id: str
    before_context: History
    past_complete: Literal[True]
    actual_shifts: list[ContinuityDuty]
    commitments_complete: Literal[True]
    committed_shifts: list[ContinuityDuty]


class Continuity(TypedDict):
    context_window: Interval
    employees: list[ContinuityEmployee]


class PlanningWindow(Interval):
    timezone: str
    slot_minutes: Literal[1, 5, 10, 15, 20, 30, 60]


class RosterRequestFields(TypedDict):
    request_id: str
    problem_type: Literal["assignment", "roster"]
    planning_window: PlanningWindow
    skills: list[Skill]
    roles: list[Role]
    solver: SolverOptions
    preferences: list[AvoidRole | WorkPreference]
    replan_mode: NotRequired[Literal["preserve_assigned", "rebuild"]]
    continuity: NotRequired[Continuity]
    employees: list[Employee]
    shift_candidates: list[ShiftCandidate]
    shift_templates: NotRequired[list[ShiftTemplate]]
    fairness: NotRequired[Fairness]
    baseline: NotRequired[Baseline]
    fixed_parts: NotRequired[list[FixedPart]]
    diagnosis: NotRequired[DiagnosisOptions]
    costs: NotRequired[Costs]
    duty_balance: NotRequired[list[DutyBalance]]


class Request015(RosterRequestFields):
    schema_version: Literal["0.15"]
    demand: list[MinimumDemand]
    constraints: list[Constraint]
    objectives: list[Objective | CostObjective | DutyObjective | ShiftCountObjective]
    shift_categories: NotRequired[list[ShiftCategory]]
    shift_count_balance: NotRequired[list[ShiftCountBalance]]


type Request = Request015


class Assignment(TypedDict):
    employee_id: str
    role_id: str
    interval: Interval


class ShiftFields(TypedDict):
    candidate_id: str
    employee_id: str


class Shift(ShiftFields):
    work_day: str
    segments: list[Segment]


class CommittedShift(TypedDict):
    committed_shift_id: str
    employee_id: str
    work_day: str
    segments: list[Segment]


class ContinuitySolution(TypedDict):
    assignments: list[Assignment]
    shifts: list[Shift | CommittedShift]


class ContinuityEmployeeSummary(TypedDict):
    employee_id: str
    historical_minutes: int
    planned_minutes: int
    outside_planning_minutes: int
    committed_shift_ids: list[str]


class ContinuitySummary(TypedDict):
    context_window: Interval
    planning_window: Interval
    employees: list[ContinuityEmployeeSummary]


type Solution = ContinuitySolution


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
    duty_id: NotRequired[str]
    balance_id: NotRequired[str]


class EmployeeCost(EmployeeRate):
    scheduled_minutes: int
    cost_units: int


class CostSummary(TypedDict):
    currency: str
    units_per_currency: int
    evaluation_period: Interval
    total_units: int
    employees: list[EmployeeCost]


class EmployeeDuty(EmployeeTarget):
    actual_minutes: int
    deviation_minutes: int


class DutyBalanceSummary(TypedDict):
    duty_id: str
    label: str
    evaluation_period: Interval
    intervals: list[Interval]
    unit: Literal["minutes"]
    scale: Literal["absolute_deviation"]
    normalized: Literal[False]
    total_deviation_minutes: int
    employees: list[EmployeeDuty]


class EmployeeShiftCount(EmployeeCountTarget):
    actual_count: int
    deviation_count: int


class ShiftCountBalanceSummary(TypedDict):
    id: str
    label: str
    evaluation_period: Interval
    category_id: NotRequired[str]
    unit: Literal["shifts"]
    scale: Literal["absolute_deviation"]
    normalized: Literal[False]
    total_deviation_count: int
    employees: list[EmployeeShiftCount]


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
    comparison_interval: NotRequired[Interval]
    slot_minutes: NotRequired[int]


class Shortage(TypedDict):
    demand_id: str
    role_id: str
    interval: Interval
    required_people: int
    assigned_people: int
    missing_people: int
    minimum_people: int


class ShortageSummary(TypedDict):
    total_person_minutes: int
    proven_minimal: bool
    shortages: list[Shortage]


class PriorityShortage(TypedDict):
    priority: int
    total_person_minutes: int
    proven_minimal: bool


class PrioritySummary(TypedDict):
    groups: list[PriorityShortage]


class ConflictCondition(TypedDict):
    code: str
    json_pointer: str
    related_ids: list[str]
    interval: Interval | None
    group_id: str


class ConflictCheck(TypedDict):
    phase: Literal["initial", "removal", "final", "witness_recheck"]
    active_groups: list[str]
    removed_group_id: str | None
    status: Literal["INFEASIBLE", "UNKNOWN", "FEASIBLE", "OPTIMAL"]
    witness_verified: bool | None
    completed_in_budget: bool
    elapsed_seconds: float
    preparation_elapsed_seconds: float
    search_elapsed_seconds: float
    verification_elapsed_seconds: float


class Conflict(TypedDict):
    conditions: list[ConflictCondition]
    background_conditions: list[ConflictCondition]
    infeasibility_proven: Literal[True]
    minimality: Literal["not_proven", "inclusion_minimal"]
    minimality_scope: Literal["condition_groups_relative_to_background"]
    background_only: bool
    rechecked: bool
    checks: list[ConflictCheck]


class Suggestion(TypedDict):
    option_id: str
    modified_request: Request
    response: Response


class DiagnosisResultFields(TypedDict):
    status: Literal["COMPLETE", "TIME_LIMIT", "ERROR", "UNSUPPORTED", "NOT_APPLICABLE"]
    reason: str | None
    suggestions: list[Suggestion]
    suggestion_minimality: Literal["not_proven"]
    time_limit_seconds: float
    elapsed_seconds: float
    diagnostics: list[Diagnostic]


class DiagnosisResult(DiagnosisResultFields):
    conflict: Conflict | None


class ResponseFields(TypedDict):
    request_id: str | None
    solver: SolverDetails
    objectives: list[ObjectiveValue]
    diagnostics: list[Diagnostic]
    verification: VerificationDetails
    stats: Stats


class ResponseSummaryFields(ResponseFields):
    fairness_summary: FairnessSummary | None
    change_summary: ChangeSummary | None
    diagnosis_result: DiagnosisResult | None
    shortage_summary: ShortageSummary | None


class ResponseMetricsFields(ResponseSummaryFields):
    cost_summary: CostSummary | None
    duty_balance_summary: list[DutyBalanceSummary] | None


class DayCountEmployeeSummary(TypedDict):
    employee_id: str
    work_days: int
    occupied_days: int
    days_off: int


class DayCountSummary(TypedDict):
    constraint_id: str
    type: Literal["work_days_bounds", "days_off_bounds"]
    interval: Interval
    min_days: int | None
    max_days: int | None
    employees: list[DayCountEmployeeSummary]


class Response015Success(ResponseMetricsFields):
    schema_version: Literal["0.15"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ContinuitySolution
    continuity_summary: ContinuitySummary | None
    priority_summary: PrioritySummary
    day_count_summary: list[DayCountSummary] | None
    shift_count_balance_summary: list[ShiftCountBalanceSummary] | None


class Response015Failure(ResponseMetricsFields):
    schema_version: Literal["0.15"]
    status: FailureStatus
    solution: None
    continuity_summary: None
    priority_summary: None
    day_count_summary: None
    shift_count_balance_summary: None


type Response = Response015Success | Response015Failure


class Verification(TypedDict):
    shift_count_balance_summary: list[ShiftCountBalanceSummary] | None
    day_count_summary: list[DayCountSummary] | None
    cost_summary: CostSummary | None
    duty_balance_summary: list[DutyBalanceSummary] | None
    priority_summary: PrioritySummary | None
    continuity_summary: ContinuitySummary | None
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


class SourceConfirmation(TypedDict):
    digest: str
    provenance: Literal["declared", "unknown"]


class InputSource(TypedDict):
    file: NotRequired[str]
    id: str
    revision: str
    section: Literal["basic", "common", "period", "history", "replanning", "execution", "imported"]
    origin: Literal["declared", "unknown"]
    data: dict[str, JSONValue]
    references: list[str]
    applies_to: dict[str, JSONValue] | None
    confirmation: SourceConfirmation | None


class UnresolvedInput(TypedDict):
    source_id: str
    json_pointer: str
    message: str


class ConstraintOverride(TypedDict):
    source_id: str
    target_source_id: str
    constraint_id: str
    before: dict[str, JSONValue]
    reason: str


class RequestDraft(TypedDict):
    adapter_version: Literal["1.0"]
    schema_version: SchemaVersion
    sources: list[InputSource]
    unresolved: list[UnresolvedInput]
    assumptions: list[str]
    overrides: list[ConstraintOverride]
    order: dict[str, list[str]]


class SourceLocation(TypedDict):
    file: NotRequired[str]
    source_id: str
    revision: str
    section: str
    json_pointer: str


class AdapterDiagnostic(Diagnostic):
    sources: NotRequired[list[SourceLocation]]


class ConfirmationState(TypedDict):
    source_id: str
    digest: str
    saved_digest: str | None
    state: Literal["confirmed", "unconfirmed", "stale"]


class Assembly(TypedDict):
    status: Literal["VALID", "INVALID_INPUT", "INTERNAL_ERROR"]
    request: Request | None
    provenance: dict[str, list[SourceLocation]]
    diagnostics: list[AdapterDiagnostic]
    confirmations: list[ConfirmationState]


class ExecutionSettings(TypedDict):
    num_workers: int


class RecordedSource(TypedDict):
    source: InputSource
    content_hash: str


class EngineIdentity(TypedDict):
    version: str
    dependencies: dict[str, str | None]


class DraftMetadata(TypedDict):
    adapter_version: Literal["1.0"]
    schema_version: SchemaVersion
    unresolved: list[UnresolvedInput]
    assumptions: list[str]
    overrides: list[ConstraintOverride]
    order: dict[str, list[str]]


class RunRecord(TypedDict):
    draft_metadata: DraftMetadata | None
    record_version: Literal["1.0"]
    run_id: str
    created_at: str
    request: Request
    response: Response
    execution: ExecutionSettings
    engine: EngineIdentity
    sources: list[RecordedSource]
    provenance: dict[str, list[SourceLocation]]
    content_hash: str


class RecordVerification(TypedDict):
    record: RunRecord
    current_verification: Verification | None
    current_solution: Solution | None


class RecordView(TypedDict):
    run_id: str
    record_hash: str
    request_id: str
    original_status: str
    current_status: str
    verification: VerificationDetails | None
    demand_satisfied: bool | None
    planning_window: PlanningWindow
    solution: Solution | None
    metrics: dict[str, JSONValue]
    diagnostics: list[AdapterDiagnostic]
    original_evidence: Response
