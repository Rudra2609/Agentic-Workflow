import heapq
def topo_order(deps):
    nodes = set(deps)
    for ps in deps.values():
        nodes.update(ps)
    indeg = {n: 0 for n in nodes}
    children = {n: [] for n in nodes}
    for t, ps in deps.items():
        for p in set(ps):
            indeg[t] += 1
            children[p].append(t)
    heap = [n for n in nodes if indeg[n] == 0]
    heapq.heapify(heap)
    out = []
    while heap:
        n = heapq.heappop(heap)
        out.append(n)
        for c in children[n]:
            indeg[c] -= 1
            if indeg[c] == 0:
                heapq.heappush(heap, c)
    if len(out) != len(nodes):
        raise ValueError("cycle")
    return out
