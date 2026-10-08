import heapq
import math
import time
from dataclasses import dataclass

from .contract import diagnostic


@dataclass
class Edge:
    target: int
    reverse: int
    capacity: int
    cost: int


@dataclass
class FlowResult:
    status: str
    solution: dict | None
    values: tuple = ()
    proven_optimal: tuple = ()
    diagnostics: tuple = ()
    search_elapsed_seconds: float = 0.0
    preparation_elapsed_seconds: float = 0.0
    shortage_person_minutes: int | None = None
    shortage_proven_minimal: bool = False


def add_edge(graph, source, target, capacity, cost):
    edge = Edge(target, len(graph[target]), capacity, cost)
    graph[source].append(edge)
    graph[target].append(Edge(source, len(graph[source]) - 1, 0, -cost))
    return edge


def prepare(problem):
    """各時間枠の二部グラフを探索予算の開始前に構築する。"""
    networks = []
    for slot, demand in enumerate(problem.demand):
        roles = sorted(role for role, count in demand.items() if count)
        if not roles:
            continue
        employees = sorted(
            employee for employee, available in problem.available.items() if slot in available
        )
        source, sink = 0, len(employees) + len(roles) + 1
        graph = [[] for _ in range(sink + 1)]
        arcs = []
        for employee_node, employee in enumerate(employees, 1):
            add_edge(graph, source, employee_node, 1, 0)
            for role_index, role in enumerate(roles, len(employees) + 1):
                if role in problem.qualified[employee]:
                    edge = add_edge(
                        graph, employee_node, role_index, 1, problem.costs.get((employee, role), 0)
                    )
                    arcs.append((employee, role, edge))
        for role_node, role in enumerate(roles, len(employees) + 1):
            qualified = sum(role in problem.qualified[employee] for employee in employees)
            if qualified < demand[role] and problem.request["schema_version"] not in {
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
            }:
                return [], diagnostic(
                    "INSUFFICIENT_QUALIFIED_EMPLOYEES",
                    "この役割の勤務可能な有資格者が不足しています。",
                    "/demand",
                    [role],
                    slot=slot,
                    required_people=demand[role],
                    eligible_people=qualified,
                )
            add_edge(graph, role_node, sink, demand[role], 0)
        networks.append((slot, graph, arcs, sum(demand.values())))
    return networks, None


def augment(graph, required, deadline):
    """残余グラフの最短路で配置を入れ替え、整数費用の最小費用流を求める。"""
    potentials = [0] * len(graph)
    total = 0
    sink = len(graph) - 1
    for _ in range(required):
        distances = [math.inf] * len(graph)
        parents = [None] * len(graph)
        distances[0] = 0
        queue = [(0, 0)]
        while queue:
            if time.monotonic() >= deadline:
                return "UNKNOWN", total
            distance, node = heapq.heappop(queue)
            if distance != distances[node]:
                continue
            for index, edge in enumerate(graph[node]):
                if not edge.capacity:
                    continue
                candidate = distance + edge.cost + potentials[node] - potentials[edge.target]
                if candidate < distances[edge.target]:
                    distances[edge.target] = candidate
                    parents[edge.target] = node, index
                    heapq.heappush(queue, (candidate, edge.target))
        if parents[sink] is None:
            return "INFEASIBLE", total
        for node, distance in enumerate(distances):
            if distance != math.inf:
                potentials[node] += distance
        node = sink
        while node:
            parent, index = parents[node]
            edge = graph[parent][index]
            edge.capacity -= 1
            graph[node][edge.reverse].capacity += 1
            total += edge.cost
            node = parent
    return "OPTIMAL", total


def make_solution(grid, assignments):
    result = []
    for employee in sorted(assignments):
        for slot, role in sorted(assignments[employee]):
            if (
                result
                and result[-1][0] == employee
                and result[-1][1] == role
                and result[-1][3] == slot
            ):
                result[-1][3] = slot + 1
            else:
                result.append([employee, role, slot, slot + 1])
    return {
        "assignments": [
            {"employee_id": employee, "role_id": role, "interval": grid.output_interval(start, end)}
            for employee, role, start, end in result
        ],
        "shifts": [],
    }


def run(problem):
    preparation_start = time.perf_counter()
    networks, shortage = prepare(problem)
    preparation_elapsed = time.perf_counter() - preparation_start
    if shortage:
        return FlowResult(
            "INFEASIBLE",
            None,
            diagnostics=(shortage,),
            preparation_elapsed_seconds=preparation_elapsed,
        )
    start = time.monotonic()
    deadline = start + problem.request["solver"]["time_limit_seconds"]
    assignments = {}
    cost = 0
    partial = problem.request["schema_version"] in {
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
    }
    completed = True
    for slot, graph, arcs, required in networks:
        status, slot_cost = augment(graph, required, deadline)
        if status != "OPTIMAL" and not partial:
            code = "TIME_LIMIT" if status == "UNKNOWN" else "COMPETING_ROLE_DEMAND"
            message = (
                "探索予算内に完全な解を得られませんでした。"
                if status == "UNKNOWN"
                else "複数役割の需要を同時に満たせません。"
            )
            return FlowResult(
                status,
                None,
                diagnostics=(diagnostic(code, message, "/demand", slot=slot),),
                search_elapsed_seconds=time.monotonic() - start,
                preparation_elapsed_seconds=preparation_elapsed,
            )
        cost += slot_cost
        for employee, role, edge in arcs:
            if edge.capacity == 0:
                assignments.setdefault(employee, []).append((slot, role))
        if status == "UNKNOWN":
            completed = False
            break
    shortage = (
        sum(sum(d.values()) for d in problem.demand)
        - sum(len(slots) for slots in assignments.values())
    ) * problem.grid.slot_minutes
    return FlowResult(
        "OPTIMAL" if completed else "FEASIBLE",
        make_solution(problem.grid, assignments),
        (cost,) if problem.request["objectives"] else (),
        (completed,) if problem.request["objectives"] else (),
        diagnostics=()
        if completed
        else (diagnostic("TIME_LIMIT", "探索予算内の担当配置を返します。"),),
        search_elapsed_seconds=time.monotonic() - start,
        preparation_elapsed_seconds=preparation_elapsed,
        shortage_person_minutes=shortage if partial else None,
        shortage_proven_minimal=completed,
    )
