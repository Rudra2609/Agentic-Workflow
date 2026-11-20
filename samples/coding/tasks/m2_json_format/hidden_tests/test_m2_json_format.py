import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import report

S = {"score": {"min": 1.0, "max": 3.0, "mean": 2.0, "median": 2.0}}


class T(unittest.TestCase):
    def test_render_json(self):
        self.assertEqual(json.loads(report.render_summary(S, "json")), S)

    def test_cli_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.csv"
            path.write_text("name,score\na,1\nb,3\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                report.main(["--input", str(path), "--format", "json"])
        self.assertEqual(json.loads(out.getvalue()), S)

    def test_md_unchanged(self):
        self.assertTrue(report.render_summary(S, "md").startswith("| column |"))
