"""Pre-merge regressions for unused lanes and credential admission order."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from jev_ios.cli import parser
from jev_ios.matrix import run_matrix
from jev_ios.parallel_cli import handle
from jev_ios.suite import Suite
from test_parallel import BUNDLE, CATALOG, Lab, case, worker


class ReviewRegressions(unittest.TestCase):
    def test_unused_offline_shard_lane_is_never_opened(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lab = Lab()
            attempted = []
            def session(spec, bundle):
                attempted.append(spec.name)
                if spec.name != "phone-1":
                    raise RuntimeError("Unused offline device should never be contacted")
                return lab.device(spec, bundle)
            cases = tuple(case(f"case-{i}") for i in range(3))
            result = run_matrix(Suite("Sharded", BUNDLE, cases, "per_device"), [(c, "all") for c in cases],
                [worker(), worker(2), worker(3)], output_dir=root / "run", catalog=CATALOG,
                parallel=1, requests_per_second=1000, session_factory=session, model_factory=lab.model,
                lease_directory=root / "locks")
            self.assertEqual(attempted, ["phone-1"])
            self.assertEqual(result["lane_errors"], [])
            self.assertEqual(result["summary"]["status"], "verified")

    def test_one_case_opens_only_one_concurrent_shard_session(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = Lab()
            c = case()
            result = run_matrix(Suite("One case", BUNDLE, (c,), "per_device"), [(c, "all")],
                [worker(i + 1) for i in range(4)], output_dir=Path(directory) / "run", catalog=CATALOG,
                parallel=4, requests_per_second=1000, session_factory=lab.device, model_factory=lab.model,
                lease_directory=Path(directory) / "locks")
            self.assertEqual(lab.opened, 1)
            self.assertEqual(lab.closed, 1)
            self.assertEqual(result["summary"]["status"], "verified")

    def test_required_offline_matrix_lane_still_prevents_success(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = Lab()
            def session(spec, bundle):
                if spec.name == "phone-2":
                    raise RuntimeError("Required device unavailable")
                return lab.device(spec, bundle)
            c = case()
            result = run_matrix(Suite("Matrix", BUNDLE, (c,), "per_device"), [(c, "all")],
                [worker(), worker(2)], output_dir=Path(directory) / "run", catalog=CATALOG,
                mode="matrix", parallel=1, requests_per_second=1000,
                session_factory=session, model_factory=lab.model, lease_directory=Path(directory) / "locks")
            self.assertEqual(result["summary"]["status"], "not_verified")
            self.assertEqual(result["summary"]["counts"]["skipped"], 1)

    def execution_args(self, output, *extra):
        repo = Path(__file__).resolve().parents[1]
        return parser().parse_args(["matrix", "--suite", str(repo / "examples/parallel/daybreak-suite.json"),
            "--udid", worker().udid, "--vercel-project", "fixture-project", "--output-dir", str(output), *extra])

    def test_over_budget_matrix_never_mints_a_token(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            token = Mock(side_effect=AssertionError("Credential requested before admission"))
            with self.assertRaisesRegex(ValueError, "reservation"):
                handle(self.execution_args(output, "--budget-usd", "0.00000001"), lambda _: None,
                       lambda: CATALOG, token)
            token.assert_not_called()
            self.assertFalse(output.exists())

    def test_missing_catalog_model_never_mints_a_token(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            token = Mock()
            with self.assertRaisesRegex(ValueError, "pricing reservation"):
                handle(self.execution_args(output), lambda _: None, lambda: [], token)
            token.assert_not_called()
            self.assertFalse(output.exists())

    def test_empty_execution_never_contacts_catalog_or_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog, token = Mock(), Mock()
            with self.assertRaisesRegex(ValueError, "No scenarios"):
                handle(self.execution_args(Path(directory) / "run", "--tag", "nonexistent"),
                       lambda _: None, catalog, token)
            catalog.assert_not_called()
            token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
