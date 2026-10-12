Write `parallel_map(fn, items: list, workers: int) -> list` that applies `fn` to every item using at most
`workers` threads running at the same time, and returns the results **in the same order as `items`**.
If `fn` raises for any item, `parallel_map` must raise that exception (after stopping or finishing the other work).
Raise `ValueError` if `workers < 1`.
