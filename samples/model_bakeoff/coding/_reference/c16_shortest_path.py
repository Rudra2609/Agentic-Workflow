import heapq
def shortest_path(graph, start, goal):
    if start == goal:
        return (0, [start])
    dist, prev, heap = {start: 0}, {}, [(0, start)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == goal:
            path = [u]
            while path[-1] != start:
                path.append(prev[path[-1]])
            return (d, path[::-1])
        if d > dist.get(u, float("inf")):
            continue
        for v, w in graph.get(u, {}).items():
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v], prev[v] = nd, u
                heapq.heappush(heap, (nd, v))
    return (float("inf"), [])
