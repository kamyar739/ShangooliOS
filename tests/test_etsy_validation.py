import unittest

from web.etsy_validation import validate_etsy_listing


class EtsyValidationTests(unittest.TestCase):
    def _listing(self, **overrides):
        listing = {
            "title": "Unbound Wall Art",
            "description": "A joyful abstract artwork.",
            "tags": "abstract art, joyful art",
            "price_cents": 4200,
        }
        listing.update(overrides)
        return listing

    def _result(self, listing, key):
        return next(item for item in validate_etsy_listing(listing) if item["key"] == key)

    def test_valid_listing_passes_content_checks(self):
        results = validate_etsy_listing(self._listing())
        self.assertTrue(all(item["passed"] for item in results))

    def test_title_cannot_exceed_140_characters(self):
        result = self._result(self._listing(title="x" * 141), "title")
        self.assertFalse(result["passed"])
        self.assertIn("141 characters", result["detail"])

    def test_listing_cannot_have_more_than_13_tags(self):
        tags = ", ".join(f"tag {number}" for number in range(1, 15))
        result = self._result(self._listing(tags=tags), "tags")
        self.assertFalse(result["passed"])
        self.assertIn("14 tags", result["detail"])

    def test_each_tag_is_limited_to_20_characters(self):
        result = self._result(
            self._listing(tags="abstract art, this tag is much too long"),
            "tags",
        )
        self.assertFalse(result["passed"])
        self.assertIn("Shorten tags over 20 characters", result["detail"])

    def test_description_and_positive_price_are_required(self):
        results = validate_etsy_listing(self._listing(description="", price_cents=0))
        failures = {item["key"] for item in results if not item["passed"]}
        self.assertEqual(failures, {"description", "price"})


if __name__ == "__main__":
    unittest.main()
