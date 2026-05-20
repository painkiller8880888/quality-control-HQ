from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from openpyxl import Workbook, load_workbook
from rest_framework.test import APIClient

from .models import History, Job, Master


class PhaseOneApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        Master.objects.create(code="C1234", name="ホルダーAssy", category=1)
        Master.objects.create(code="C5678", name="検査品", category=6)

    def test_manual_targets_preserve_unknown_code_warning(self):
        response = self.client.post(
            "/api/inspection-targets/manual/",
            {"date": "2026-05-20", "codes": ["C1234", "X9999"]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        targets = self.client.get("/api/inspection-targets/?date=2026-05-20").json()

        self.assertEqual(len(targets), 2)
        unknown = next(target for target in targets if target["code"] == "X9999")
        self.assertEqual(unknown["warnings"][0]["error_code"], "UNKNOWN_CODE")

    def test_bulk_history_upsert_creates_and_removes_checked_slots(self):
        response = self.client.post(
            "/api/history/bulk-upsert/",
            {
                "date": "2026-05-20",
                "items": [
                    {
                        "code": "C1234",
                        "checks": {"A": True, "B": False, "C": True, "D": False},
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(History.objects.values_list("time_slot", flat=True)), {"A", "C"})

        response = self.client.patch(
            "/api/history/",
            {"date": "2026-05-20", "code": "C1234", "time": "C", "checked": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(History.objects.values_list("time_slot", flat=True)), {"A"})

    def test_daily_report_generation_writes_expected_cells(self):
        with TemporaryDirectory() as temp_dir:
            template_path = Path(temp_dir) / "daily.xlsm"
            output_dir = Path(temp_dir) / "reports"

            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "日報"
            workbook.save(template_path)

            History.objects.create(
                date="2026-05-20",
                master=Master.objects.get(code="C1234"),
                time_slot="A",
            )
            History.objects.create(
                date="2026-05-20",
                master=Master.objects.get(code="C5678"),
                time_slot="B",
            )

            with override_settings(
                DAILY_REPORT_TEMPLATE=template_path,
                DAILY_REPORT_OUTPUT_DIR=output_dir,
            ):
                response = self.client.post(
                    "/api/daily-report/generate/",
                    {"date": "2026-05-20"},
                    format="json",
                )

            self.assertEqual(response.status_code, 202)
            job = Job.objects.get(job_id=response.json()["job_id"])
            self.assertEqual(job.status, Job.Status.SUCCEEDED)

            report = load_workbook(output_dir / "2026-05-20.xlsm")
            sheet = report["日報"]
            self.assertEqual(sheet["C26"].value, "ホルダーAssy")
            self.assertEqual(sheet["F18"].value, "検査品")
