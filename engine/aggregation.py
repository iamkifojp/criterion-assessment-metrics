"""
Grade aggregation: five selectable calculation methods.

Given a chronological series of band scores for one criterion, produce a single
"final suggestion". The teacher picks one of five algorithms (the
``CALCULATION_METHODS`` dropdown); each operates on the values ordered oldest
-> newest:

``Simple Average``
    Plain arithmetic mean of every score.

``60/40 Recency``
    The original linear-interpolation model with fixed boundaries: the newest
    score is weighted 0.60 and the oldest 0.40, entries between them linearly
    distributed:

        w_i = 0.40 + (0.60 - 0.40) * i / (n - 1)
        suggestion = sum(w_i * score_i) / sum(w_i)

``EMA``
    Exponential moving average seeded with the oldest score, then folded
    forward with a fixed smoothing factor of 0.3:

        EMA_t = value_t * 0.3 + EMA_{t-1} * 0.7

``Z-Score Adjusted``
    Outlier-discounted mean: scores whose |z-score| exceeds 2.0 (against the
    student's own mean/stdev) are silently dropped, then the survivors are
    simple-averaged.

``Weighted Median``
    The 60/40 linear weights are assigned chronologically, then the scores are
    sorted by *value* and the grade where the cumulative weight crosses 50% of
    the total is returned.

The aggregation operates on plain ``(timestamp, value)`` pairs so it is
independent of the rest of the engine and trivially unit-testable, but a
convenience helper is provided to run it directly on a :class:`Student`.

The legacy slider-driven API (:class:`RecencyWeightConfig` /
:func:`recency_weighted_score`) is retained for the demo and verification
scripts; the app now drives everything through ``method=`` selection.

This module also hosts the UI-free *context-filtering pipeline* that feeds the
prompt synthesis engine: best/worst evidence slicing and trend summarisation.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from .models import Criterion, Student


@dataclass
class RecencyWeightConfig:
    """Slider configuration for recency weighting."""

    oldest_weight: float = 0.40
    newest_weight: float = 0.60

    def __post_init__(self) -> None:
        if self.oldest_weight <= 0 or self.newest_weight <= 0:
            raise ValueError("Weights must be positive.")


@dataclass
class AggregationResult:
    """Full output of an aggregation run, for transparency in the UI."""

    criterion: str
    suggestion: float                       # weighted mean (unrounded)
    rounded_band: int                       # nearest legal 0-8 band
    n: int                                  # number of scores used
    simple_mean: float                      # unweighted mean, for comparison
    weights: List[float]                    # normalized weights, oldest->newest
    timeline: List[Tuple[datetime, int]]    # (timestamp, value) used


def _linear_weights(n: int, cfg: RecencyWeightConfig) -> List[float]:
    """Raw linear weights from oldest_weight -> newest_weight."""
    if n == 1:
        return [cfg.newest_weight]
    span = cfg.newest_weight - cfg.oldest_weight
    return [cfg.oldest_weight + span * i / (n - 1) for i in range(n)]


# --------------------------------------------------------------------------
# Calculation methods (dropdown selection)
# --------------------------------------------------------------------------

# Fixed boundaries for the 60/40 methods: newest strictly 60%, oldest 40%.
_FIXED_60_40 = RecencyWeightConfig(oldest_weight=0.40, newest_weight=0.60)
_EMA_ALPHA = 0.3          # smoothing factor for the EMA method
_Z_THRESHOLD = 2.0        # |z| above this is discarded as an anomaly


def simple_average(values: Sequence[float]) -> float:
    """Standard arithmetic mean of all grades."""
    return sum(values) / len(values)


def recency_60_40(values: Sequence[float]) -> float:
    """Linear 60/40 recency weighting with hardcoded boundaries.

    Reuses the linear-interpolation weights: newest counts 0.60, oldest 0.40,
    intervening grades linearly distributed between the two."""
    if len(values) == 1:      # a lone grade passes through exactly
        return float(values[0])
    raw = _linear_weights(len(values), _FIXED_60_40)
    return sum(w * v for w, v in zip(raw, values)) / sum(raw)


def exponential_moving_average(values: Sequence[float]) -> float:
    """EMA seeded with the oldest grade, alpha = 0.3.

    Each subsequent grade folds in as ``EMA = v * 0.3 + EMA_prev * 0.7``."""
    ema = float(values[0])
    for v in values[1:]:
        ema = v * _EMA_ALPHA + ema * (1.0 - _EMA_ALPHA)
    return ema


def zscore_adjusted_average(values: Sequence[float]) -> float:
    """Mean of the grades that survive |z| <= 2.0 outlier filtering.

    Uses the population standard deviation of the student's own grades. A zero
    spread (all grades identical) means no outliers by definition."""
    n = len(values)
    m = sum(values) / n
    sd = (sum((v - m) ** 2 for v in values) / n) ** 0.5
    if sd == 0:
        return m
    kept = [v for v in values if abs((v - m) / sd) <= _Z_THRESHOLD]
    if not kept:          # unreachable in practice, but never divide by zero
        return m
    return sum(kept) / len(kept)


def weighted_median(values: Sequence[float]) -> float:
    """Grade at the 50% cumulative-weight point under 60/40 linear weights.

    Weights are assigned chronologically (oldest 0.40 -> newest 0.60), the
    grades are then sorted by value, and the first grade whose cumulative
    weight reaches half the total weight is returned."""
    raw = _linear_weights(len(values), _FIXED_60_40)
    pairs = sorted(zip(values, raw), key=lambda p: p[0])
    half = sum(raw) / 2.0
    cum = 0.0
    for value, weight in pairs:
        cum += weight
        if cum >= half:
            return float(value)
    return float(pairs[-1][0])   # float rounding safety net


METHOD_SIMPLE_AVERAGE = "Simple Average"
METHOD_60_40 = "60/40 Recency"
METHOD_EMA = "EMA"
METHOD_ZSCORE = "Z-Score Adjusted"
METHOD_WEIGHTED_MEDIAN = "Weighted Median"

_METHOD_FUNCS = {
    METHOD_SIMPLE_AVERAGE: simple_average,
    METHOD_60_40: recency_60_40,
    METHOD_EMA: exponential_moving_average,
    METHOD_ZSCORE: zscore_adjusted_average,
    METHOD_WEIGHTED_MEDIAN: weighted_median,
}

# Dropdown order in the UI.
CALCULATION_METHODS = [
    METHOD_SIMPLE_AVERAGE,
    METHOD_60_40,
    METHOD_EMA,
    METHOD_ZSCORE,
    METHOD_WEIGHTED_MEDIAN,
]

# Human-facing dropdown labels. Display-only: the stored method names above
# stay the persisted values; keyed by the METHOD_* constants so the label
# strings can never drift from the method identities.
METHOD_LABELS = {
    METHOD_SIMPLE_AVERAGE: "Simple Average (Equal weighting)",
    METHOD_60_40: "60/40 Recency (Best for < 10 assignments)",
    METHOD_WEIGHTED_MEDIAN: "Weighted Median (Best for 15+ assignments)",
    METHOD_EMA: "EMA (Highly reactive to newest trend)",
    METHOD_ZSCORE: "Z-Score Adjusted (Drops extreme outliers)",
}

# The 60/40 model matches the app's previous default behaviour.
DEFAULT_CALCULATION_METHOD = METHOD_60_40


def calculate_final_grade(values: Sequence[float], method: str) -> float:
    """Run one calculation method over a chronological (oldest -> newest)
    series of grades. Unknown method names fall back to the default."""
    func = _METHOD_FUNCS.get(method, _METHOD_FUNCS[DEFAULT_CALCULATION_METHOD])
    return func(values)


# --------------------------------------------------------------------------
# School grade lookups (MYP Grade + School Grade)
# --------------------------------------------------------------------------
#
# School-specific report-card grades, NOT IB's published method. Both are
# banded lookups on the SUM of a student's final criterion grades, with the
# band table chosen by how many MYP criteria were assessed this term (2, 3
# or 4). The boundary values are fixed School policy.

# School-determined MYP grade boundaries. Keyed by criteria count.
# Each tuple is (low, high, grade), inclusive. MYP grade runs 1..7.
MYP_GRADE_BOUNDS = {
    2: [(1,3,1),(4,5,2),(6,7,3),(8,9,4),(10,11,5),(12,14,6),(15,16,7)],
    3: [(1,4,1),(5,7,2),(8,11,3),(12,14,4),(15,18,5),(19,21,6),(22,24,7)],
    4: [(1,5,1),(6,9,2),(10,14,3),(15,18,4),(19,23,5),(24,27,6),(28,32,7)],
}

# School grade boundaries (criterion sum + Effort/English use). Grade runs 1..10.
SCHOOL_GRADE_BOUNDS = {
    2: [(1,3,1),(4,5,2),(6,7,3),(8,9,4),(10,11,5),(12,13,6),(14,15,7),(16,17,8),(18,19,9),(20,21,10)],
    3: [(1,3,1),(4,6,2),(7,9,3),(10,12,4),(13,15,5),(16,18,6),(19,21,7),(22,24,8),(25,27,9),(28,29,10)],
    4: [(1,3,1),(4,7,2),(8,11,3),(12,15,4),(16,19,5),(20,23,6),(24,27,7),(28,31,8),(32,34,9),(35,37,10)],
}


def _banded_grade(total: int, bounds: List[Tuple[int, int, int]]) -> int:
    """Look ``total`` up in an inclusive (low, high, grade) band table.

    Out-of-range totals clamp: at or below the lowest band -> lowest grade
    (so an all-missing total of 0 maps to grade 1), at or above the highest
    band -> top grade."""
    if total <= bounds[0][0]:
        return bounds[0][2]
    if total >= bounds[-1][1]:
        return bounds[-1][2]
    for low, high, grade in bounds:
        if low <= total <= high:
            return grade
    return bounds[-1][2]   # bands are contiguous; unreachable safety net


def myp_grade(crit_total: int, n_criteria: int) -> Optional[int]:
    """School's MYP report grade (1-7) from the criterion-grade sum.

    Effort is NOT part of this lookup. Returns ``None`` when ``n_criteria``
    is not 2, 3 or 4 (the UI/exports show N/A)."""
    bounds = MYP_GRADE_BOUNDS.get(n_criteria)
    if bounds is None:
        return None
    return _banded_grade(crit_total, bounds)


def school_grade(crit_total: int, effort: int, n_criteria: int) -> Optional[int]:
    """School's school grade (1-10) from criterion sum + Effort/English use.

    Returns ``None`` when ``n_criteria`` is not 2, 3 or 4."""
    bounds = SCHOOL_GRADE_BOUNDS.get(n_criteria)
    if bounds is None:
        return None
    return _banded_grade(crit_total + effort, bounds)


def method_score(
    scores: Sequence[Tuple[datetime, int]],
    method: str = DEFAULT_CALCULATION_METHOD,
) -> Optional[AggregationResult]:
    """Compute the selected method's suggestion for a criterion timeline.

    ``scores`` is a sequence of (timestamp, band) pairs in any order; they are
    sorted oldest -> newest internally. Returns ``None`` when there are no
    scores to aggregate."""
    ordered = sorted(scores, key=lambda p: p[0])
    if not ordered:
        return None

    values = [v for _, v in ordered]
    n = len(values)
    suggestion = calculate_final_grade(values, method)

    # Chronological weights are only meaningful for the weight-based methods;
    # the others report an empty list.
    if method in (METHOD_60_40, METHOD_WEIGHTED_MEDIAN):
        raw = _linear_weights(n, _FIXED_60_40)
        total = sum(raw)
        weights = [w / total for w in raw]
    else:
        weights = []

    return AggregationResult(
        criterion="",
        suggestion=suggestion,
        rounded_band=int(max(0, min(8, round(suggestion)))),
        n=n,
        simple_mean=sum(values) / n,
        weights=weights,
        timeline=list(ordered),
    )


def recency_weighted_score(
    scores: Sequence[Tuple[datetime, int]],
    config: Optional[RecencyWeightConfig] = None,
) -> Optional[AggregationResult]:
    """Compute the recency-weighted suggestion for a criterion timeline.

    ``scores`` is a sequence of (timestamp, band) pairs in any order; they are
    sorted oldest -> newest internally. Returns ``None`` when there are no
    scores to aggregate.
    """
    cfg = config or RecencyWeightConfig()
    ordered = sorted(scores, key=lambda p: p[0])
    if not ordered:
        return None

    values = [v for _, v in ordered]
    n = len(values)

    raw = _linear_weights(n, cfg)
    total_w = sum(raw)
    norm = [w / total_w for w in raw]

    suggestion = sum(w * v for w, v in zip(norm, values))
    simple_mean = sum(values) / n

    return AggregationResult(
        criterion="",
        suggestion=suggestion,
        rounded_band=int(max(0, min(8, round(suggestion)))),
        n=n,
        simple_mean=simple_mean,
        weights=norm,
        timeline=list(ordered),
    )


def aggregate_student_criterion(
    student: Student,
    criterion: Criterion,
    config: Optional[RecencyWeightConfig] = None,
    include_assignments: Optional[Set[str]] = None,
    method: Optional[str] = None,
    extra_scores: Optional[Sequence[Tuple[datetime, int]]] = None,
    exclude_assignments: Optional[Set[str]] = None,
) -> Optional[AggregationResult]:
    """Run one criterion's final-grade calculation for one student.

    Pass ``method`` (a :data:`CALCULATION_METHODS` name) to use the dropdown
    algorithms; otherwise the legacy slider path runs with ``config``.

    Only scores that are both valid and flagged ``include_in_report=True`` are
    fed to the calculation; toggling ``include_in_report`` to False on any
    score removes it from the result immediately, without deleting the record.

    ``include_assignments`` optionally restricts the calculation to scores whose
    ``assignment`` is in the supplied set. This lets the prompt engine compute a
    *current-term-only* band (passing the term's assignment names) while exports
    and the cockpit keep aggregating the full year by leaving it ``None``.

    ``extra_scores`` are synthetic (timestamp, band) points folded into the
    timeline before calculation — the Missing=0 pipeline uses this to inject a
    mathematical 0 for each unsubmitted assignment. ``exclude_assignments``
    drops scores from the named assignments entirely (the per-student
    "Excused" flag), without touching the stored records.
    """
    crit = Criterion(criterion)
    scores = [
        (s.timestamp, s.value)
        for s in student.criterion_scores(crit, valid_only=True)
        if s.include_in_report
        and (include_assignments is None or s.assignment in include_assignments)
        and (exclude_assignments is None or s.assignment not in exclude_assignments)
    ]
    if extra_scores:
        scores.extend(extra_scores)
    if method is not None:
        result = method_score(scores, method)
    else:
        result = recency_weighted_score(scores, config)
    if result is not None:
        result.criterion = crit.value
    return result


# --------------------------------------------------------------------------
# Context-filtering pipeline (feeds the prompt synthesis engine)
# --------------------------------------------------------------------------
#
# These helpers are deliberately UI-free and operate on plain data so they are
# trivially unit-testable and independent of Streamlit. The Streamlit front end
# gathers a student's current-term scores into ``Evidence`` items and asks this
# module to (a) slice the best/worst pieces for Strengths/Growths and (b) reduce
# a criterion's timeline to a one-line trajectory sentence.


@dataclass
class Evidence:
    """One qualitative data point distilled from a graded score.

    Carries the raw material the LLM turns into narrative: the ticked rubric
    keywords and the teacher's per-task remark, tagged with the band so the
    pipeline can rank pieces highest-to-lowest.
    """

    assignment: str
    criterion: str
    score: int
    timestamp: datetime
    keywords: List[str] = field(default_factory=list)
    comment: str = ""

    @property
    def has_qualitative(self) -> bool:
        """True when this piece carries keywords or a remark worth sending."""
        return bool(self.keywords) or bool(self.comment.strip())

    def as_text(self) -> str:
        """Compact human/LLM-readable line, e.g.
        ``Diptych (B, grade 7): "strong tonal control"``.

        The comment is preferred over the keywords list because the grading
        workspace auto-builds each comment *from* the checked keywords (e.g.
        "Strengths: kw1, kw2." plus any custom note), so emitting both halves
        near-duplicates the same content. When the comment is non-empty only it
        is quoted; the raw keyword list is used solely as a fallback for pieces
        that carry keywords but no comment. Keywords still qualify a piece for
        selection (see :attr:`has_qualitative`) even when they aren't printed.
        """
        bits = f"{self.assignment} ({self.criterion}, grade {self.score})"
        if self.comment.strip():
            return bits + f": “{self.comment.strip()}”"
        if self.keywords:
            return bits + ": " + ", ".join(self.keywords)
        return bits


def select_evidence(
    items: Iterable[Evidence],
    n_strengths: int,
    n_growth: int,
    qualitative_only: bool = True,
) -> Tuple[List[Evidence], List[Evidence]]:
    """Slice evidence into Strengths (highest scores) and Growths (lowest).

    The pool is ranked by band (ties broken by recency — newer first). The top
    ``n_strengths`` become Strength material and the bottom ``n_growth`` become
    Growth material. An item is never placed in both lists: when the pool is too
    small to satisfy both fully, Strengths are filled first from the top and
    Growths then drawn from the remaining lowest pieces.

    With ``qualitative_only`` (default) pieces carrying no keywords and no remark
    are dropped first — there is nothing for the model to paraphrase from a bare
    band number, and forwarding empties only wastes tokens.
    """
    pool = list(items)
    if qualitative_only:
        pool = [e for e in pool if e.has_qualitative]
    # Highest band first; for equal bands prefer the more recent piece.
    ranked = sorted(pool, key=lambda e: (e.score, e.timestamp), reverse=True)

    strengths: List[Evidence] = ranked[: max(0, n_strengths)]
    chosen = set(id(e) for e in strengths)
    # Growths: lowest-scoring pieces not already claimed as strengths.
    remaining = [e for e in reversed(ranked) if id(e) not in chosen]
    growths: List[Evidence] = remaining[: max(0, n_growth)]
    return strengths, growths


@dataclass
class TrendInfo:
    """The shape of one criterion's progression across a term.

    ``direction`` / ``first`` / ``last`` / ``delta`` / ``n`` are the original
    first-vs-last read. The remaining fields describe the *shape* of the path so
    the narrative can go beyond "up" / "down" without the engine ever
    speculating — every value below is a deterministic fact about the series:

    vmin / vmax : lowest / highest band seen.
    range       : spread (``vmax - vmin``).
    typical     : the modal band when one value occupies at least half the
                  points (a clear "mostly at band X"), else ``None``.
    min_pos     : "early" / "mid" / "late" third of the timeline where the low
                  first occurs — set only when the low sits strictly BELOW both
                  endpoints (a genuine interior dip), else ``None``.
    max_pos     : same, for a peak strictly ABOVE both endpoints.
    recovery    : ``last - vmin`` — how far the series climbed back from its low.
    """

    direction: str   # "positive" | "negative" | "steady"
    first: int
    last: int
    delta: int
    n: int
    vmin: int = 0
    vmax: int = 0
    range: int = 0
    typical: Optional[int] = None
    min_pos: Optional[str] = None
    max_pos: Optional[str] = None
    recovery: int = 0


def _timeline_third(idx: int, n: int) -> str:
    """Which third of an ``n``-point timeline index ``idx`` falls in."""
    if n <= 1:
        return "mid"
    frac = idx / (n - 1)
    if frac < 1 / 3:
        return "early"
    if frac < 2 / 3:
        return "mid"
    return "late"


def trend_for_series(
    series: Sequence[Tuple[datetime, int]]
) -> Optional[TrendInfo]:
    """Reduce a (timestamp, band) timeline to a direction, endpoints and shape.

    Returns ``None`` for fewer than two points (no trajectory to describe). The
    direction compares the chronological first and last bands, so a dip-then-
    recover still reads by its net movement across the term; the extra shape
    fields (spread, modal band, interior dip/peak and its rough position) let
    the formatter narrate that dip explicitly rather than flattening it.
    """
    ordered = sorted(series, key=lambda p: p[0])
    values = [v for _, v in ordered]
    if len(values) < 2:
        return None
    delta = values[-1] - values[0]
    direction = "positive" if delta > 0 else "negative" if delta < 0 else "steady"
    first, last = values[0], values[-1]
    vmin, vmax = min(values), max(values)

    # Modal band, but only when it is a *unique* mode covering at least half the
    # points — otherwise there is no honest "mostly at band X" to claim.
    counts = Counter(values)
    mode_val, mode_n = counts.most_common(1)[0]
    unique_mode = sum(1 for c in counts.values() if c == mode_n) == 1
    typical = mode_val if (unique_mode and mode_n * 2 >= len(values)) else None

    # An interior dip: the low sits strictly below both endpoints. A peak: the
    # high sits strictly above both. Position = the third where it first occurs.
    min_pos = (_timeline_third(values.index(vmin), len(values))
               if vmin < first and vmin < last else None)
    max_pos = (_timeline_third(values.index(vmax), len(values))
               if vmax > first and vmax > last else None)

    return TrendInfo(
        direction=direction, first=first, last=last, delta=delta, n=len(values),
        vmin=vmin, vmax=vmax, range=vmax - vmin, typical=typical,
        min_pos=min_pos, max_pos=max_pos, recovery=last - vmin,
    )


def _detailed_trend_sentence(label: str, info: TrendInfo,
                             fmark: str, lmark: str) -> str:
    """1–2 clause narration of a TrendInfo's whole path (deterministic)."""
    if info.range == 0:
        return (f"{label} stayed at grade {info.last} across "
                f"{info.n} pieces{lmark}.")
    head = (f"{label} started at grade {info.first}{fmark} and finished at "
            f"grade {info.last}{lmark}")
    detail: List[str] = []
    # Only narrate the spread when it exceeds the net move — otherwise the
    # endpoints already tell the whole story (a plain monotonic run).
    if info.range > abs(info.delta):
        lead = f"marks ranged between grade {info.vmin} and grade {info.vmax}"
        if info.typical is not None:
            lead += f", mostly at grade {info.typical}"
        detail.append(lead)
    if info.min_pos:
        art = "an" if info.min_pos == "early" else "a"
        detail.append(f"with {art} {info.min_pos}-term dip to grade {info.vmin} "
                      f"before climbing back")
    elif info.max_pos:
        detail.append(f"peaking at grade {info.vmax} {info.max_pos}-term")
    if not detail:
        return head + "."
    return head + "; " + ", ".join(detail) + "."


def format_trend_sentence(
    criterion_label: str,
    info: TrendInfo,
    first_label: str = "",
    last_label: str = "",
    detail: str = "compact",
) -> str:
    """Render a TrendInfo as a readable clause for the prompt.

    ``first_label`` / ``last_label`` are optional time markers (e.g. an
    assignment date) appended for orientation.

    ``detail`` picks the depth:

    - ``"compact"`` (default, ~today's length): the original first-vs-last
      sentence, plus a spread clause only when the swing is wider than the net
      move, e.g. *"Criterion B showed a decline from grade 6 (May 10) to grade 5
      (Jul 24), with marks ranging between grade 3 and grade 6."*
    - ``"detailed"``: 1–2 clauses narrating the path, including any interior dip
      or peak and the modal grade.

    All phrasing is deterministic template text derived from the math — the LLM
    paraphrases it; the engine never speculates.
    """
    fmark = f" ({first_label})" if first_label else ""
    lmark = f" ({last_label})" if last_label else ""
    if detail == "detailed":
        return _detailed_trend_sentence(criterion_label, info, fmark, lmark)
    if info.direction == "steady":
        core = (f"{criterion_label} held steady at grade {info.last}"
                f" across {info.n} pieces{lmark}")
    else:
        word = ("positive progression" if info.direction == "positive"
                else "a decline")
        core = (f"{criterion_label} showed {word} from grade {info.first}{fmark} "
                f"to grade {info.last}{lmark}")
    if info.range > abs(info.delta):
        core += (f", with marks ranging between grade {info.vmin} and "
                 f"grade {info.vmax}")
    return core + "."
