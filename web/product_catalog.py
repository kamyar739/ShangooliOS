"""Configurable ShangooliShop print-product catalog.

Add, remove, or disable products in PRODUCT_CATALOG. Existing callers may
continue using product_sizes_for_ratio(), while newer production code can use
the full PrintProduct definitions returned by products_for_ratio().
"""

from __future__ import annotations

from dataclasses import dataclass, replace


DEFAULT_DPI = 300
DEFAULT_FILE_FORMAT = "PNG"


@dataclass(frozen=True, slots=True)
class PrintProduct:
    key: str
    ratio: str
    width_inches: int
    height_inches: int
    dpi: int = DEFAULT_DPI
    file_format: str = DEFAULT_FILE_FORMAT
    enabled: bool = True

    @property
    def pixel_dimensions(self) -> tuple[int, int]:
        return (
            round(self.width_inches * self.dpi),
            round(self.height_inches * self.dpi),
        )


def canonical_ratio(label: str) -> str:
    """Return the horizontal form of a ratio label, such as 2:3 -> 3:2."""
    left, right = (int(value.strip()) for value in label.split(":", 1))

    if left <= 0 or right <= 0:
        raise ValueError(f"Invalid ratio: {label}")

    if left < right:
        left, right = right, left

    return f"{left}:{right}"


def _product(
    ratio: str,
    width: int,
    height: int,
    *,
    dpi: int = DEFAULT_DPI,
    file_format: str = DEFAULT_FILE_FORMAT,
    enabled: bool = True,
) -> PrintProduct:
    ratio_slug = ratio.replace(":", "x")

    return PrintProduct(
        key=f"{ratio_slug}-{width}x{height}",
        ratio=ratio,
        width_inches=width,
        height_inches=height,
        dpi=dpi,
        file_format=file_format,
        enabled=enabled,
    )


PRODUCT_CATALOG: dict[str, tuple[PrintProduct, ...]] = {
    "3:2": tuple(
        _product("3:2", width, height)
        for width, height in (
            (12, 8),
            (18, 12),
            (24, 16),
            (30, 20),
            (36, 24),
            (48, 32),
            (60, 40),
        )
    ),
    "4:3": tuple(
        _product("4:3", width, height)
        for width, height in (
            (12, 9),
            (16, 12),
            (20, 15),
            (24, 18),
            (32, 24),
            (40, 30),
            (48, 36),
        )
    ),
    "5:4": tuple(
        _product("5:4", width, height)
        for width, height in (
            (10, 8),
            (15, 12),
            (20, 16),
            (25, 20),
            (30, 24),
            (40, 32),
            (50, 40),
        )
    ),
    "14:11": tuple(
        _product("14:11", width, height)
        for width, height in (
            (14, 11),
            (28, 22),
            (42, 33),
            (56, 44),
        )
    ),
    "1:1": tuple(
        _product("1:1", width, height)
        for width, height in (
            (12, 12),
            (18, 18),
            (24, 24),
            (30, 30),
            (36, 36),
            (48, 48),
        )
    ),
}


def products_for_ratio(
    ratio: str,
    orientation: str,
    *,
    include_disabled: bool = False,
) -> tuple[PrintProduct, ...]:
    """Return configured products in the requested artwork orientation."""
    horizontal_ratio = canonical_ratio(ratio)
    products = PRODUCT_CATALOG.get(horizontal_ratio, ())

    if not include_disabled:
        products = tuple(product for product in products if product.enabled)

    if orientation != "vertical" or horizontal_ratio == "1:1":
        return products

    ratio_left, ratio_right = horizontal_ratio.split(":", 1)
    vertical_ratio = f"{ratio_right}:{ratio_left}"

    return tuple(
        replace(
            product,
            key=(
                f"{vertical_ratio.replace(':', 'x')}-"
                f"{product.height_inches}x{product.width_inches}"
            ),
            ratio=vertical_ratio,
            width_inches=product.height_inches,
            height_inches=product.width_inches,
        )
        for product in products
    )


def product_sizes_for_ratio(
    ratio: str,
    orientation: str,
) -> tuple[tuple[int, int], ...]:
    """Compatibility API returning only physical width and height."""
    return tuple(
        (product.width_inches, product.height_inches)
        for product in products_for_ratio(ratio, orientation)
    )
