"""ShangooliShop print-size catalog used by artwork certification.

Edit PRODUCT_CATALOG in one place when the live Printify offering changes.
Sizes are stored in horizontal orientation; vertical artwork swaps dimensions.
"""
from __future__ import annotations

PRODUCT_CATALOG: dict[str, tuple[tuple[int, int], ...]] = {
    "3:2": ((12, 8), (18, 12), (24, 16), (30, 20), (36, 24), (48, 32), (60, 40)),
    "4:3": ((12, 9), (16, 12), (20, 15), (24, 18), (32, 24), (40, 30), (48, 36)),
    "5:4": ((10, 8), (15, 12), (20, 16), (25, 20), (30, 24), (40, 32), (50, 40)),
    "14:11": ((14, 11), (28, 22), (42, 33), (56, 44)),
    "1:1": ((12, 12), (18, 18), (24, 24), (30, 30), (36, 36), (48, 48)),
}


def canonical_ratio(label: str) -> str:
    """Return horizontal form for a ratio label (2:3 -> 3:2)."""
    left, right = (int(value) for value in label.split(":", 1))
    if left < right:
        left, right = right, left
    return f"{left}:{right}"


def product_sizes_for_ratio(ratio: str, orientation: str) -> tuple[tuple[int, int], ...]:
    sizes = PRODUCT_CATALOG.get(canonical_ratio(ratio), ())
    if orientation == "vertical":
        return tuple((height, width) for width, height in sizes)
    return sizes
