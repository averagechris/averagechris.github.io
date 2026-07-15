import contextlib
import io
import json
import unittest
from unittest import mock

import site_measure


class SiteMeasureTests(unittest.TestCase):
    def setUp(self) -> None:
        site_measure._counts.clear()

    def test_disabled_measurement_is_silent(self) -> None:
        output = io.StringIO()
        with mock.patch.object(site_measure, "ENABLED", False), contextlib.redirect_stdout(output):
            with site_measure.stage("before_fingerprint"):
                site_measure.count("probe_count")
        self.assertEqual(output.getvalue(), "")

    def test_stage_emits_only_named_timing_and_counter_data(self) -> None:
        output = io.StringIO()
        with mock.patch.object(site_measure, "ENABLED", True), \
             mock.patch.object(site_measure.time, "monotonic", side_effect=[10.0, 10.1, 10.4, 10.5]), \
             contextlib.redirect_stdout(output):
            with site_measure.stage("before_fingerprint"):
                with site_measure.operation("probe_count", "probe_ms"):
                    pass
        record = json.loads(output.getvalue().removeprefix("SITE_MEASURE "))
        self.assertEqual(record["stage"], "before_fingerprint")
        self.assertEqual(record["duration_ms"], 500)
        self.assertEqual(record["counts"], {"probe_count": 1, "probe_ms": 300})


if __name__ == "__main__":
    unittest.main()
