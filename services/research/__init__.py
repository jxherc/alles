"""
deep research — IterResearch-style engine (ported from odysseus, which adapted
Alibaba Tongyi DeepResearch). LLM-driven think→search→extract→synthesize loop.
"""

from .deep_research import DeepResearcher, current_date_context
from .handler import cancel_task, get_task, run_research

__all__ = ["DeepResearcher", "current_date_context", "run_research", "get_task", "cancel_task"]
