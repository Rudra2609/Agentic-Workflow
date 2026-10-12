Write a thread-safe counter and a helper:

- class `SafeCounter` with `increment()` (adds 1) and a `value` property.
- `count_with_threads(n_threads: int, increments: int) -> int` starts `n_threads` threads that each call
  `increment()` on one shared `SafeCounter` exactly `increments` times, waits for all of them, and returns the final value.
