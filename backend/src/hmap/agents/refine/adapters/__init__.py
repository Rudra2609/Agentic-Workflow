"""Refinement adapters for existing capabilities (Sprint 4 item 4.10, plan D1): registered in the refine plug-in's
``Plugin.refiners`` so Member 2's and Member 3's agents are refined behind ``refine=true`` without editing them."""

from hmap.agents.refine.adapters import extraction, plan
from hmap.agents.refine.integration import CapabilityAdapter

EXTRACTION_ADAPTER = CapabilityAdapter(extraction.build_setup, name="extraction")
PLAN_ADAPTER = CapabilityAdapter(plan.build_setup, name="plan")

__all__ = ["EXTRACTION_ADAPTER", "PLAN_ADAPTER", "extraction", "plan"]
