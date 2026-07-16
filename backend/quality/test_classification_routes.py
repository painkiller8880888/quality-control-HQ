from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (
    ClassMaster,
    History,
    InspectionFile,
    InspectionTarget,
    Machine,
    MachineAssignment,
    Master,
    MasterClass,
    SpecialInspectionClass9,
    User,
)
from .services import (
    ClassificationError,
    resolve_class_for_route,
    resolve_ocr_class,
    resolve_process_class,
    resolve_product_inspection_class,
    resolve_inspection_file,
    resolve_unambiguous_inspection_file,
    issue_inspection_sheets,
    upsert_targets,
)


class ClassificationRouteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            login_name="route-user", display_name="Route User", password_hash="!", role=User.Role.ADMIN
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        for class_no in range(1, 10):
            ClassMaster.objects.get_or_create(class_no=class_no, defaults={"class_name": f"Class {class_no}"})

    def machine(self, number, class_no, master):
        machine = Machine.objects.create(
            machine_no=number,
            machine_name=number,
            machine_class=class_no,
            shape_type=Machine.ShapeType.RECTANGLE,
            map_x=0,
            map_y=0,
            width=1,
            height=1,
        )
        MachineAssignment.objects.create(machine=machine, code=master, assignment_class=class_no)
        return machine

    def test_process_class_1_2_conflict_is_not_silently_prioritized(self):
        master = Master.objects.create(code="CON0001", name="Conflict")
        self.machine("M1", 1, master)
        self.machine("M2", 2, master)

        with self.assertRaises(ClassificationError) as raised:
            resolve_process_class(master)
        self.assertEqual(raised.exception.error_code, "CLASS_1_2_CONFLICT")
        self.assertEqual(raised.exception.details["detected_classes"], [1, 2])
        self.assertEqual(raised.exception.details["machine_numbers"], ["M1", "M2"])

    def add_master_class(self, master, class_no):
        MasterClass.objects.create(
            master=master,
            class_master=ClassMaster.objects.get(class_no=class_no),
        )

    def test_ocr_uses_explicit_class8_only_after_process_not_found(self):
        class8 = Master.objects.create(code="OCR0008", name="Packing")
        self.add_master_class(class8, 8)
        self.assertEqual(resolve_ocr_class(class8), 8)

        process = Master.objects.create(code="OCR0001", name="Process")
        self.machine("MOCR1", 1, process)
        self.add_master_class(process, 8)
        self.assertEqual(resolve_ocr_class(process), 1)

    def test_ocr_does_not_hide_conflict_or_fall_back_to_other_classes(self):
        conflict = Master.objects.create(code="OCRCON1", name="Conflict")
        self.machine("MOCRC1", 1, conflict)
        self.machine("MOCRC2", 2, conflict)
        self.add_master_class(conflict, 8)
        with self.assertRaises(ClassificationError) as raised:
            resolve_ocr_class(conflict)
        self.assertEqual(raised.exception.error_code, "CLASS_1_2_CONFLICT")

        product_only = Master.objects.create(code="OCR0006", name="Product only")
        self.add_master_class(product_only, 6)
        with self.assertRaises(ClassificationError) as missing:
            resolve_ocr_class(product_only)
        self.assertEqual(missing.exception.error_code, "PROCESS_CLASS_NOT_FOUND")

    def test_factory_map_does_not_use_explicit_class8(self):
        master = Master.objects.create(code="MAP0008", name="Packing")
        self.add_master_class(master, 8)
        with self.assertRaises(ClassificationError) as raised:
            resolve_class_for_route(master, InspectionTarget.RegistrationRoute.FACTORY_MAP)
        self.assertEqual(raised.exception.error_code, "PROCESS_CLASS_NOT_FOUND")

    def test_ocr_batch_accepts_process_and_explicit_class8(self):
        process = Master.objects.create(code="OCRBAT1", name="Process")
        self.machine("MOCRB1", 2, process)
        class8 = Master.objects.create(code="OCRBAT8", name="Packing")
        self.add_master_class(class8, 8)

        upsert_targets(date(2026, 7, 16), [process.code, class8.code], "ocr", user=self.user)

        self.assertEqual(
            set(InspectionTarget.objects.values_list("registration_route", "class_override")),
            {("ocr", 2), ("ocr", 8)},
        )
        class8_target = InspectionTarget.objects.get(master=class8)
        self.assertTrue(class8_target.source_ocr)

    def test_ocr_batch_accepts_fourteen_explicit_class8_codes(self):
        codes = [
            "CDS1101", "CAI0041", "CLS0231", "CLS0100", "CHS0082", "CBR0100", "COS0369",
            "CNS0746", "CDS1011", "COS0538", "COS0598", "COS0269", "CCS0155", "COS0220",
        ]
        for code in codes:
            master = Master.objects.create(code=code, name=f"Class 8 {code}")
            self.add_master_class(master, 8)

        upsert_targets(date(2026, 7, 20), codes, "ocr", user=self.user)

        targets = InspectionTarget.objects.filter(session__target_date=date(2026, 7, 20))
        self.assertEqual(targets.count(), 14)
        self.assertFalse(targets.exclude(registration_route="ocr", class_override=8, source_ocr=True).exists())

    def test_ocr_unclassified_code_rolls_back_entire_batch(self):
        valid = Master.objects.create(code="OCRRBK8", name="Class 8")
        self.add_master_class(valid, 8)
        invalid = Master.objects.create(code="OCRRBK0", name="Unclassified")

        with self.assertRaises(ClassificationError) as raised:
            upsert_targets(date(2026, 7, 21), [valid.code, invalid.code], "ocr", user=self.user)

        self.assertEqual(raised.exception.error_code, "PROCESS_CLASS_NOT_FOUND")
        self.assertFalse(InspectionTarget.objects.filter(session__target_date=date(2026, 7, 21)).exists())

    def test_product_class_6_7_conflict_and_missing_file_stop(self):
        master = Master.objects.create(code="CON0002", name="Conflict")
        with self.assertRaises(ClassificationError) as missing:
            resolve_product_inspection_class(master)
        self.assertEqual(missing.exception.error_code, "PRODUCT_INSPECTION_FILE_NOT_FOUND")

        InspectionFile.objects.create(master=master, file_name="one.xlsx", file_path=r"C:\製品検査\(1)\one.xlsx")
        InspectionFile.objects.create(master=master, file_name="two.xlsx", file_path=r"C:\製品検査\(2)\two.xlsx")
        with self.assertRaises(ClassificationError) as conflict:
            resolve_product_inspection_class(master)
        self.assertEqual(conflict.exception.error_code, "CLASS_6_7_CONFLICT")
        self.assertEqual(conflict.exception.details["detected_classes"], [6, 7])
        self.assertEqual(conflict.exception.details["candidate_file_names"], ["one.xlsx", "two.xlsx"])
        self.assertNotIn("C:\\製品検査", str(conflict.exception.details))

    def test_same_code_process_and_product_routes_create_separate_targets_and_histories(self):
        master = Master.objects.create(code="MIX0001", name="Mixed work")
        self.machine("M3", 2, master)
        InspectionFile.objects.create(master=master, file_name="two.xlsx", file_path=r"C:\製品検査\(2)\two.xlsx")

        upsert_targets(date(2026, 7, 16), [master.code], "ocr", user=self.user)
        upsert_targets(date(2026, 7, 16), [master.code], "excel", user=self.user)
        targets = list(InspectionTarget.objects.filter(master=master).order_by("class_override"))
        self.assertEqual([target.class_override for target in targets], [2, 7])
        self.assertEqual([target.registration_route for target in targets], ["ocr", "excel"])

        for target in targets:
            response = self.client.patch(
                "/api/history/",
                {"date": "2026-07-16", "target_id": target.id, "time": "A", "checked": True},
                format="json",
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(set(History.objects.values_list("class_override", flat=True)), {2, 7})
        payload = self.client.get("/api/inspection-targets/?date=2026-07-16").json()
        by_class = {row["category"]: row["checks"]["A"] for row in payload}
        self.assertEqual(by_class, {2: True, 7: True})

    def test_same_code_class_1_and_6_are_separate(self):
        master = Master.objects.create(code="MIX0002", name="Internal and outsourced")
        self.machine("M6", 1, master)
        InspectionFile.objects.create(master=master, file_name="one.xlsx", file_path=r"C:\製品検査\(1)\one.xlsx")

        upsert_targets(date(2026, 7, 16), [master.code], "factory_map", user=self.user)
        upsert_targets(date(2026, 7, 16), [master.code], "manual_code", user=self.user)

        targets = list(InspectionTarget.objects.filter(master=master).order_by("class_override"))
        self.assertEqual([target.class_override for target in targets], [1, 6])

    def test_normal_and_class9_targets_histories_and_checks_are_separate(self):
        master = Master.objects.create(code="MIX0009", name="Normal and special")
        self.machine("M9", 1, master)
        SpecialInspectionClass9.objects.create(master=master, inspection_sheet_path=r"C:\special\nine.xlsx")
        upsert_targets(date(2026, 7, 16), [master.code], "ocr", user=self.user)
        upsert_targets(date(2026, 7, 16), [master.code], "special", user=self.user)
        targets = list(InspectionTarget.objects.filter(master=master).order_by("class_override"))
        self.assertEqual([target.class_override for target in targets], [1, 9])

        response = self.client.patch(
            "/api/history/",
            {"date": "2026-07-16", "target_id": targets[1].id, "time": "B", "checked": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(History.objects.values_list("class_override", "time_slot")), [(9, "B")])
        payload = self.client.get("/api/inspection-targets/?date=2026-07-16").json()
        checks = {row["category"]: row["checks"]["B"] for row in payload}
        self.assertEqual(checks, {1: False, 9: True})

    def test_product_conflict_rolls_back_entire_batch(self):
        valid = Master.objects.create(code="BAT0001", name="Valid")
        conflict = Master.objects.create(code="BAT0002", name="Conflict")
        InspectionFile.objects.create(master=valid, file_name="one.xlsx", file_path=r"C:\製品検査\(1)\one.xlsx")
        InspectionFile.objects.create(master=conflict, file_name="one.xlsx", file_path=r"C:\製品検査\(1)\one.xlsx")
        InspectionFile.objects.create(master=conflict, file_name="two.xlsx", file_path=r"C:\製品検査\(2)\two.xlsx")

        with self.assertRaises(ClassificationError) as raised:
            upsert_targets(date(2026, 7, 17), [valid.code, conflict.code], "excel", user=self.user)
        self.assertEqual(raised.exception.error_code, "CLASS_6_7_CONFLICT")
        self.assertFalse(InspectionTarget.objects.filter(session__target_date=date(2026, 7, 17)).exists())

    def test_class9_print_failures_remain_unissued_and_return_warnings(self):
        missing_master = Master.objects.create(code="PRN0001", name="Missing")
        failed_master = Master.objects.create(code="PRN0002", name="Failed")
        success_master = Master.objects.create(code="PRN0004", name="Success")
        SpecialInspectionClass9.objects.create(master=missing_master, inspection_sheet_path="")
        SpecialInspectionClass9.objects.create(master=failed_master, inspection_sheet_path=r"C:\secret\special.xlsx")
        SpecialInspectionClass9.objects.create(master=success_master, inspection_sheet_path=r"C:\special\success.xlsx")
        missing = History.objects.create(date=date(2026, 7, 18), master=missing_master, time_slot="A", class_override=9, created_by=self.user)
        failed = History.objects.create(date=date(2026, 7, 18), master=failed_master, time_slot="B", class_override=9, created_by=self.user)
        success = History.objects.create(date=date(2026, 7, 18), master=success_master, time_slot="C", class_override=9, created_by=self.user)

        def print_class9(file_path):
            if "secret" in file_path:
                raise OSError("printer unavailable")

        with TemporaryDirectory() as tmp:
            template = Path(tmp) / "template.xlsm"
            template.touch()
            with override_settings(DAILY_REPORT_TEMPLATE=template), patch(
                "quality.services._print_file_direct", side_effect=print_class9
            ):
                result = issue_inspection_sheets(date(2026, 7, 18), user=self.user)

        missing.refresh_from_db()
        failed.refresh_from_db()
        success.refresh_from_db()
        self.assertFalse(missing.is_sheet_issued)
        self.assertFalse(failed.is_sheet_issued)
        self.assertTrue(success.is_sheet_issued)
        self.assertEqual(result["class9_printed"], 1)
        self.assertEqual(result["class9_failed"], 2)
        self.assertEqual({warning["error_code"] for warning in result["warnings"]}, {"FILE_NOT_FOUND", "PRINT_FAILED"})
        self.assertNotIn("C:\\secret", str(result))

    def test_target_print_accepts_same_class_candidates_and_hides_path(self):
        master = Master.objects.create(code="PRN0003", name="Ambiguous")
        InspectionFile.objects.create(master=master, file_name="a.xlsx", file_path=r"C:\製品検査\(1)\a.xlsx")
        InspectionFile.objects.create(master=master, file_name="b.xlsx", file_path=r"C:\製品検査\(1)\b.xlsx")
        session, _, _ = upsert_targets(date(2026, 7, 19), [master.code], "manual_code", user=self.user)
        target = InspectionTarget.objects.get(session=session, master=master)
        response = self.client.post(f"/api/inspection-targets/{target.id}/print-file/", format="json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error_code"], "FILE_NOT_FOUND")
        self.assertNotIn("AMBIGUOUS_INSPECTION_FILE", str(response.json()))

        InspectionFile.objects.filter(master=master).delete()
        secret_path = r"C:\internal\secret\missing.xlsx"
        InspectionFile.objects.create(master=master, file_name="missing.xlsx", file_path=secret_path)
        response = self.client.post(f"/api/inspection-targets/{target.id}/print-file/", format="json")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(secret_path, str(response.json()))

    def test_process_resolver_covers_3_4_5_without_using_product_files(self):
        class3 = Master.objects.create(code="PRO0003", name="Setter")
        self.machine("M30", 3, class3)
        InspectionFile.objects.create(master=class3, file_name="one.xlsx", file_path=r"C:\製品検査\(1)\one.xlsx")
        class4 = Master.objects.create(code="PRO0004", name="Press", node_type_1="プレス")
        class5 = Master.objects.create(code="PRO0005", name="Process", node_type_1="加工", department="製造管理部")
        self.assertEqual(resolve_process_class(class3), 3)
        self.assertEqual(resolve_process_class(class4), 4)
        self.assertEqual(resolve_process_class(class5), 5)

    def test_file_resolution_is_bound_to_confirmed_class(self):
        master = Master.objects.create(code="FIL0001", name="Files")
        product1 = InspectionFile.objects.create(master=master, file_name="one.xlsx", file_path=r"C:\製品検査\(1)\one.xlsx")
        product2 = InspectionFile.objects.create(master=master, file_name="two.xlsx", file_path=r"C:\製品検査\(2)\two.xlsx")
        special = SpecialInspectionClass9.objects.create(master=master, inspection_sheet_path=r"C:\special\nine.xlsx")
        self.assertEqual(resolve_inspection_file(master, 6), product1)
        self.assertEqual(resolve_inspection_file(master, 7), product2)
        self.assertEqual(resolve_inspection_file(master, 9)["file_path"], special.inspection_sheet_path)

    def test_duplicate_same_class_files_select_highest_priority(self):
        master = Master.objects.create(code="CCP0030", name="Duplicate files")
        low_priority = InspectionFile.objects.create(
            master=master,
            file_name="CCP0030-A.xlsx",
            file_path=r"C:\internal\自動機\工程内検査\CCP0030-A.xlsx",
            priority=10,
        )
        high_priority = InspectionFile.objects.create(
            master=master,
            file_name="CCP0030-B.xlsx",
            file_path=r"C:\secret\自動機\工程内検査\CCP0030-B.xlsx",
            priority=100,
        )

        self.assertEqual(resolve_inspection_file(master, 1), high_priority)
        self.assertNotEqual(resolve_inspection_file(master, 1), low_priority)

    def test_same_priority_selects_newest_created_file_and_prefers_known_date(self):
        master = Master.objects.create(code="CCP0031", name="Created date")
        unknown = InspectionFile.objects.create(
            master=master,
            file_name="unknown.xlsx",
            file_path=r"C:\自動機\工程内検査\unknown.xlsx",
            priority=10,
        )
        old = InspectionFile.objects.create(
            master=master,
            file_name="old.xlsx",
            file_path=r"C:\自動機\工程内検査\old.xlsx",
            priority=10,
            file_created=timezone.now() - timedelta(days=1),
        )
        newest = InspectionFile.objects.create(
            master=master,
            file_name="new.xlsx",
            file_path=r"C:\自動機\工程内検査\new.xlsx",
            priority=10,
            file_created=timezone.now(),
        )

        self.assertEqual(resolve_inspection_file(master, 1), newest)
        newest.delete()
        self.assertEqual(resolve_inspection_file(master, 1), old)
        self.assertNotEqual(resolve_inspection_file(master, 1), unknown)

    def test_selection_uses_normalized_path_then_id_as_deterministic_tiebreaker(self):
        master = Master.objects.create(code="CCP0032", name="Tie break")
        created = datetime(2026, 7, 1, tzinfo=timezone.get_current_timezone())
        later_path = InspectionFile.objects.create(
            master=master,
            file_name="b.xlsx",
            file_path=r"C:\自動機\工程内検査\b.xlsx",
            priority=0,
            file_created=created,
        )
        earlier_path = InspectionFile.objects.create(
            master=master,
            file_name="a.xlsx",
            file_path=r"C:\自動機\工程内検査\a.xlsx",
            priority=0,
            file_created=created,
        )

        self.assertEqual(resolve_inspection_file(master, 1), earlier_path)
        self.assertNotEqual(resolve_inspection_file(master, 1), later_path)

    def test_unclassified_same_code_candidates_use_common_selection_rule(self):
        master = Master.objects.create(code="CCP0033", name="Unclassified")
        first = InspectionFile.objects.create(
            master=master,
            file_name="same.xlsx",
            file_path=r"C:\other\same.xlsx",
            priority=4,
        )
        InspectionFile.objects.create(
            master=master,
            file_name="same-copy.xlsx",
            file_path=r"C:\other\same-copy.xlsx",
            priority=1,
        )

        self.assertEqual(resolve_unambiguous_inspection_file(master), first)

    def test_machine_class_change_resynchronizes_master_class(self):
        master = Master.objects.create(code="MAC0001", name="Machine")
        machine = self.machine("M31", 1, master)
        response = self.client.put(
            "/api/machine-master/",
            {
                "id": machine.id,
                "machine_no": machine.machine_no,
                "machine_name": machine.machine_name,
                "machine_class": 2,
                "shape_type": "rectangle",
                "map_x": 0,
                "map_y": 0,
                "width": 1,
                "height": 1,
                "is_active": True,
                "assignments": [{"code": master.code}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(master.master_classes.values_list("class_master__class_no", flat=True)), {2})

    def test_endpoints_determine_route_and_reject_client_class_override(self):
        process_master = Master.objects.create(code="API0001", name="Process")
        machine = self.machine("M4", 1, process_master)
        product_master = Master.objects.create(code="API0002", name="Product")
        InspectionFile.objects.create(
            master=product_master, file_name="one.xlsx", file_path=r"C:\製品検査\(1)\one.xlsx"
        )
        special_master = Master.objects.create(code="API0003", name="Special")
        SpecialInspectionClass9.objects.create(master=special_master, inspection_sheet_path=r"C:\special.xlsx")

        rejected = self.client.post(
            "/api/inspection-targets/manual/",
            {"date": "2026-07-16", "codes": [product_master.code], "class_override": 9},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)
        unknown_special = self.client.post(
            "/api/inspection-targets/special/",
            {"date": "2026-07-16", "codes": ["UNKNOWN1"]},
            format="json",
        )
        self.assertEqual(unknown_special.status_code, 400)
        self.assertEqual(unknown_special.json()["error_code"], "CLASS_9_SETTING_NOT_FOUND")

        factory = self.client.post(
            "/api/inspection-targets/factory-map/",
            {"date": "2026-07-16", "machine_id": machine.id, "code": process_master.code},
            format="json",
        )
        manual = self.client.post(
            "/api/inspection-targets/manual/",
            {"date": "2026-07-16", "codes": [product_master.code]},
            format="json",
        )
        special = self.client.post(
            "/api/inspection-targets/special/",
            {"date": "2026-07-16", "codes": [special_master.code]},
            format="json",
        )
        self.assertEqual((factory.status_code, manual.status_code, special.status_code), (200, 200, 200))
        self.assertEqual(
            set(InspectionTarget.objects.values_list("registration_route", "class_override")),
            {("factory_map", 1), ("manual_code", 6), ("special", 9)},
        )
