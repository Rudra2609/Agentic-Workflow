"""Revisers (Sprint 4 item 4.4): targeted patch (only flagged parts change), full rewrite, constrained-schema rewrite,
and a strategy dispatcher."""

from hmap.agents.refine.revisers.patch import Patch, PatchError, apply, apply_all, resolve, within
from hmap.agents.refine.revisers.rewrite import FullRewriteReviser, SchemaReviser
from hmap.agents.refine.revisers.strategic import StrategicReviser
from hmap.agents.refine.revisers.targeted import PatchAnswer, PatchOp, TargetedReviser, issue_lines, reflection_lines

__all__ = ["FullRewriteReviser", "Patch", "PatchAnswer", "PatchError", "PatchOp", "SchemaReviser",
           "StrategicReviser", "TargetedReviser", "apply", "apply_all", "issue_lines", "reflection_lines", "resolve",
           "within"]
