"""Ports: Protocol definitions only.

Nothing in this package may import from `lmh.adapters` or `lmh.engine`.
Every implementation lives in `lmh.adapters` and is selected by config.
"""

from .clock import Clock
from .formatter import Formatter
from .index import CandidateIndex
from .llm import LanguageModel, LLMResponse
from .phonetics import PhoneticComparator, PhoneticEncoder
from .policy import Policy, PolicyContext
from .store import AdjudicationLog, MemoryStore, ObservationLog

__all__ = [
    "AdjudicationLog",
    "CandidateIndex",
    "Clock",
    "Formatter",
    "LLMResponse",
    "LanguageModel",
    "MemoryStore",
    "ObservationLog",
    "PhoneticComparator",
    "PhoneticEncoder",
    "Policy",
    "PolicyContext",
]
