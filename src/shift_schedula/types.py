"""JSON契約の公開型。範囲・参照・業務上の整合はvalidateで確認する。"""

from typing import Literal, NotRequired, TypedDict

type SchemaVersion = Literal[
    "0.1",
    "0.2",
    "0.3",
    "0.4",
    "0.5",
    "0.6",
    "0.7",
    "0.8",
    "0.9",
    "0.10",
    "0.11",
    "0.12",
    "0.13",
    "0.14",
    "0.15",
]
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


class DayCountBounds(ConstraintFields):
    type: Literal["work_days_bounds", "days_off_bounds"]
    interval: Interval
    min_days: NotRequired[int]
    max_days: NotRequired[int]


type Constraint01 = MinutesConstraint | ConsecutiveDaysConstraint | RoleSwitchConstraint
type Constraint = Constraint01 | SplitGapConstraint
type Constraint04 = Constraint | ScheduledMinutesBounds
type Constraint011 = Constraint04 | DayCountBounds


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


type Constraint013 = (
    Constraint011
    | ForbiddenShiftSuccessions
    | DaysOffAfterShift
    | MinConsecutiveDaysOff
    | WorkedDateGroupsLimit
)


class RequiredCoworkers(ConstraintFields):
    type: Literal["required_coworkers"]
    interval: Interval
    coworker_ids: list[str]
    minimum_people: int


class IncompatibleEmployees(ConstraintFields):
    type: Literal["incompatible_employees"]
    interval: Interval


type Constraint014 = Constraint013 | RequiredCoworkers | IncompatibleEmployees


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


class DiagnosisOptions(TypedDict):
    time_limit_seconds: float
    max_suggestions: int
    allowed_changes: list[AllowedChange]


class ConflictRefinement(TypedDict):
    time_limit_seconds: float


class DiagnosisOptions08(DiagnosisOptions):
    conflict_refinement: NotRequired[ConflictRefinement]


class RequestFields(TypedDict):
    request_id: str
    problem_type: Literal["assignment", "roster"]
    planning_window: PlanningWindow
    skills: list[Skill]
    roles: list[Role]
    solver: SolverOptions


class Request01(RequestFields):
    schema_version: Literal["0.1"]
    demand: list[Demand]
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
    demand: list[Demand]
    constraints: list[Constraint]
    preferences: list[AvoidRole]


class Request03(ExtendedRequestFields):
    schema_version: Literal["0.3"]
    demand: list[Demand]
    constraints: list[Constraint]
    preferences: list[AvoidRole]


class Request04(ExtendedRequestFields):
    schema_version: Literal["0.4"]
    demand: list[Demand]
    constraints: list[Constraint04]
    preferences: list[AvoidRole | WorkPreference]
    replan_mode: NotRequired[Literal["preserve_assigned", "rebuild"]]


class Request05(ExtendedRequestFields):
    schema_version: Literal["0.5"]
    demand: list[PriorityDemand]
    constraints: list[Constraint04]
    preferences: list[AvoidRole | WorkPreference]
    replan_mode: NotRequired[Literal["preserve_assigned", "rebuild"]]


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


class Request06(ExtendedRequestFields):
    schema_version: Literal["0.6"]
    demand: list[PriorityDemand]
    constraints: list[Constraint04]
    preferences: list[AvoidRole | WorkPreference]
    replan_mode: NotRequired[Literal["preserve_assigned", "rebuild"]]
    continuity: NotRequired[Continuity]


class Request07(ExtendedRequestFields):
    schema_version: Literal["0.7"]
    demand: list[PriorityDemand]
    constraints: list[Constraint04]
    preferences: list[AvoidRole | WorkPreference]
    replan_mode: NotRequired[Literal["preserve_assigned", "rebuild"]]
    continuity: NotRequired[Continuity]


class Request08(RequestFields):
    schema_version: Literal["0.8"]
    demand: list[PriorityDemand]
    constraints: list[Constraint04]
    preferences: list[AvoidRole | WorkPreference]
    replan_mode: NotRequired[Literal["preserve_assigned", "rebuild"]]
    continuity: NotRequired[Continuity]

    employees: list[Employee]
    shift_candidates: list[ShiftCandidate]
    shift_templates: NotRequired[list[ShiftTemplate]]
    objectives: list[Objective]
    fairness: NotRequired[Fairness]
    baseline: NotRequired[Baseline]
    fixed_parts: NotRequired[list[FixedPart]]
    diagnosis: NotRequired[DiagnosisOptions08]


class PlanningWindow09(Interval):
    timezone: str
    slot_minutes: Literal[1, 5, 10, 15, 20, 30, 60]


class RosterRequestFields(TypedDict):
    request_id: str
    problem_type: Literal["assignment", "roster"]
    planning_window: PlanningWindow09
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
    diagnosis: NotRequired[DiagnosisOptions08]
    costs: NotRequired[Costs]
    duty_balance: NotRequired[list[DutyBalance]]


class MetricsRequestFields(RosterRequestFields):
    objectives: list[Objective | CostObjective | DutyObjective]


class Request09(MetricsRequestFields):
    schema_version: Literal["0.9"]
    demand: list[PriorityDemand]
    constraints: list[Constraint04]


class Request010(MetricsRequestFields):
    schema_version: Literal["0.10"]
    demand: list[PriorityDemand]
    constraints: list[Constraint04]


class Request011(MetricsRequestFields):
    schema_version: Literal["0.11"]
    demand: list[PriorityDemand]
    constraints: list[Constraint011]


class Request012(MetricsRequestFields):
    schema_version: Literal["0.12"]
    demand: list[MinimumDemand]
    constraints: list[Constraint011]


class Request013(MetricsRequestFields):
    schema_version: Literal["0.13"]
    demand: list[MinimumDemand]
    constraints: list[Constraint013]

    shift_categories: NotRequired[list[ShiftCategory]]


class Request014(MetricsRequestFields):
    schema_version: Literal["0.14"]
    demand: list[MinimumDemand]
    constraints: list[Constraint014]
    shift_categories: NotRequired[list[ShiftCategory]]


class Request015(RosterRequestFields):
    schema_version: Literal["0.15"]
    demand: list[MinimumDemand]
    constraints: list[Constraint014]
    objectives: list[Objective | CostObjective | DutyObjective | ShiftCountObjective]
    shift_categories: NotRequired[list[ShiftCategory]]
    shift_count_balance: NotRequired[list[ShiftCountBalance]]


type Request = (
    Request01
    | Request02
    | Request03
    | Request04
    | Request05
    | Request06
    | Request07
    | Request08
    | Request09
    | Request010
    | Request011
    | Request012
    | Request013
    | Request014
    | Request015
)


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


type Solution = Solution01 | ExtendedSolution | ContinuitySolution


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
    minimum_people: NotRequired[int]


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


class Conflict(TypedDict):
    conditions: list[ConflictCondition]
    infeasibility_proven: Literal[True]
    minimality: Literal["not_proven"]


class ConflictCondition08(ConflictCondition):
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


class Conflict08(TypedDict):
    conditions: list[ConflictCondition08]
    background_conditions: list[ConflictCondition08]
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


class DiagnosisResult08(DiagnosisResultFields):
    conflict: Conflict08 | None


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


class Response05Success(PartialResponseFields):
    schema_version: Literal["0.5"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ExtendedSolution
    priority_summary: PrioritySummary


class Response05Failure(PartialResponseFields):
    schema_version: Literal["0.5"]
    status: FailureStatus
    solution: None
    priority_summary: None


class Response06Success(PartialResponseFields):
    schema_version: Literal["0.6"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ContinuitySolution
    continuity_summary: ContinuitySummary | None
    priority_summary: PrioritySummary


class Response06Failure(PartialResponseFields):
    schema_version: Literal["0.6"]
    status: FailureStatus
    solution: None
    continuity_summary: None
    priority_summary: None


class Response07Success(PartialResponseFields):
    schema_version: Literal["0.7"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ContinuitySolution
    continuity_summary: ContinuitySummary | None
    priority_summary: PrioritySummary


class Response07Failure(PartialResponseFields):
    schema_version: Literal["0.7"]
    status: FailureStatus
    solution: None
    continuity_summary: None
    priority_summary: None


class Response08Fields(ResponseFields):
    fairness_summary: FairnessSummary | None
    change_summary: ChangeSummary | None
    diagnosis_result: DiagnosisResult08 | None
    shortage_summary: ShortageSummary | None


class Response08Success(Response08Fields):
    schema_version: Literal["0.8"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ContinuitySolution
    continuity_summary: ContinuitySummary | None
    priority_summary: PrioritySummary


class Response08Failure(Response08Fields):
    schema_version: Literal["0.8"]
    status: FailureStatus
    solution: None
    continuity_summary: None
    priority_summary: None


class Response09Fields(Response08Fields):
    cost_summary: CostSummary | None
    duty_balance_summary: list[DutyBalanceSummary] | None


class Response09Success(Response09Fields):
    schema_version: Literal["0.9"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ContinuitySolution
    continuity_summary: ContinuitySummary | None
    priority_summary: PrioritySummary


class Response09Failure(Response09Fields):
    schema_version: Literal["0.9"]
    status: FailureStatus
    solution: None
    continuity_summary: None
    priority_summary: None


class Response010Success(Response09Fields):
    schema_version: Literal["0.10"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ContinuitySolution
    continuity_summary: ContinuitySummary | None
    priority_summary: PrioritySummary


class Response010Failure(Response09Fields):
    schema_version: Literal["0.10"]
    status: FailureStatus
    solution: None
    continuity_summary: None
    priority_summary: None


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


class Response011Success(Response09Fields):
    schema_version: Literal["0.11"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ContinuitySolution
    continuity_summary: ContinuitySummary | None
    priority_summary: PrioritySummary
    day_count_summary: list[DayCountSummary] | None


class Response011Failure(Response09Fields):
    schema_version: Literal["0.11"]
    status: FailureStatus
    solution: None
    continuity_summary: None
    priority_summary: None
    day_count_summary: None


class Response012Success(Response09Fields):
    schema_version: Literal["0.12"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ContinuitySolution
    continuity_summary: ContinuitySummary | None
    priority_summary: PrioritySummary
    day_count_summary: list[DayCountSummary] | None


class Response012Failure(Response09Fields):
    schema_version: Literal["0.12"]
    status: FailureStatus
    solution: None
    continuity_summary: None
    priority_summary: None
    day_count_summary: None


class Response013Success(Response09Fields):
    schema_version: Literal["0.13"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ContinuitySolution
    continuity_summary: ContinuitySummary | None
    priority_summary: PrioritySummary
    day_count_summary: list[DayCountSummary] | None


class Response013Failure(Response09Fields):
    schema_version: Literal["0.13"]
    status: FailureStatus
    solution: None
    continuity_summary: None
    priority_summary: None
    day_count_summary: None


class Response014Success(Response09Fields):
    schema_version: Literal["0.14"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ContinuitySolution
    continuity_summary: ContinuitySummary | None
    priority_summary: PrioritySummary
    day_count_summary: list[DayCountSummary] | None


class Response014Failure(Response09Fields):
    schema_version: Literal["0.14"]
    status: FailureStatus
    solution: None
    continuity_summary: None
    priority_summary: None
    day_count_summary: None


class Response015Success(Response09Fields):
    schema_version: Literal["0.15"]
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    solution: ContinuitySolution
    continuity_summary: ContinuitySummary | None
    priority_summary: PrioritySummary
    day_count_summary: list[DayCountSummary] | None
    shift_count_balance_summary: list[ShiftCountBalanceSummary] | None


class Response015Failure(Response09Fields):
    schema_version: Literal["0.15"]
    status: FailureStatus
    solution: None
    continuity_summary: None
    priority_summary: None
    day_count_summary: None
    shift_count_balance_summary: None


type Response = (
    Response01Success
    | Response01Failure
    | Response02Success
    | Response02Failure
    | Response03Success
    | Response03Failure
    | Response04Success
    | Response04Failure
    | Response05Success
    | Response05Failure
    | Response06Success
    | Response06Failure
    | Response07Success
    | Response07Failure
    | Response08Success
    | Response08Failure
    | Response09Success
    | Response09Failure
    | Response010Success
    | Response010Failure
    | Response011Success
    | Response011Failure
    | Response012Success
    | Response012Failure
    | Response013Success
    | Response013Failure
    | Response014Success
    | Response014Failure
    | Response015Success
    | Response015Failure
)


class Verification(TypedDict):
    shift_count_balance_summary: NotRequired[list[ShiftCountBalanceSummary] | None]
    day_count_summary: NotRequired[list[DayCountSummary] | None]
    cost_summary: NotRequired[CostSummary | None]
    duty_balance_summary: NotRequired[list[DutyBalanceSummary] | None]
    priority_summary: NotRequired[PrioritySummary | None]
    continuity_summary: NotRequired[ContinuitySummary | None]
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
