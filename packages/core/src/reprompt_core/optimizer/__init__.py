"""M3 optimizer loop — turns a stage's original prompt + rubric + a
benchmark example into a scored, selected best candidate for a cheaper
target model.

See ``loop.py`` for the entry point (:func:`run_optimizer`) and its module
docstring for the full design (why PromptWizard was dropped in favor of an
in-house mutator, why selection happens per-stage against one representative
benchmark example, and why ``packages/core`` stays headless — no DB, no
FastAPI — with progress/persistence handed to the caller via a callback).
"""

from reprompt_core.optimizer.loop import (
    OptimizationResult,
    StageAttempt,
    StageOptimizationInput,
    StageResult,
    run_optimizer,
)
from reprompt_core.optimizer.mutator import (
    MutationExample,
    PromptMutationError,
    PromptMutationResult,
    generate_prompt_mutations,
)

__all__ = [
    "OptimizationResult",
    "StageAttempt",
    "StageOptimizationInput",
    "StageResult",
    "run_optimizer",
    "MutationExample",
    "PromptMutationError",
    "PromptMutationResult",
    "generate_prompt_mutations",
]
