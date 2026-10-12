Write `topo_order(deps: dict[str, list[str]]) -> list[str]`.

`deps[task]` lists the tasks that must come **before** `task`. Tasks that appear only as prerequisites are
also part of the result. Return every task exactly once so that each task comes after all its prerequisites.
When several tasks are ready at the same time, pick them in alphabetical order (so the result is deterministic).
Raise `ValueError` if there is a cycle (including a task depending on itself).
