"""Flatten + diff helpers for the eval harness.

PropertyData dicts (nested) are flattened into dot-path dicts so per-field comparisons
are straightforward. The "effective gold" used for scoring is `agreed_fields ∪ corrections`,
both of which are already flat dot-path dicts.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DiffCategory(str, Enum):
    MATCH = "MATCH"
    OMISSION = "OMISSION"
    HALLUCINATION = "HALLUCINATION"
    WRONG = "WRONG"


@dataclass(frozen=True)
class FieldDiff:
    field: str
    cheap_value: Any
    gold_value: Any
    category: DiffCategory


def flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            out.update(flatten(val, path))
        else:
            out[path] = val
    return out


def _values_match(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) < 1e-9
    if isinstance(a, str) and isinstance(b, str):
        return a.strip() == b.strip()
    return a == b


def compute_agreement(
    model_outputs: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Given {model_name: nested_property_dict}, return:
    - agreed: {dot.path: common_value} — fields where every model agrees
    - disagreed: {dot.path: {model_name: value}} — fields with any disagreement
    """
    if not model_outputs:
        return {}, {}

    flattened = {name: flatten(out) for name, out in model_outputs.items()}
    all_fields: set[str] = set()
    for fl in flattened.values():
        all_fields.update(fl.keys())

    agreed: dict[str, Any] = {}
    disagreed: dict[str, dict[str, Any]] = {}

    for field in sorted(all_fields):
        values = {name: fl.get(field) for name, fl in flattened.items()}
        first = next(iter(values.values()))
        if all(_values_match(first, v) for v in values.values()):
            agreed[field] = first
        else:
            disagreed[field] = values

    return agreed, disagreed


def effective_gold(agreed: dict[str, Any], corrections: dict[str, Any]) -> dict[str, Any]:
    """Corrections override / extend the agreed-fields set."""
    return {**agreed, **corrections}


def diff_against_gold(cheap: dict[str, Any], gold_flat: dict[str, Any]) -> list[FieldDiff]:
    """`cheap` is a nested PropertyData dict; `gold_flat` is the effective gold (flat)."""
    cheap_flat = flatten(cheap)
    diffs: list[FieldDiff] = []
    for field, gold_val in gold_flat.items():
        cheap_val = cheap_flat.get(field)
        if _values_match(cheap_val, gold_val):
            cat = DiffCategory.MATCH
        elif cheap_val is None:
            cat = DiffCategory.OMISSION
        elif gold_val is None:
            cat = DiffCategory.HALLUCINATION
        else:
            cat = DiffCategory.WRONG
        diffs.append(FieldDiff(field, cheap_val, gold_val, cat))
    return diffs
