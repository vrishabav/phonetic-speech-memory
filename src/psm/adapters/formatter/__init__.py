"""Formatter adapters.

The formatter is the stage *above* memory: raw ASR text in, clean prose out.
PSM does not own it - it conditions it, and then checks its work.

Two implementations, and the difference between them is the whole reason this
is a port:

`PassthroughFormatter` is the frozen formatter. The evaluation fixtures supply
both `asr_text` and `formatted_text`, so during evaluation the formatting stage
must be a constant: if it were a model, a change in its mood would be
indistinguishable from a change in memory quality, and every number in
`evals/results/` would be unfalsifiable.

`LLMFormatter` is the live one, used by the demo and by `make eval-live`. It is
the only place a standing instruction ("never write 'Sarvam AI' mid-sentence")
can actually be executed, because an instruction is a rule about how to write,
not a string to substitute.
"""

from __future__ import annotations

from psm.adapters.formatter.llm_formatter import LLMFormatter
from psm.adapters.formatter.passthrough import PassthroughFormatter

__all__ = ["LLMFormatter", "PassthroughFormatter"]
