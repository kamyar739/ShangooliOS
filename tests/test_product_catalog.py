from web.product_catalog import (
    PrintProduct,
    canonical_ratio,
    product_sizes_for_ratio,
    products_for_ratio,
)


def test_vertical_ratio_uses_matching_rotated_catalog():
    assert canonical_ratio("2:3") == "3:2"

    sizes = product_sizes_for_ratio("2:3", "vertical")

    assert sizes[0] == (8, 12)
    assert sizes[-1] == (40, 60)


def test_square_catalog_stays_square():
    assert product_sizes_for_ratio("1:1", "square")[-1] == (48, 48)


def test_products_include_generation_settings():
    products = products_for_ratio("3:2", "horizontal")
    product = products[0]

    assert isinstance(product, PrintProduct)
    assert product.ratio == "3:2"
    assert (product.width_inches, product.height_inches) == (12, 8)
    assert product.dpi == 300
    assert product.file_format == "PNG"
    assert product.enabled is True
    assert product.pixel_dimensions == (3600, 2400)


def test_vertical_products_swap_dimensions():
    product = products_for_ratio("2:3", "vertical")[0]

    assert product.ratio == "2:3"
    assert (product.width_inches, product.height_inches) == (8, 12)
    assert product.pixel_dimensions == (2400, 3600)


def test_product_keys_are_unique():
    products = products_for_ratio("3:2", "horizontal")
    keys = [product.key for product in products]

    assert len(keys) == len(set(keys))
    assert keys[0] == "3x2-12x8"
