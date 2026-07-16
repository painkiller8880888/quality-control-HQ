from datetime import date

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RegistrationRouteMigrationTests(TransactionTestCase):
    migrate_from = [("quality", "0023_inspectionsession_note")]
    migrate_to = [("quality", "0025_allow_explicit_class8_for_ocr")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        User = old_apps.get_model("quality", "User")
        Master = old_apps.get_model("quality", "Master")
        InspectionSession = old_apps.get_model("quality", "InspectionSession")
        InspectionTarget = old_apps.get_model("quality", "InspectionTarget")

        user = User.objects.create(login_name="migration-user", display_name="Migration User", password_hash="!", role="worker")
        master = Master.objects.create(code="MIG0001", name="Migration")
        session = InspectionSession.objects.create(target_date=date(2026, 7, 20), owner_user=user, created_by=user, updated_by=user)
        self.class9_id = InspectionTarget.objects.create(
            session=session,
            master=master,
            raw_code=master.code,
            normalized_code=master.code,
            class_override=9,
            created_by=user,
            updated_by=user,
        ).id
        self.legacy_id = InspectionTarget.objects.create(
            session=session,
            master=master,
            raw_code="MIG0002",
            normalized_code="MIG0002",
            class_override=None,
            created_by=user,
            updated_by=user,
        ).id
        self.pre_migration_count = InspectionTarget.objects.count()

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_backfill_constraints_and_legacy_null_compatibility(self):
        InspectionTarget = self.apps.get_model("quality", "InspectionTarget")
        Master = self.apps.get_model("quality", "Master")

        class9 = InspectionTarget.objects.get(id=self.class9_id)
        legacy = InspectionTarget.objects.get(id=self.legacy_id)
        self.assertEqual(InspectionTarget.objects.count(), self.pre_migration_count)
        self.assertEqual((class9.registration_route, class9.class_override), ("special", 9))
        self.assertEqual((legacy.registration_route, legacy.class_override), ("legacy", None))

        invalid_master = Master.objects.create(code="MIG0003", name="Invalid")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InspectionTarget.objects.create(
                    session_id=class9.session_id,
                    master=invalid_master,
                    raw_code=invalid_master.code,
                    normalized_code=invalid_master.code,
                    registration_route="manual_code",
                    class_override=1,
                )

        compatible = InspectionTarget.objects.create(
            session_id=class9.session_id,
            master=invalid_master,
            raw_code="MIG0004",
            normalized_code="MIG0004",
            registration_route="legacy",
            class_override=None,
        )
        self.assertIsNone(compatible.class_override)

        ocr_class8 = InspectionTarget.objects.create(
            session_id=class9.session_id,
            master=invalid_master,
            raw_code="MIG0008",
            normalized_code="MIG0008",
            registration_route="ocr",
            class_override=8,
        )
        self.assertEqual(ocr_class8.class_override, 8)

        for route in ("factory_map", "manual_code", "special"):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    InspectionTarget.objects.create(
                        session_id=class9.session_id,
                        master=invalid_master,
                        raw_code=f"MIG8{route}",
                        normalized_code=f"MIG8{route}",
                        registration_route=route,
                        class_override=8,
                    )
