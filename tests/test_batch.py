import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from batch import run_batch
from pipeline.batch_report import csv_safe, write_report
from pipeline.io import sha256


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.output = self.root / "output"
        for name in ("a.png", "b.png"):
            Image.new("RGB", (12, 10), (50, 100, 150)).save(self.inputs / name)
        self.calls = []

    def fake_runner(self, path, root, device, tile, overlap):
        self.calls.append(path.name)
        if path.suffix == ".txt":
            raise ValueError("file rusak")
        run = root / f"run-{len(self.calls)}"
        run.mkdir(parents=True)
        Image.new("RGB", (24, 20)).save(run / "comparison.png")
        (run / "processing.json").write_text(json.dumps({"status": "success",
            "source": {"normalized_size": [12, 10], "source_sha256": sha256(path), "warnings": []},
            "output_size": [24, 20], "inference_seconds": 0.1, "peak_cuda_allocated_bytes": None,
            "peak_cuda_reserved_bytes": None, "tile_used": tile, "overlap_used": overlap,
            "attempts": [{"status": "success"}], "artifacts": {"comparison.png": {"sha256": sha256(run / "comparison.png")}}}), encoding="utf-8")
        return run

    def test_failure_does_not_stop_batch_and_resume_skips_valid(self):
        (self.inputs / "0-bad.txt").write_text("corrupt")
        state = run_batch(self.inputs, self.output, device="cpu", runner=self.fake_runner)
        self.assertEqual([e["status"] for e in state["entries"]], ["failed", "success", "success"])
        self.assertEqual(state["status"], "complete_with_failures")
        self.calls.clear()
        run_batch(self.inputs, self.output, device="cpu", resume=True, runner=self.fake_runner)
        self.assertEqual(self.calls, ["0-bad.txt"])

    def test_changed_input_rejected_on_resume(self):
        run_batch(self.inputs, self.output, device="cpu", runner=self.fake_runner)
        Image.new("RGB", (12, 10), "red").save(self.inputs / "a.png")
        with self.assertRaisesRegex(ValueError, "hash input berubah"):
            run_batch(self.inputs, self.output, device="cpu", resume=True, runner=self.fake_runner)

    def test_corrupt_output_is_reprocessed(self):
        state = run_batch(self.inputs, self.output, device="cpu", runner=self.fake_runner)
        (self.output / state["entries"][0]["run"] / "comparison.png").write_bytes(b"corrupt")
        old_count = len(self.calls)
        run_batch(self.inputs, self.output, device="cpu", resume=True, runner=self.fake_runner)
        self.assertEqual(self.calls[old_count:], ["a.png"])

    def test_html_escape_and_csv_formula_guard(self):
        state = {"config": {"tile": 96, "overlap": 32}, "status": "complete_with_failures",
                 "entries": [{"id": "001", "name": "</script><script>alert(1)</script>", "status": "failed", "error": "<bad>"}]}
        self.output.mkdir()
        write_report(state, self.output)
        page = (self.output / "report.html").read_text(encoding="utf-8")
        self.assertNotIn("</script><script>alert(1)</script>", page)
        self.assertIn("&lt;bad&gt;", page)
        self.assertIn("FP32 · 96 / 32", page)
        self.assertIn('id="exporttext"', page)
        self.assertEqual(csv_safe("=1+1"), "'=1+1")


if __name__ == "__main__":
    unittest.main()
