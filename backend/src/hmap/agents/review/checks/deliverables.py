"""Every deliverable is present (a file in the workspace, a document in the doc bundle)."""

from hmap.agents.review.model import Check, Item


def check(item: Item) -> Check | None:
    ds = item.evidence.deliverables
    if not ds:
        return None
    if all(d.where == "needs a person" for d in ds):
        return Check(verdict="PARTIAL", no_action=True,
                     reasons=[f"{', '.join(d.name for d in ds)}: needs a person (no agent can produce it)"])
    missing = [d.name for d in ds if d.present is False]
    if missing:
        return Check(verdict="FAIL", category="MISSING",
                     reasons=[f"deliverable {', '.join(missing)} not produced"])
    known = [d for d in ds if d.present]
    if not known:
        return None          # the rules could not tell where it would be: the judge decides
    return Check(verdict="PASS", reasons=[f"{d.name} present ({d.where})" if d.where else f"{d.name} present"
                                          for d in known])
