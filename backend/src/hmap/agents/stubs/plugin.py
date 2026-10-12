"""Stub plug-in (priority 0): yields each capability automatically once a real plug-in declares it."""

from hmap.agents.stubs.agents import CAPABILITY_STUBS, EchoAgent
from hmap.core.plugins import Plugin
from hmap.core.runtime.base import BaseAgent

AGENTS: list[type[BaseAgent]] = [EchoAgent, *CAPABILITY_STUBS]

PLUGIN = Plugin(
    name="stubs",
    agents=AGENTS,
    priority=0,
    description="Canned contract-valid outputs for every Sprint-1 capability (+ echo).",
)
