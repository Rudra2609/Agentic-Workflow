Write `shortest_path(graph: dict[str, dict[str, float]], start: str, goal: str) -> tuple[float, list[str]]`.

`graph[u][v]` is the non-negative weight of the directed edge u -> v. Nodes may appear only as edge targets.
Return `(total_cost, path)` for a cheapest path from `start` to `goal`, where `path` lists the nodes including both ends.
If `start == goal` return `(0, [start])`. If `goal` is unreachable (or a node is unknown) return `(float("inf"), [])`.
