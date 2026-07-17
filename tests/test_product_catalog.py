from web.product_catalog import canonical_ratio, product_sizes_for_ratio


def test_vertical_ratio_uses_matching_rotated_catalog():
    assert canonical_ratio("2:3") == "3:2"
    sizes = product_sizes_for_ratio("2:3", "vertical")
    assert sizes[0] == (8, 12)
    assert sizes[-1] == (40, 60)


def test_square_catalog_stays_square():
    assert product_sizes_for_ratio("1:1", "square")[-1] == (48, 48)
