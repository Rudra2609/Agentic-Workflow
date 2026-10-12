from concurrent.futures import ThreadPoolExecutor
def parallel_map(fn, items, workers):
    if workers < 1:
        raise ValueError("workers")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))
