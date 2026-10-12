Write `merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]`.

Each interval is `(start, end)` with start <= end. Merge all overlapping intervals; intervals that only touch
(like `(1, 2)` and `(2, 3)`) also merge. Return the merged intervals as tuples sorted by start.
The input may be unsorted and must not be modified.
