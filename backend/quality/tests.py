from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
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

    def test_plan_import_merges_ocr_text_and_excel_codes(self):
        Master.objects.create(code="CDP0028", name="OCR対象", category=5)
        Master.objects.create(code="CAP0044", name="Excel対象", category=4)

        with TemporaryDirectory() as temp_dir:
            excel_path = Path(temp_dir) / "plan.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "雛形"
            worksheet["G5"] = "cap0044"
            worksheet["G6"] = "cdp0028"
            workbook.save(excel_path)

            with excel_path.open("rb") as handle:
                response = self.client.post(
                    "/api/plans/import/",
                    {
                        "target_date": "2026-05-21",
                        "scan_file": SimpleUploadedFile(
                            "ocr.txt",
                            b"cdp0028\ncdp0029\n",
                            content_type="text/plain",
                        ),
                        "excel_file": SimpleUploadedFile(
                            "plan.xlsx",
                            handle.read(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        ),
                    },
                    format="multipart",
                )

        self.assertEqual(response.status_code, 202)
        targets = self.client.get("/api/inspection-targets/?date=2026-05-21").json()
        codes = {target["code"]: target for target in targets}

        self.assertEqual(set(codes), {"CAP0044", "CDP0028", "CDP0029"})
        self.assertTrue(codes["CDP0028"]["source_flags"]["ocr"])
        self.assertTrue(codes["CDP0028"]["source_flags"]["excel"])
        self.assertEqual(codes["CDP0029"]["warnings"][0]["error_code"], "UNKNOWN_CODE")

    def test_master_update_imports_csv_and_resolves_name(self):
        csv_content = (
            '"h0","h1","h2","h3","h4","h5","h6","h7","h8","品目コード","品目略称","h11","h12","h13","h14","h15","オーダー先略称"\n'
            '"0","0","0","0","0","0","0","0","0","CAP0048","テスト品名","0","0","0","0","0","生産管理部"\n'
        ).encode("cp932")

        response = self.client.post(
            "/api/master/update/",
            {"master_file": SimpleUploadedFile("master.csv", csv_content, content_type="text/csv")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(Master.objects.filter(code="CAP0048", name="テスト品名").exists())

        self.client.post(
            "/api/inspection-targets/manual/",
            {"date": "2026-05-21", "codes": ["cap0048"]},
            format="json",
        )
        targets = self.client.get("/api/inspection-targets/?date=2026-05-21").json()
        self.assertEqual(targets[0]["name"], "テスト品名")

    @patch("quality.services.extract_codes_and_match_failures_from_pdf")
    def test_plan_import_from_pdf_tracks_match_failed_and_unknown_code(self, mocked_pdf_ocr):
        mocked_pdf_ocr.return_value = {
            "codes": ["CAP0048", "CAP0048", "ZZZ9999"],
            "match_failed_count": 2,
            "page_count": 3,
            "mode": "ocr",
        }
        Master.objects.create(code="CAP0048", name="OCR参照品名", category=1)

        response = self.client.post(
            "/api/plans/import/",
            {
                "target_date": "2026-05-22",
                "scan_file": SimpleUploadedFile("scan.pdf", b"%PDF-mock", content_type="application/pdf"),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 202)
        job = Job.objects.get(job_id=response.json()["job_id"])
        self.assertEqual(job.result["warning_summary"]["MATCH_FAILED"], 2)
        self.assertEqual(job.result["warning_summary"]["DUPLICATE_TARGET"], 1)
        self.assertEqual(job.result["warning_summary"]["UNKNOWN_CODE"], 1)

        targets = self.client.get("/api/inspection-targets/?date=2026-05-22").json()
        codes = {target["code"]: target for target in targets}
        self.assertEqual(codes["CAP0048"]["name"], "OCR参照品名")
        self.assertEqual(codes["ZZZ9999"]["warnings"][0]["error_code"], "UNKNOWN_CODE")
