"""
Narrative generator interface.

Same abstraction principle as app/embeddings/base.py: the comparison
report's PROSE (executive summary, per-item description, recommendations)
goes through an object that implements NarrativeGenerator, instead of
app/analysis/report_builder.py calling a specific LLM SDK directly.
The overall_match_score and every classification (match/partial_match/
gap) are computed in app/analysis/matcher.py and NEVER pass through
here - only already-decided, already-scored data gets described in
words. Swapping the provider (template -> Claude, or a different LLM
later) is a factory change in app/analysis/__init__.py, not a rewrite
of report_builder.py.

One generate() call covers the whole report (not one call per item) -
both so a hosted-LLM implementation isn't forced into N small, costly
requests, and so the executive summary and per-item narratives read as
one coherent document instead of N independently-written fragments.
An implementation must not introduce claims beyond the ComparisonResult
it's given, and must never write a narrative for an item with no
sources (see report_builder.py's hallucination guard) - each
provider's own docstring explains how it satisfies that in practice.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.analysis.models import ComparisonResult


@dataclass
class ReportNarrative:
    """One NarrativeGenerator call's full output for one report."""

    executive_summary: str
    # Keyed by ComparisonItem.input_chunk_index. Only items with at
    # least one source may have an entry - report_builder.py supplies
    # the fixed no-evidence string itself for every "gap" item without
    # sources, never asking a NarrativeGenerator to invent one.
    item_narratives: dict[int, str] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)


class NarrativeGenerator(ABC):
    """Abstract base class for all report-narrative providers."""

    @abstractmethod
    def generate(self, comparison: ComparisonResult) -> ReportNarrative:
        """
        Only called when comparison.has_any_evidence is True - see
        report_builder.py's hallucination guard for what happens
        otherwise (this is never invoked with zero evidence to work
        from).
        """

        raise NotImplementedError
