"""Guard the sampling summary against compact Gecko rows and overlapping stacks."""

import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "profile_circuitverse", Path(__file__).resolve().parents[1] / "tools/profile-circuitverse.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProfileSummaryTests(unittest.TestCase):
    def test_compact_rows_inherit_category_and_inclusive_counts_overlap(self):
        script = "http://localhost/simulator-v0/simulator-v0.js"
        thread = {
            "name": "GeckoMain",
            "processType": "tab",
            "stringTable": [
                "root",
                f"play ({script}:1:1)",
                "add (circuitverse-queue-experiment.js:26:21)",
                "native",
            ],
            "frameTable": {
                "schema": {"location": 0, "category": 2},
                "data": [[0, None, 1], [1], [2], [3]],
            },
            "stackTable": {
                "schema": {"prefix": 0, "frame": 1},
                "data": [[None, 0], [0, 1], [1, 2], [2, 3]],
            },
            "samples": {"schema": {"stack": 0}, "data": [[3], [1], [None]]},
        }
        profile = {
            "meta": {"categories": [{"name": "Idle"}, {"name": "JavaScript"}]},
            "processes": [{"threads": [thread]}],
        }
        result = module.summarize(profile, 3)["threads"][0]
        self.assertEqual(result["samples"], 3)
        self.assertEqual(result["categories"], {"JavaScript": 2, "No stack": 1})
        self.assertEqual(result["samplesWithSimulatorJS"], 2)
        self.assertEqual(sum(x["samples"] for x in result["leafSimulatorJS"]), 2)
        self.assertEqual(sum(x["samples"] for x in result["inclusiveSimulatorJS"]), 3)
        self.assertEqual(
            result["leafSimulatorJS"][0]["function"], "add (circuitverse-queue-experiment.js:26:21)"
        )
        self.assertEqual(result["branches"][0]["function"], "Native play / propagation")
        self.assertEqual(result["branches"][0]["samples"], 2)
        self.assertEqual(sum(x["samples"] for x in result["branches"]), 3)

    def test_non_simulator_processes_are_excluded(self):
        profile = {"threads": [{"name": "GeckoMain", "stringTable": ["browser UI"]}]}
        self.assertEqual(module.summarize(profile, 10)["threads"], [])


if __name__ == "__main__":
    unittest.main()
