import unittest

from web.production import build_workflow_status


def production_state(
    *,
    approved=False,
    ratios_reviewed=False,
    mockups_ready=False,
    listing_ready=False,
):
    return {
        "original_approved": int(approved),
        "ratio_exports_ready": int(ratios_reviewed),
        "mockups_ready": int(mockups_ready),
        "listing_content_ready": int(listing_ready),
    }


class WorkflowStatusTests(unittest.TestCase):
    def test_new_artwork_needs_source_upload(self):
        workflow = build_workflow_status(
            {"status": "creating"},
            production_state(),
            source_ready=False,
            master_ready=False,
            required_ratios=[],
            missing_ratios=[],
        )

        self.assertEqual(workflow.current_step["key"], "source")
        self.assertEqual(workflow.current_stage, "Source Artwork")
        self.assertEqual(
            workflow.next_action["title"],
            "Upload the source artwork",
        )
        self.assertEqual(workflow.completed_steps, 1)
        self.assertEqual(workflow.progress_percent, 11)

    def test_uploaded_source_needs_approval(self):
        workflow = build_workflow_status(
            {"status": "review"},
            production_state(),
            source_ready=True,
            master_ready=False,
            required_ratios=[],
            missing_ratios=[],
        )

        self.assertEqual(workflow.current_step["key"], "approved")
        self.assertEqual(
            workflow.next_action["title"],
            "Approve the source artwork",
        )
        self.assertEqual(workflow.completed_steps, 2)

    def test_missing_ratios_are_named_in_next_action(self):
        workflow = build_workflow_status(
            {"status": "production"},
            production_state(approved=True),
            source_ready=True,
            master_ready=True,
            required_ratios=["3:2", "4:3", "5:4", "14:11"],
            missing_ratios=["5:4", "14:11"],
        )

        self.assertEqual(workflow.current_step["key"], "ratios")
        self.assertEqual(workflow.current_stage, "Print Production")
        self.assertEqual(
            workflow.next_action["title"],
            "Generate 5:4, 14:11",
        )

    def test_completed_files_move_workflow_to_mockups(self):
        workflow = build_workflow_status(
            {"status": "production"},
            production_state(
                approved=True,
                ratios_reviewed=True,
            ),
            source_ready=True,
            master_ready=True,
            required_ratios=["3:2", "4:3"],
            missing_ratios=[],
        )

        self.assertEqual(workflow.current_step["key"], "mockups")
        self.assertEqual(workflow.current_stage, "Marketing Assets")
        self.assertEqual(
            workflow.next_action["title"],
            "Create and approve the listing images",
        )

    def test_listing_ready_stops_at_publish(self):
        workflow = build_workflow_status(
            {"status": "approved"},
            production_state(
                approved=True,
                ratios_reviewed=True,
                mockups_ready=True,
                listing_ready=True,
            ),
            source_ready=True,
            master_ready=True,
            required_ratios=["3:2", "4:3"],
            missing_ratios=[],
        )

        self.assertEqual(workflow.current_step["key"], "published")
        self.assertEqual(workflow.current_stage, "Publishing")
        self.assertEqual(workflow.readiness, "ready")
        self.assertEqual(workflow.readiness_label, "Ready for listing")

    def test_listed_artwork_is_complete(self):
        workflow = build_workflow_status(
            {"status": "listed"},
            production_state(
                approved=True,
                ratios_reviewed=True,
                mockups_ready=True,
                listing_ready=True,
            ),
            source_ready=True,
            master_ready=True,
            required_ratios=["3:2", "4:3"],
            missing_ratios=[],
        )

        self.assertIsNone(workflow.current_step)
        self.assertEqual(workflow.current_stage, "Complete")
        self.assertEqual(workflow.progress_percent, 100)
        self.assertEqual(
            workflow.next_action["title"],
            "Workflow complete",
        )


if __name__ == "__main__":
    unittest.main()
