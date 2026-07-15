"""Model-card transform layer — mechanical, versioned prompt rewrites per model family.

Per ``reprompt-master-build-prompt.md`` §2 ("Model card: registry layer,
versioned; transforms encoded as rewrite rules per model family") and §5
M3 ("model-card transform layer (mechanical prompt rewrites per target
family, driven by a versioned registry JSON on top of LiteLLM's model
data)"), and ``reprompt-parity-engine-plan.md`` §3 ("...+ custom layer:
format preference (XML/MD/JSON) ... prompting-guide transforms per model
family") and §6 ("Model cards: registry layer, versioned; transforms
encoded as rewrite rules per model family (community-contributable
later = moat)").

This module is **not** the capability registry — see
:mod:`reprompt_core.llm.registry` for cost/context-window/JSON-mode/
tool-use facts pulled from LiteLLM's own model metadata. This module
answers a different question: *given a prompt written for one model,
what mechanical text rewrite makes it read more like a prompt written
in the target family's idiom?* It is pure text-in/text-out — no LLM
call, no I/O, no randomness. See ``test_model_card.py`` for a test that
asserts this module never imports or calls
:func:`reprompt_core.llm.client.complete`.

Family classification
----------------------
:func:`resolve_family` maps a LiteLLM model string to one of a small,
documented set of families:

* ``"anthropic"`` — all Claude models (Claude API, Bedrock, Vertex AI).
  Lumped into one family: Anthropic's own prompting guidance (XML-tagged
  sections) is the same across every Claude model and hosting surface.
* ``"gemini"`` — all Gemini models (Gemini API, Vertex AI). Same
  reasoning as above: one vendor, one prompting convention, regardless
  of which API surface routes the call.
* ``"openai"`` — GPT-family models, including Azure OpenAI (Azure hosts
  the identical underlying models under a different auth/routing
  provider, so it is folded into the same family rather than split out).
* ``"llama"`` — a deliberately broad **open-weight / self-hosted**
  bucket, not literally "only Meta's Llama". The task's own phrasing
  ("llama"/open-source) is used as the label for this bucket. Model
  strings that name-match a known open-weight family (Llama, Mistral,
  Mixtral, Gemma, Qwen, Phi, DeepSeek, Falcon, Vicuna, StarCoder) land
  here *regardless of which provider/aggregator is serving them*
  (``ollama/llama3``, ``groq/llama3-70b-8192``,
  ``together_ai/meta-llama/Llama-3-70b``, ``vllm/mistral-7b``, ...) —
  because aggregator/self-host providers route many unrelated model
  families through one LiteLLM provider string, provider alone is not
  enough signal. No family-specific structural rule is implemented for
  this bucket yet (only the universal small-model compression rule
  applies) since there isn't one open-weight-wide prompting convention
  the way there is for Claude (XML) or Gemini (Markdown) — a future
  community contribution could split this further (e.g. a Llama-specific
  or Qwen-specific card).
* ``"generic"`` — the fallback for every other provider (Cohere,
  Mistral's own API, a model LiteLLM can't classify at all, ...). Gets
  only the universal small-model compression rule, never a structural
  rewrite, per the "sensible default" requirement.

Name-based sniffing (open-weight markers, ``"claude"``, ``"gemini"``,
``"gpt"``) runs *before* the provider-based fallback, so a Claude model
served through Bedrock or Vertex (provider ``"bedrock"``/``"vertex_ai"``)
still resolves to ``"anthropic"``, not ``"generic"``. Vertex AI Gemini
models (provider ``"vertex_ai"``) resolve to ``"gemini"`` via the
provider fallback if the model name itself doesn't say "gemini" (it
normally does).

Small-model ("nano") detection is a **separate axis**, not a family
------------------------------------------------------------------------
The task's own framing lists "terse system prompts for nano/small
models" alongside the Claude/Gemini structural examples. Rather than
making "nano" its own family (which would mean a small Claude model like
``claude-3-5-haiku`` loses XML structuring just because it's small — the
opposite of what Anthropic's own guidance recommends), this module treats
model *size* as an orthogonal dimension via :func:`is_small_variant`.
Every family's rule set includes the same shared compression rule, gated
to only fire when the target model looks small (see ``applies_to`` on
:class:`TransformRule`). Concretely: ``claude-3-5-haiku`` gets *both* the
compression rule *and* the XML-wrap rule; ``gpt-4o-mini`` gets *only*
compression (the ``openai`` family has no structural rule); a large
Claude model gets *only* XML-wrap. Compression is applied before the
structural rewrite (see :func:`apply_model_card_transform`) so that
section headers survive intact for the structural rule to find.

Versioning
----------
Each :class:`FamilyCard` carries an integer ``version``, bumped whenever
that family's rule *set* changes (a rule added, removed, or its behavior
changed) — the exact scheme matters less than it being present, per the
plan's "versioned... community-contributable later" framing. A future
contributed rule set (e.g. a dedicated ``"mistral"`` card) simply adds a
new entry to ``_FAMILY_CARDS`` with its own ``version=1``.

Zero FastAPI imports, per the working rules for ``packages/core``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import litellm

__all__ = [
    "TransformRule",
    "FamilyCard",
    "resolve_family",
    "is_small_variant",
    "get_transform_rules",
    "applicable_rules",
    "apply_model_card_transform",
]


# ---------------------------------------------------------------------------
# Family classification
# ---------------------------------------------------------------------------

# Model-name substrings that indicate a specific open-weight model family,
# checked regardless of which LiteLLM provider is serving the model (see
# module docstring: aggregators like groq/together_ai/openrouter/ollama/vllm
# route many unrelated model families through one provider string). Plain
# substring matching (not word-boundary) is deliberate: real open-weight
# naming conventions glue a version digit directly onto the family name
# with no separator ("llama3", "gemma2", "qwen2", "phi3", "phi4"), so a
# ``\b`` boundary between the name and the digit would fail to match the
# common case. None of these particular words collide with an unrelated
# substring in realistic model-name space.
_OPEN_WEIGHT_MARKERS = (
    "llama",
    "mistral",
    "mixtral",
    "gemma",
    "qwen",
    "deepseek",
    "phi",
    "vicuna",
    "falcon",
    "starcoder",
)

# LiteLLM provider -> family, consulted only after name-sniffing finds
# nothing more specific (see module docstring).
_PROVIDER_FAMILY: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "azure": "openai",  # Azure OpenAI hosts the same underlying OpenAI models
    "gemini": "gemini",
    "vertex_ai": "gemini",
    "vertex_ai_beta": "gemini",
}


def _resolve_provider(model: str) -> str | None:
    try:
        return litellm.get_llm_provider(model)[1]
    except Exception:
        return None


def resolve_family(model: str) -> str:
    """Classify a LiteLLM model string into a model-card family.

    Never raises: an unrecognized model string resolves to ``"generic"``
    rather than raising, mirroring the "degrade gracefully" contract used
    throughout :mod:`reprompt_core.llm.registry`.

    See the module docstring for the full classification scheme and the
    documented reasoning behind every lump/split decision.
    """
    lower_model = model.lower()

    if any(marker in lower_model for marker in _OPEN_WEIGHT_MARKERS):
        return "llama"
    if "claude" in lower_model:
        return "anthropic"
    if "gemini" in lower_model:
        return "gemini"
    if "gpt" in lower_model:
        return "openai"

    provider = _resolve_provider(model)
    return _PROVIDER_FAMILY.get(provider or "", "generic")


# Name markers for "small"/"nano" variants: word-boundary matches (case-
# insensitive) for the common vendor naming conventions the task calls
# out ("mini", "flash-lite", "haiku", ...), plus a numeric parameter-count
# pattern (e.g. "llama3:8b", "phi3-3.8b") for open-weight models that
# encode size directly in the name. Threshold of <=10B is a heuristic, not
# a precise cutoff — it is meant to catch the "obviously small, deploy-
# on-a-laptop" tier, not draw a scientifically exact line.
#
# Word-boundary (not plain substring) matching is required here: a naive
# ``"mini" in "gemini"`` is True, which would wrongly flag every Gemini
# model as "small". ``\b`` still matches "mini" in "gpt-4o-mini" (the
# hyphen is a non-word character, so a boundary exists there) while
# correctly rejecting "mini" inside the contiguous word "gemini".
_SMALL_NAME_MARKERS = ("mini", "nano", "flash-lite", "haiku", "lite", "small")
_SMALL_NAME_RE = re.compile(r"\b(?:" + "|".join(_SMALL_NAME_MARKERS) + r")\b", re.IGNORECASE)
_SIZE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)b\b")
_SMALL_PARAM_COUNT_THRESHOLD_B = 10.0


def is_small_variant(model: str) -> bool:
    """Heuristic: does ``model`` look like a "nano"/small/cheap variant?

    Used to gate the universal compression rule (see module docstring) —
    intentionally independent of :func:`resolve_family`, since size and
    prompting-family are orthogonal facts about a model.
    """
    lower_model = model.lower()
    if _SMALL_NAME_RE.search(lower_model):
        return True
    match = _SIZE_PATTERN.search(lower_model)
    if match:
        try:
            return float(match.group(1)) <= _SMALL_PARAM_COUNT_THRESHOLD_B
        except ValueError:
            return False
    return False


# ---------------------------------------------------------------------------
# Shared section-detection (used by both the XML and Markdown structural
# rules) — a prompt is considered "structured" if it has one or more
# recognized labeled sections, each on its own line, optionally as a
# markdown header (``## Instructions``) and optionally colon-terminated
# (``Instructions:``). This is deliberately a small, fixed vocabulary
# rather than an attempt to parse arbitrary prose.
# ---------------------------------------------------------------------------

_LABEL_LOOKUP: dict[str, tuple[str, str]] = {
    # captured label (lowercased) -> (xml tag key, markdown title)
    "instructions": ("instructions", "Instructions"),
    "instruction": ("instructions", "Instructions"),
    "context": ("context", "Context"),
    "output format": ("output_format", "Output Format"),
    "output": ("output_format", "Output Format"),
    "examples": ("example", "Examples"),
    "example": ("example", "Examples"),
    "task": ("task", "Task"),
    "constraints": ("constraints", "Constraints"),
}

_HEADER_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*)?"
    r"(?P<label>Instructions?|Context|Output Format|Output|Examples?|Task|Constraints)"
    r"\s*:?\s*$",
    re.IGNORECASE,
)


def _split_sections(prompt: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Split ``prompt`` into a preamble plus recognized labeled sections.

    Returns ``(preamble, sections)`` where each section is
    ``(markdown_title, xml_tag_key, body_text)``. ``sections`` is empty
    (and ``preamble`` is the whole, unchanged prompt) if no recognized
    header line is found — callers use this to no-op cleanly on
    unstructured prose rather than mangling it.
    """
    lines = prompt.split("\n")
    headers: list[tuple[int, str, str]] = []  # (line_index, tag_key, title)
    for index, line in enumerate(lines):
        match = _HEADER_RE.match(line)
        if not match:
            continue
        key = match.group("label").lower()
        mapped = _LABEL_LOOKUP.get(key)
        if mapped is not None:
            headers.append((index, mapped[0], mapped[1]))

    if not headers:
        return prompt, []

    preamble = "\n".join(lines[: headers[0][0]]).strip()
    sections: list[tuple[str, str, str]] = []
    for position, (line_no, tag_key, title) in enumerate(headers):
        start = line_no + 1
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        body = "\n".join(lines[start:end]).strip()
        sections.append((title, tag_key, body))
    return preamble, sections


# ---------------------------------------------------------------------------
# Anthropic/Claude: wrap labeled sections in XML tags.
#
# A well-documented real Anthropic prompting convention (see Anthropic's
# own "use XML tags" prompt-engineering guidance) — not invented for this
# task.
# ---------------------------------------------------------------------------


def _wrap_sections_as_xml(prompt: str) -> str:
    preamble, sections = _split_sections(prompt)
    if not sections:
        return prompt  # nothing recognized: safe no-op rather than guessing
    parts = [preamble] if preamble else []
    for _title, tag_key, body in sections:
        parts.append(f"<{tag_key}>\n{body}\n</{tag_key}>" if body else f"<{tag_key}></{tag_key}>")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Gemini: prefer markdown headers over XML tags.
#
# Also a documented, real convention difference (Google's Gemini prompting
# guidance favors markdown structure over XML). Handles two source shapes:
# a prompt already written with labeled ``Label:``/``## Label`` sections
# (converted straight to markdown headers), and a prompt that already has
# Claude-style XML tags (converted from XML to markdown headers) — the
# latter matters for migration: a prompt authored for Claude may already
# be XML-tagged when it is transformed for a Gemini target.
# ---------------------------------------------------------------------------

_XML_TAG_RE = re.compile(
    r"<(?P<tag>instructions|context|example|input|task|output_format|constraints)>"
    r"\s*(?P<body>.*?)\s*</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)

_TAG_TITLES: dict[str, str] = {
    "instructions": "Instructions",
    "context": "Context",
    "example": "Examples",
    "input": "Input",
    "task": "Task",
    "output_format": "Output Format",
    "constraints": "Constraints",
}


def _xml_tags_to_markdown(prompt: str) -> tuple[str, bool]:
    if not _XML_TAG_RE.search(prompt):
        return prompt, False

    def _replace(match: re.Match[str]) -> str:
        tag = match.group("tag").lower()
        title = _TAG_TITLES.get(tag, tag.replace("_", " ").title())
        body = match.group("body").strip()
        return f"## {title}\n{body}" if body else f"## {title}"

    return _XML_TAG_RE.sub(_replace, prompt), True


def _sections_as_markdown(prompt: str) -> str:
    converted, changed = _xml_tags_to_markdown(prompt)
    if changed:
        return converted

    preamble, sections = _split_sections(prompt)
    if not sections:
        return prompt  # nothing recognized: safe no-op
    parts = [preamble] if preamble else []
    for title, _tag_key, body in sections:
        parts.append(f"## {title}\n{body}" if body else f"## {title}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Nano/small models: compress verbose instructions.
#
# Strips common hedging/filler phrases, then folds each remaining
# paragraph's sentences into terse imperative bullet points. Structural
# lines (recognized section headers, markdown headers, blank lines) are
# left untouched so this composes cleanly with the XML/Markdown structural
# rules above (see module docstring on rule ordering).
# ---------------------------------------------------------------------------

# Longer/more specific idioms first so the whole hedging phrase is removed
# cleanly; the trailing generic "please " catches anything left over.
_FILLER_PATTERNS: tuple[str, ...] = (
    r"\bplease\s+make\s+sure\s+to\s*",
    r"\bplease\s+make\s+sure\s+you\s*",
    r"\bmake\s+sure\s+you\s*",
    r"\bplease\s+ensure\s+that\s+you\s*",
    r"\bplease\s+ensure\s+that\s*",
    r"\bplease\s+ensure\s+you\s*",
    r"\bit\s+is\s+important\s+that\s+you\s*",
    r"\bit's\s+important\s+that\s+you\s*",
    r"\bplease\s+remember\s+to\s*",
    r"\bplease\s+try\s+to\s*",
    r"\bplease\s+note\s+that\s*",
    r"\bwe\s+would\s+like\s+you\s+to\s*",
    r"\bi\s+would\s+like\s+you\s+to\s*",
    r"\bkindly\s*",
    r"\bplease\s+",
)


def _strip_filler(text: str) -> str:
    for pattern in _FILLER_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text


def _is_structural_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True  # blank line: paragraph separator, always preserved
    if stripped.startswith("#"):
        return True
    if _HEADER_RE.match(line):
        return True
    if len(stripped) <= 40 and stripped.endswith(":"):
        return True
    return False


def _sentence_case(sentence: str) -> str:
    if not sentence:
        return sentence
    return sentence[0].upper() + sentence[1:]


def _terseify(prompt: str) -> str:
    output_lines: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        text = re.sub(r"\s{2,}", " ", _strip_filler(" ".join(buffer))).strip()
        buffer.clear()
        if not text:
            return
        sentences = [_sentence_case(s.strip()) for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if len(sentences) >= 2:
            output_lines.extend(f"- {sentence}" for sentence in sentences)
        elif sentences:
            output_lines.append(sentences[0])

    for line in prompt.split("\n"):
        if _is_structural_line(line):
            flush()
            output_lines.append(line)
        else:
            buffer.append(line.strip())
    flush()

    return "\n".join(output_lines).strip()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

RuleApplicability = Literal["all", "small_only"]


@dataclass(frozen=True)
class TransformRule:
    """One mechanical rewrite step within a :class:`FamilyCard`."""

    name: str
    description: str
    fn: Callable[[str], str]
    applies_to: RuleApplicability = "all"
    """``"all"``: always applied. ``"small_only"``: only applied when
    :func:`is_small_variant` is True for the target model — see the
    module docstring on why model size is a separate axis from family."""


@dataclass(frozen=True)
class FamilyCard:
    """The versioned rewrite-rule set for one model family."""

    family: str
    version: int
    description: str
    rules: tuple[TransformRule, ...]
    """Applied in order by :func:`apply_model_card_transform` — compression
    rules are ordered before structural rules so section headers survive
    intact for the structural rule to find (see module docstring)."""


_TERSEIFY_RULE = TransformRule(
    name="terseify_if_small",
    description=(
        "Strip hedging/filler phrases and fold each paragraph's sentences "
        "into terse imperative bullet points. Applied only when the target "
        "model looks like a nano/small/cheap variant."
    ),
    fn=_terseify,
    applies_to="small_only",
)

_XML_WRAP_RULE = TransformRule(
    name="xml_wrap_sections",
    description=(
        "Wrap recognized labeled sections (Instructions, Context, Examples, "
        "Input, Task, Output Format, Constraints) in XML-ish tags, per "
        "Anthropic's documented prompting guidance."
    ),
    fn=_wrap_sections_as_xml,
    applies_to="all",
)

_MARKDOWN_RULE = TransformRule(
    name="markdown_sections",
    description=(
        "Prefer markdown headers (## Instructions) over XML tags for "
        "structuring a prompt, per Gemini's documented prompting guidance. "
        "Converts existing XML-tagged sections to markdown headers too."
    ),
    fn=_sections_as_markdown,
    applies_to="all",
)

_FAMILY_CARDS: dict[str, FamilyCard] = {
    "anthropic": FamilyCard(
        family="anthropic",
        version=1,
        description="Claude models (Claude API, Bedrock, Vertex AI) — XML-tagged sections.",
        rules=(_TERSEIFY_RULE, _XML_WRAP_RULE),
    ),
    "gemini": FamilyCard(
        family="gemini",
        version=1,
        description="Gemini models (Gemini API, Vertex AI) — markdown-headed sections.",
        rules=(_TERSEIFY_RULE, _MARKDOWN_RULE),
    ),
    "openai": FamilyCard(
        family="openai",
        version=1,
        description=(
            "GPT-family models (OpenAI, Azure OpenAI). No single structural "
            "convention documented as strongly as Anthropic's XML or "
            "Gemini's Markdown guidance, so only the universal small-model "
            "compression rule applies."
        ),
        rules=(_TERSEIFY_RULE,),
    ),
    "llama": FamilyCard(
        family="llama",
        version=1,
        description=(
            "Open-weight/self-hosted bucket (Llama, Mistral, Gemma, Qwen, "
            "Phi, DeepSeek, ...) across any serving provider. No "
            "family-specific structural rule yet — compression only. A "
            "future contribution could split this into per-vendor cards."
        ),
        rules=(_TERSEIFY_RULE,),
    ),
    "generic": FamilyCard(
        family="generic",
        version=1,
        description="Fallback for any provider/model without a specific rule set.",
        rules=(_TERSEIFY_RULE,),
    ),
}


def get_transform_rules(family: str) -> FamilyCard:
    """Look up the versioned rule set for ``family``.

    Never raises: an unrecognized family name (e.g. a stale value from a
    caller, or a future family the registry hasn't been extended with
    yet) falls back to the ``"generic"`` card rather than raising.
    """
    return _FAMILY_CARDS.get(family, _FAMILY_CARDS["generic"])


def applicable_rules(target_model: str) -> list[TransformRule]:
    """Which rules will *actually* fire for ``target_model``, in order.

    Unlike :func:`get_transform_rules` (which returns every rule a family
    *could* run, including size-gated ones), this accounts for
    :func:`is_small_variant` and returns only the rules that will really
    apply — useful for debugging/inspecting a specific migration target
    without re-deriving the family/size logic by hand.
    """
    family = resolve_family(target_model)
    card = get_transform_rules(family)
    small = is_small_variant(target_model)
    return [rule for rule in card.rules if rule.applies_to == "all" or small]


def apply_model_card_transform(prompt: str, target_model: str) -> str:
    """Apply ``target_model``'s family transform rules to ``prompt``.

    Pure function: no I/O, no network call, no LLM call, no randomness —
    the same ``(prompt, target_model)`` pair always produces the same
    output. See the module docstring for family resolution, rule
    ordering, and versioning.

    Parameters
    ----------
    prompt:
        The rendered prompt text to rewrite (e.g. a stage's system
        prompt). Not a chat-messages list — callers that need per-message
        transforms should call this once per message content string.
    target_model:
        A LiteLLM model string identifying the migration target.

    Returns
    -------
    The rewritten prompt. If no rule for the resolved family actually
    changes anything (unstructured prose, a large non-"nano" model in a
    family with no structural rule, ...), this returns ``prompt``
    unchanged.
    """
    result = prompt
    for rule in applicable_rules(target_model):
        result = rule.fn(result)
    return result
