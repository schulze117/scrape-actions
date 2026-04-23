"""Console report for eval.run."""

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from extract.eval.compare import DiffCategory, FieldDiff


@dataclass
class CaseResult:
    source: str
    external_id: str
    cheap_output: dict[str, Any] | None
    error: str | None
    effective_gold: dict[str, Any]
    skipped_fields: dict[str, dict[str, Any]]  # field -> {model_name: value}
    diffs: list[FieldDiff] = field(default_factory=list)


def _short(value: Any, width: int = 28) -> str:
    s = "None" if value is None else repr(value)
    if len(s) > width:
        s = s[: width - 1] + "..."
    return s


def render(results: list[CaseResult], model_name: str, dataset_path: Path) -> str:
    lines: list[str] = []
    bar = "=" * 100

    lines.append(bar)
    lines.append(f"EVAL  model={model_name} | cases={len(results)} | dataset={dataset_path}")
    lines.append(bar)
    lines.append("")

    # 1. Per-field aggregate
    per_field: dict[str, dict[str, int]] = defaultdict(
        lambda: {"match": 0, "omission": 0, "hallucination": 0, "wrong": 0}
    )
    for r in results:
        for d in r.diffs:
            per_field[d.field][d.category.value.lower()] += 1

    if per_field:
        rows = []
        for field_name, counts in per_field.items():
            total = sum(counts.values())
            accuracy = counts["match"] / total if total else 0.0
            rows.append(
                (
                    field_name,
                    counts["match"],
                    total,
                    accuracy,
                    counts["omission"],
                    counts["hallucination"],
                    counts["wrong"],
                )
            )
        rows.sort(key=lambda r: (r[3], -r[2]))

        lines.append("PER-FIELD ACCURACY (worst first)")
        lines.append(f"{'field':<42} {'accuracy':>14} {'omit':>5} {'hall':>5} {'wrong':>6}")
        lines.append("-" * 100)
        for fname, m, t, acc, om, hl, wr in rows:
            acc_cell = f"{m}/{t} ({acc * 100:>3.0f}%)"
            lines.append(f"{fname:<42} {acc_cell:>14} {om:>5} {hl:>5} {wr:>6}")
        lines.append("")
    else:
        lines.append("No fields scored - empty effective gold across all cases.")
        lines.append("")

    # 2. Disagreements between gold models (skipped)
    skipped_counts: dict[str, int] = defaultdict(int)
    for r in results:
        for fname in r.skipped_fields:
            skipped_counts[fname] += 1
    if skipped_counts:
        lines.append(
            "DISAGREEMENTS BETWEEN GOLD MODELS (skipped - add a correction to score these):"
        )
        for fname, count in sorted(skipped_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {fname:<42} {count} cases")
        lines.append("")

    # 3. Per-case diffs
    cases_with_diffs = [
        r for r in results if any(d.category != DiffCategory.MATCH for d in r.diffs)
    ]
    if cases_with_diffs:
        lines.append("PER-CASE DIFFS:")
        for r in cases_with_diffs:
            lines.append(f"--- {r.external_id} ({r.source}) ---")
            for d in r.diffs:
                if d.category == DiffCategory.MATCH:
                    continue
                lines.append(
                    f"  {d.field:<42} cheap={_short(d.cheap_value):<28} "
                    f"gold={_short(d.gold_value):<28} [{d.category.value}]"
                )
            lines.append("")

    # 4. Cheap-model failures
    failed = [r for r in results if r.error]
    if failed:
        lines.append("CHEAP-MODEL FAILURES:")
        for r in failed:
            lines.append(f"  {r.external_id} ({r.source}): {r.error}")
        lines.append("")

    return "\n".join(lines)
