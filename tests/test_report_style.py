import datetime as dt
import importlib.util
import unittest
from pathlib import Path

from muse_tmr.reports.report_style import TOKENS_CSS, brand_line, readable_time


def _load_nightly_report_script():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_nightly_report.py"
    spec = importlib.util.spec_from_file_location("generate_nightly_report", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestReportStyle(unittest.TestCase):
    def test_readable_time_is_local_and_drops_the_microseconds(self):
        moment = dt.datetime(2026, 10, 17, 11, 22, 28, 281028, tzinfo=dt.timezone.utc)
        local = moment.astimezone()
        self.assertEqual(
            readable_time(moment.isoformat()),
            f"{local:%a} {local.day} {local:%b %Y, %H:%M}",
        )
        self.assertEqual(readable_time("2026-10-17T16:22:00"), "Sat 17 Oct 2026, 16:22")
        self.assertEqual(readable_time("not a time"), "not a time")
        self.assertEqual(readable_time(None), "")

    def test_brand_line_names_the_app_and_escapes_the_kind(self):
        line = brand_line("<b>REM</b> report")
        self.assertIn("Athena TMR · &lt;b&gt;REM&lt;/b&gt; report", line)
        self.assertIn("<svg", line)
        self.assertNotIn("http", TOKENS_CSS + line.replace("http://www.w3.org/2000/svg", ""))

    def test_the_rem_report_is_a_whole_document(self):
        script = _load_nightly_report_script()
        values = dict(
            page_title="REM report · 20261017_162227",
            brand=brand_line("REM report"),
            title="REM report · Sat 17 Oct 2026, 16:22",
            subtitle="20261017_162227 · amused",
            mean_p=0.41,
            duration_h=0.1,
            n_epochs=12,
            reconnects=0,
            callout="",
            data_json="[]",
            hourly_json="[]",
            t_max=1,
            start_min=0,
            cardio_section="",
        )
        page = script.TEMPLATE.format(**values)
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn('<meta charset="utf-8">', page)
        self.assertIn("<title>REM report · 20261017_162227</title>", page)
        self.assertIn("Athena TMR · REM report", page)
        self.assertTrue(page.rstrip().endswith("</html>"))


if __name__ == "__main__":
    unittest.main()
