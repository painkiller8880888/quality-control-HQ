import mimetypes
import os
import sys
import csv
from collections import Counter, defaultdict
from datetime import date, timedelta
from io import StringIO

from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db import models as db_models
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AppSetting,
    ClassMaster,
    History,
    InspectionFile,
    InspectionSession,
    InspectionTarget,
    Job,
    LayoutMaster,
    LayoutObject,
    LayoutObjectType,
    Machine,
    MachineAssignment,
    Master,
    MasterClass,
    SpecialInspectionClass9,
    Structure,
    AuditLog,
)
from .permissions import IsAdmin
from .serializers import (
    AppSettingSerializer,
    AssignmentInputSerializer,
    BulkHideTargetsRequestSerializer,
    BulkHistoryRequestSerializer,
    Class9SettingCreateSerializer,
    Class9SettingSerializer,
    CreateLayoutSerializer,
    DailyReportGenerateRequestSerializer,
    FactoryMapTargetRequestSerializer,
    InspectionTargetSerializer,
    JobSerializer,
    LayoutMasterListSerializer,
    LayoutObjectSerializer,
    LayoutObjectTypeSerializer,
    LayoutSaveRequestSerializer,
    MachineDetailSerializer,
    MachineMasterSaveSerializer,
    MachineSerializer,
    ManualTargetsRequestSerializer,
    MasterImportRequestSerializer,
    PlanImportRequestSerializer,
    SingleHistoryRequestSerializer,
    SpecialTargetsRequestSerializer,
)
import subprocess
from pathlib import Path

from rest_framework import serializers
from .services import (
    ClassificationError,
    add_factory_map_target,
    add_manual_targets,
    add_special_targets,
    bulk_upsert_history,
    create_job,
    generate_daily_report,
    history_map_for_date,
    import_master_csv,
    import_plan_targets,
    issue_daily_report,
    issue_inspection_sheets,
    print_inspection_file,
    run_job,
    set_check,
    sync_master_class_from_assignment,
    write_history_to_excel,
    resolve_inspection_file,
    resolve_unambiguous_inspection_file,
)


def success_response(**data):
    return Response({"status": "success", **data})


def error_response(error_code, message, http_status=status.HTTP_400_BAD_REQUEST, details=None):
    return Response(
        {
            "status": "error",
            "error_code": error_code,
            "message": message,
            "details": details or {},
        },
        status=http_status,
    )


DEFAULT_LAYOUT_NAME = "default"
LAYOUT_OBJECT_TYPE_DEFAULTS = {
    "machine": ("機械", "#6366f1"),
    "wall": ("壁", "#64748b"),
    "path": ("通路", "#10b981"),
    "area": ("エリア", "#f59e0b"),
    "stairs": ("階段", "#a855f7"),
    "entrance": ("出入口", "#06b6d4"),
}


def ensure_layout_object_types():
    for code, (display_name, color) in LAYOUT_OBJECT_TYPE_DEFAULTS.items():
        LayoutObjectType.objects.get_or_create(
            code=code,
            defaults={"display_name": display_name, "color": color, "selectable": True},
        )


def get_default_layout():
    ensure_layout_object_types()
    layout, _ = LayoutMaster.objects.get_or_create(
        layout_name=DEFAULT_LAYOUT_NAME,
        defaults={"grid_width": 50, "grid_height": 50},
    )
    return layout


def serialize_layout(layout):
    objects = (
        layout.layout_objects.select_related("object_type", "machine")
        .order_by("id")
    )
    object_types = LayoutObjectType.objects.order_by("code")
    return {
        "layout_id": layout.id,
        "layout_name": layout.layout_name,
        "background_image_path": "",
        "grid_width": layout.grid_width,
        "grid_height": layout.grid_height,
        "object_types": LayoutObjectTypeSerializer(object_types, many=True).data,
        "objects": LayoutObjectSerializer(objects, many=True).data,
    }


class JobDetailView(APIView):
    def get(self, request, job_id):
        job = get_object_or_404(Job, job_id=job_id, created_by=request.user)
        return Response(JobSerializer(job).data)


class MasterUpdateView(APIView):
    permission_classes = [IsAdmin]
    def post(self, request):
        serializer = MasterImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        master_file = request.FILES.get("master_file")

        csv_path = None
        if not master_file:
            setting = AppSetting.objects.first()
            if setting and setting.csv_path:
                csv_path = setting.csv_path

        folder_paths = []
        folder_priorities = {}
        setting = AppSetting.objects.first()
        if setting and setting.inspection_folder_paths:
            folder_paths = setting.inspection_folder_paths
            folder_priorities = setting.inspection_folder_priorities or {}

        payload = {
            "force": serializer.validated_data["force"],
            "master_file": getattr(master_file, "name", None),
            "csv_path": csv_path,
        }
        job = create_job(Job.JobType.MASTER_UPDATE, payload, request.user)
        try:
            run_job(
                job,
                lambda: import_master_csv(
                    master_file=master_file,
                    csv_path=csv_path,
                    inspection_folder_paths=folder_paths,
                    inspection_folder_priorities=folder_priorities,
                ),
            )
        except FileNotFoundError:
            return error_response("FILE_NOT_FOUND", "マスタ取込ファイルが保存場所に存在しません。", status.HTTP_404_NOT_FOUND)
        except ClassificationError as exc:
            return classification_error_response(exc)
        except Exception as exc:
            return error_response("ERP_AUTOMATION_FAILED", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"status": "accepted", "job_id": job.job_id}, status=status.HTTP_202_ACCEPTED)


class MasterSearchView(APIView):
    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if not q:
            return Response([])
        masters = Master.objects.filter(
            db_models.Q(code__icontains=q) | db_models.Q(name__icontains=q)
        ).order_by("code")[:20]
        return Response([
            {"code": m.code, "name": m.name, "product_category": m.product_category}
            for m in masters
        ])


class SettingsView(APIView):
    permission_classes = [IsAdmin]
    def get(self, request):
        setting = AppSetting.objects.first()
        if setting is None:
            setting = AppSetting.objects.create()
        return Response(AppSettingSerializer(setting).data)

    def put(self, request):
        setting = AppSetting.objects.first()
        if setting is None:
            setting = AppSetting.objects.create()
        serializer = AppSettingSerializer(setting, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(AppSettingSerializer(setting).data)


class ErpAutomationView(APIView):
    permission_classes = [IsAdmin]
    def post(self, request):
        csv_path = request.data.get("csv_path") or ""
        erp_path = request.data.get("erp_path") or ""

        if not csv_path:
            return error_response("CSV_PATH_NOT_CONFIGURED", "構成CSVのパスが設定されていません。", status.HTTP_400_BAD_REQUEST)
        if not erp_path:
            return error_response("ERP_PATH_NOT_CONFIGURED", "ERPのパスが設定されていません。", status.HTTP_400_BAD_REQUEST)

        csv_path = str(Path(csv_path).resolve())
        module_dir = Path(__file__).resolve().parent.parent.parent / "erp_automation"
        script = module_dir / "erp.py"

        if not script.exists():
            return error_response("SCRIPT_NOT_FOUND", f"スクリプトが見つかりません: {script}", status.HTTP_500_INTERNAL_SERVER_ERROR)

        job = create_job(Job.JobType.MASTER_UPDATE, {"erp_path": erp_path, "csv_path": csv_path}, request.user)

        def run():
            try:
                result = subprocess.run(
                    [sys.executable, str(script), erp_path, csv_path],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"ERP automation failed: {result.stderr.strip()}")
                return {"status": "succeeded", "output": result.stdout.strip()}
            except subprocess.TimeoutExpired:
                raise RuntimeError("ERP automation timed out (300s)")

        try:
            run_job(job, run)
        except Exception as exc:
            return error_response("ERP_AUTOMATION_FAILED", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"status": "accepted", "job_id": job.job_id}, status=status.HTTP_202_ACCEPTED)


class PlansImportView(APIView):
    def post(self, request):
        serializer = PlanImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scan_file = request.FILES.get("scan_file")
        excel_file = request.FILES.get("excel_file")
        sheet_name = serializer.validated_data.get("sheet_name", "")

        if excel_file and not sheet_name:
            return error_response("INVALID_REQUEST", "計画Excelファイルを指定する場合はシート名を入力してください。")
        job = create_job(
            Job.JobType.PLANS_IMPORT,
            {
                "target_date": str(serializer.validated_data["target_date"]),
                "scan_file": getattr(scan_file, "name", None),
                "excel_file": getattr(excel_file, "name", None),
                "sheet_name": sheet_name,
            },
            request.user,
        )
        try:
            run_job(
                job,
                lambda: import_plan_targets(
                    serializer.validated_data["target_date"],
                    scan_file=scan_file,
                    excel_file=excel_file,
                    sheet_name=sheet_name,
                    user=request.user,
                ),
            )
        except FileNotFoundError:
            return error_response("FILE_NOT_FOUND", "取込ファイルが保存場所に存在しません。", status.HTTP_404_NOT_FOUND)
        except ClassificationError as exc:
            return classification_error_response(exc)
        except Exception as exc:
            return error_response("JOB_FAILED", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"status": "accepted", "job_id": job.job_id}, status=status.HTTP_202_ACCEPTED)


class ManualTargetsView(APIView):
    def post(self, request):
        if "class_override" in request.data:
            return error_response("INVALID_REQUEST", "class_overrideは指定できません。")
        serializer = ManualTargetsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session, added_count = add_manual_targets(
                serializer.validated_data["date"], serializer.validated_data["codes"], user=request.user
            )
        except ClassificationError as exc:
            return classification_error_response(exc)
        return success_response(session_id=session.id, added_count=added_count)


def classification_error_response(exc):
    http_status = status.HTTP_409_CONFLICT if exc.error_code in ("CLASS_1_2_CONFLICT", "CLASS_6_7_CONFLICT") else status.HTTP_400_BAD_REQUEST
    return error_response(exc.error_code, exc.message, http_status=http_status, details=exc.details)


class FactoryMapTargetsView(APIView):
    def post(self, request):
        if "class_override" in request.data:
            return error_response("INVALID_REQUEST", "class_overrideは指定できません。")
        serializer = FactoryMapTargetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session, added_count = add_factory_map_target(
                serializer.validated_data["date"],
                serializer.validated_data["machine_id"],
                serializer.validated_data["code"],
                user=request.user,
            )
        except ClassificationError as exc:
            return classification_error_response(exc)
        return success_response(session_id=session.id, added_count=added_count)


class SpecialTargetsView(APIView):
    def post(self, request):
        if "class_override" in request.data:
            return error_response("INVALID_REQUEST", "class_overrideは指定できません。")
        serializer = SpecialTargetsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session, added_count = add_special_targets(
                serializer.validated_data["date"], serializer.validated_data["codes"], user=request.user
            )
        except ClassificationError as exc:
            return classification_error_response(exc)
        return success_response(session_id=session.id, added_count=added_count)


class InspectionTargetsView(APIView):
    def get(self, request):
        target_date = request.query_params.get("date")
        if not target_date:
            return error_response("INVALID_REQUEST", "date query parameter is required.")

        session = InspectionSession.objects.filter(target_date=target_date, owner_user=request.user).first()
        if session is None:
            return Response([])

        targets = (
            InspectionTarget.objects.filter(session=session, visible=True)
            .select_related("master")
            .prefetch_related("warnings")
            .order_by("normalized_code")
        )
        serializer = InspectionTargetSerializer(
            targets,
            many=True,
            context={"histories": history_map_for_date(target_date, request.user)},
        )
        return Response(serializer.data)


def _parse_summary_period(request):
    try:
        start = date.fromisoformat(request.query_params.get("start", ""))
        end = date.fromisoformat(request.query_params.get("end", ""))
    except ValueError:
        return None, None, error_response("INVALID_PERIOD", "start and end must be valid ISO dates.")
    if start > end:
        return None, None, error_response("INVALID_PERIOD", "start must not be after end.")
    if (end - start).days > 366:
        return None, None, error_response("INVALID_PERIOD", "The selected period must be 367 days or less.")
    return start, end, None


def _history_class_map(histories):
    master_ids = {row.master_id for row in histories if not row.class_override}
    mapping = {}
    for master_id, class_no in (
        MasterClass.objects.filter(master_id__in=master_ids, class_master__isnull=False)
        .exclude(class_master__class_no=9)
        .order_by("id")
        .values_list("master_id", "class_master__class_no")
    ):
        mapping.setdefault(master_id, class_no)
    return {row.history_id: row.class_override or mapping.get(row.master_id) for row in histories}


def _summary_source(start, end):
    histories = list(
        History.objects.filter(date__range=(start, end), deleted_at__isnull=True)
        .select_related("master", "created_by")
        .order_by("date", "history_id")
    )
    sessions = list(
        InspectionSession.objects.filter(target_date__range=(start, end), deleted_at__isnull=True)
        .select_related("owner_user")
        .order_by("target_date", "owner_user__display_name")
    )
    return histories, sessions, _history_class_map(histories)


class InspectionNoteView(APIView):
    def get(self, request):
        try:
            target_date = date.fromisoformat(request.query_params.get("date", ""))
        except ValueError:
            return error_response("INVALID_DATE", "date must be a valid ISO date.")
        session = InspectionSession.objects.filter(
            owner_user=request.user, target_date=target_date, deleted_at__isnull=True
        ).first()
        return Response({"date": str(target_date), "note": session.note if session else ""})

    def put(self, request):
        try:
            target_date = date.fromisoformat(str(request.data.get("date", "")))
        except ValueError:
            return error_response("INVALID_DATE", "date must be a valid ISO date.")
        note = request.data.get("note", "")
        if not isinstance(note, str):
            return error_response("INVALID_REQUEST", "note must be a string.")
        session, _ = InspectionSession.objects.get_or_create(
            owner_user=request.user,
            target_date=target_date,
            defaults={"created_by": request.user, "updated_by": request.user},
        )
        session.note = note
        session.updated_by = request.user
        session.deleted_at = None
        session.deleted_by = None
        session.save(update_fields=["note", "updated_by", "deleted_at", "deleted_by", "updated_at"])
        return Response({"date": str(target_date), "note": session.note})


class InspectionSummaryView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        start, end, invalid = _parse_summary_period(request)
        if invalid:
            return invalid
        histories, sessions, class_map = _summary_source(start, end)
        class_totals = Counter()
        item_totals = Counter()
        daily = defaultdict(lambda: {"total": 0, "classes": Counter(), "inspectors": defaultdict(lambda: {"name": "不明", "total": 0, "classes": Counter()})})
        requested_classes = request.query_params.get("classes")
        try:
            top_classes = set(range(1, 10)) if requested_classes is None else {
                int(value) for value in requested_classes.split(",") if value
            }
        except ValueError:
            return error_response("INVALID_CLASSES", "classes must be comma-separated integers.")
        requested_inspectors = request.query_params.get("inspectors")
        top_inspectors = None
        if requested_inspectors is not None:
            top_inspectors = set()
            if requested_inspectors:
                for value in requested_inspectors.split(","):
                    token = value.strip()
                    if token == "unknown":
                        top_inspectors.add(None)
                    else:
                        try:
                            top_inspectors.add(int(token))
                        except ValueError:
                            return error_response("INVALID_INSPECTORS", "inspectors must be comma-separated integer IDs or unknown.")
        for row in histories:
            class_no = class_map.get(row.history_id)
            inspector_id = row.created_by_id
            inspector = row.created_by.display_name if row.created_by else "不明"
            day = daily[str(row.date)]
            day["total"] += 1
            day["inspectors"][inspector_id]["name"] = inspector
            day["inspectors"][inspector_id]["total"] += 1
            if class_no in range(1, 10):
                class_totals[class_no] += 1
                day["classes"][class_no] += 1
                day["inspectors"][inspector_id]["classes"][class_no] += 1
            if class_no in top_classes and (top_inspectors is None or inspector_id in top_inspectors):
                item_totals[(row.master.code, row.master.name)] += 1
        notes_by_day = defaultdict(list)
        for session in sessions:
            if session.note.strip():
                inspector_id = session.owner_user_id
                inspector = session.owner_user.display_name if session.owner_user else "不明"
                notes_by_day[str(session.target_date)].append({
                    "user_id": inspector_id,
                    "inspector": inspector,
                    "note": session.note,
                })
                daily[str(session.target_date)]["inspectors"][inspector_id]["name"] = inspector
        rows = []
        cursor = start
        while cursor <= end:
            key = str(cursor)
            value = daily[key]
            rows.append({
                "date": key,
                "total": value["total"],
                "classes": {str(no): value["classes"][no] for no in range(1, 10)},
                "inspectors": [
                    {"user_id": user_id, "name": detail["name"], "total": detail["total"], "classes": {str(no): detail["classes"][no] for no in range(1, 10)}}
                    for user_id, detail in sorted(value["inspectors"].items(), key=lambda item: (item[1]["name"], item[0] or 0))
                ],
                "notes": notes_by_day[key],
            })
            cursor += timedelta(days=1)
        months = {date.today().strftime("%Y-%m")}
        months.update(value.strftime("%Y-%m") for value in History.objects.filter(deleted_at__isnull=True).dates("date", "month"))
        months.update(value.strftime("%Y-%m") for value in InspectionSession.objects.filter(deleted_at__isnull=True).dates("target_date", "month"))
        return Response({
            "start": str(start), "end": str(end), "months": sorted(months, reverse=True),
            "class_totals": {str(no): class_totals[no] for no in range(1, 10)},
            "top_items": [{"code": code, "name": name, "count": count} for (code, name), count in item_totals.most_common(10)],
            "days": rows,
        })


class InspectionSummaryCsvView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, csv_type):
        start, end, invalid = _parse_summary_period(request)
        if invalid:
            return invalid
        histories, sessions, class_map = _summary_source(start, end)
        output = StringIO(newline="")
        output.write("\ufeff")
        writer = csv.writer(output, lineterminator="\r\n")
        if csv_type == "counts":
            writer.writerow(["日付", "総数", *[f"クラス{no}" for no in range(1, 10)]])
            counts = defaultdict(Counter)
            for row in histories:
                counts[row.date]["total"] += 1
                class_no = class_map.get(row.history_id)
                if class_no in range(1, 10):
                    counts[row.date][class_no] += 1
            cursor = start
            while cursor <= end:
                writer.writerow([cursor, counts[cursor]["total"], *[counts[cursor][no] for no in range(1, 10)]])
                cursor += timedelta(days=1)
            prefix = "inspection-counts"
        elif csv_type == "notes":
            writer.writerow(["日付", "検査者名", "ノート内容"])
            for session in sessions:
                if session.note.strip():
                    writer.writerow([session.target_date, session.owner_user.display_name if session.owner_user else "不明", session.note])
            prefix = "inspection-notes"
        else:
            return error_response("INVALID_CSV_TYPE", "csv_type must be counts or notes.")
        response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{prefix}_{start}_{end}.csv"'
        return response


class InspectionTargetDetailView(APIView):
    def delete(self, request, target_id):
        target = get_object_or_404(InspectionTarget, id=target_id, session__owner_user=request.user)
        target.visible = False
        target.deleted_at = timezone.now()
        target.deleted_by = request.user
        target.updated_by = request.user
        target.save(update_fields=["visible", "deleted_at", "deleted_by", "updated_by", "updated_at"])
        return success_response()


class TargetInspectionFileView(APIView):
    def get(self, request, target_id):
        target = get_object_or_404(
            InspectionTarget.objects.select_related("master"), id=target_id, session__owner_user=request.user
        )
        if not target.master:
            return error_response(
                "NO_MASTER", "検査対象にマスターが登録されていません"
            )

        try:
            insp_file = resolve_inspection_file(target.master, target.class_override)
            if insp_file is None and target.class_override is None:
                insp_file = resolve_unambiguous_inspection_file(target.master)
        except ClassificationError as exc:
            return classification_error_response(exc)
        if not insp_file:
            return error_response(
                "FILE_NOT_FOUND", "検査書ファイルが見つかりません"
            )

        file_path = insp_file["file_path"] if isinstance(insp_file, dict) else insp_file.file_path
        if not os.path.exists(file_path):
            return error_response(
                "FILE_NOT_FOUND",
                "検査書ファイルが保存場所に存在しません。",
            )

        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".xls", ".xlsx", ".xlsm"):
            try:
                os.startfile(file_path)
            except OSError as exc:
                return error_response(
                    "OPEN_FAILED", str(exc), http_status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            return success_response(message="ファイルを起動しました")

        content_type = (
            mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        )
        response = FileResponse(open(file_path, "rb"), content_type=content_type)
        response["Content-Disposition"] = (
            f'inline; filename="{os.path.basename(file_path)}"'
        )
        return response


class TargetInspectionFilePrintView(APIView):
    def post(self, request, target_id):
        try:
            print_inspection_file(target_id, request.user)
            return success_response(message="印刷を開始しました")
        except InspectionTarget.DoesNotExist:
            return error_response(
                "NOT_FOUND",
                "検査対象が見つかりません",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        except ClassificationError as exc:
            return classification_error_response(exc)
        except FileNotFoundError:
            return error_response(
                "FILE_NOT_FOUND",
                "検査書ファイルが保存場所に存在しません。",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError as exc:
            return error_response("INVALID_REQUEST", str(exc))
        except Exception:
            return error_response(
                "PRINT_FAILED", "検査書の印刷に失敗しました。", http_status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BulkHideTargetsView(APIView):
    def post(self, request):
        serializer = BulkHideTargetsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        date = serializer.validated_data["date"]
        session = InspectionSession.objects.filter(target_date=date, owner_user=request.user).first()
        if session is None:
            return success_response(hidden_count=0)
        ids = serializer.validated_data["target_ids"]
        hidden = InspectionTarget.objects.filter(session=session, id__in=ids).update(
            visible=False, deleted_at=timezone.now(), deleted_by=request.user,
            updated_by=request.user, updated_at=timezone.now()
        )
        return success_response(hidden_count=hidden)


class BulkHistoryView(APIView):
    def post(self, request):
        serializer = BulkHistoryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated_count = bulk_upsert_history(
                serializer.validated_data["date"],
                serializer.validated_data["items"],
                user=request.user,
            )
        except ClassificationError as exc:
            return classification_error_response(exc)
        return success_response(updated_count=updated_count)


class SingleHistoryView(APIView):
    def patch(self, request):
        serializer = SingleHistoryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            set_check(
                serializer.validated_data["date"],
                serializer.validated_data["target_id"],
                serializer.validated_data["time"],
                serializer.validated_data["checked"],
                user=request.user,
            )
        except ClassificationError as exc:
            return classification_error_response(exc)
        return success_response()

    def get(self, request):
        target_date = request.query_params.get("date")
        if not target_date:
            return error_response("INVALID_REQUEST", "date query parameter is required.")

        rows = (
            History.objects.filter(date=target_date, created_by=request.user, deleted_at__isnull=True)
            .select_related("master")
            .order_by("master__code", "time_slot")
        )
        return Response(
            [
                {
                    "code": row.master.code,
                    "time": row.time_slot,
                }
                for row in rows
            ]
        )


class HistoryWriteToFileView(APIView):
    def post(self, request):
        target_date = request.data.get("date")
        if not target_date:
            return error_response("INVALID_REQUEST", "date is required.")
        try:
            from datetime import date as date_type
            from django.conf import settings
            if isinstance(target_date, str):
                from datetime import datetime
                target_date = datetime.strptime(target_date, "%Y-%m-%d").date()
            written_count = write_history_to_excel(target_date, request.user)
        except FileNotFoundError:
            return error_response("FILE_NOT_FOUND", "履歴ファイルが保存場所に存在しません。", status.HTTP_404_NOT_FOUND)
        except Exception as exc:
            return error_response("HISTORY_WRITE_FAILED", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
        return success_response(written_count=written_count)


class FactoryMapView(APIView):
    def get(self, request):
        target_date = request.query_params.get("date")
        layout_id = request.query_params.get("layout_id")
        if layout_id:
            layout = get_object_or_404(LayoutMaster, id=layout_id)
        else:
            layout = get_default_layout()
        target_codes = set()
        target_codes_by_machine = {}
        warnings = []

        if target_date:
            session = InspectionSession.objects.filter(target_date=target_date, owner_user=request.user).first()
            if session:
                targets = InspectionTarget.objects.filter(session=session, visible=True).filter(
                    db_models.Q(class_override__range=(1, 5)) | db_models.Q(master__isnull=True)
                ).select_related("master")
                target_codes = {target.normalized_code for target in targets}
                assigned_codes = set(
                    MachineAssignment.objects.filter(code__code__in=target_codes).values_list("code__code", flat=True)
                )
                for code in sorted(target_codes - assigned_codes):
                    warnings.append({"code": code, "error_code": "NO_MATCHING_MACHINE"})

                for assignment in (
                    MachineAssignment.objects.filter(code__code__in=target_codes)
                    .select_related("machine", "code")
                    .order_by("machine_id", "code__code")
                ):
                    target_codes_by_machine.setdefault(assignment.machine_id, []).append(assignment.code.code)

        machines = []
        for machine in Machine.objects.filter(is_active=True).prefetch_related("assignments__code").order_by("machine_no"):
            assigned_items = [
                {"code": assignment.code.code, "name": assignment.code.name}
                for assignment in machine.assignments.all()
            ]
            assigned_codes = [item["code"] for item in assigned_items]
            machine_target_codes = target_codes_by_machine.get(machine.id, [])
            machines.append(
                {
                    "machine_id": machine.id,
                    "machine_no": machine.machine_no,
                    "machine_name": machine.machine_name,
                    "shape_type": machine.shape_type,
                    "x": machine.map_x,
                    "y": machine.map_y,
                    "width": machine.width,
                    "height": machine.height,
                    "status": "pending" if machine_target_codes else "idle",
                    "assigned_items": assigned_items,
                    "target_codes": machine_target_codes,
                }
            )

        return Response(
            {
                "image_url": "",
                "layout": serialize_layout(layout),
                "machines": machines,
                "warnings": warnings,
            }
        )


class FactoryMapLayoutView(APIView):
    def get_permissions(self):
        return [IsAdmin()] if self.request.method in ("PUT", "DELETE") else super().get_permissions()
    def get(self, request, layout_id=None):
        if layout_id:
            layout = get_object_or_404(LayoutMaster, id=layout_id)
        else:
            layout_id_param = request.query_params.get("layout_id")
            if layout_id_param:
                layout = get_object_or_404(LayoutMaster, id=layout_id_param)
            else:
                layout = get_default_layout()
        return Response(serialize_layout(layout))

    @transaction.atomic
    def put(self, request):
        serializer = LayoutSaveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ensure_layout_object_types()

        layout_id = request.query_params.get("layout_id")
        if layout_id:
            layout = get_object_or_404(LayoutMaster, id=layout_id)
        else:
            layout, _ = LayoutMaster.objects.get_or_create(layout_name=data["layout_name"])

        layout.grid_width = data["grid_width"]
        layout.grid_height = data["grid_height"]
        layout.save()

        layout.layout_objects.all().delete()
        object_types = {item.code: item for item in LayoutObjectType.objects.all()}
        machines = {item.id: item for item in Machine.objects.filter(id__in=[
            obj["machine_id"] for obj in data["objects"] if obj.get("machine_id") is not None
        ])}

        for obj in data["objects"]:
            machine_id = obj.get("machine_id")
            object_name = obj.get("object_name") or ""
            machine = machines.get(machine_id) if machine_id is not None else None
            if machine and not object_name:
                object_name = machine.machine_name
            LayoutObject.objects.create(
                layout=layout,
                object_type=object_types[obj["type"]],
                machine=machine,
                object_name=object_name,
                grid_x=obj["grid_x"],
                grid_y=obj["grid_y"],
                width=obj["width"],
                height=obj["height"],
                rotation=obj.get("rotation", 0),
                meta_json=obj.get("meta_json", {}),
            )

        return Response(serialize_layout(layout))

    def delete(self, request, layout_id=None):
        if layout_id is None:
            layout_id = request.query_params.get("layout_id")
        if not layout_id:
            return error_response("INVALID_REQUEST", "layout_id is required.")
        layout = get_object_or_404(LayoutMaster, id=layout_id)
        if layout.layout_name == "default":
            return error_response("FORBIDDEN", "デフォルトレイアウトは削除できません。")
        layout.delete()
        return Response({"status": "deleted"})


class FactoryMapLayoutsView(APIView):
    def get_permissions(self):
        return [IsAdmin()] if self.request.method == "POST" else super().get_permissions()
    def get(self, request):
        layouts = LayoutMaster.objects.all().order_by("id")
        serializer = LayoutMasterListSerializer(layouts, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = CreateLayoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data["layout_name"]
        if LayoutMaster.objects.filter(layout_name=name).exists():
            return error_response("DUPLICATE_NAME", f"レイアウト名 '{name}' は既に存在します。")
        layout = LayoutMaster.objects.create(layout_name=name, owner_user=request.user)
        return Response(LayoutMasterListSerializer(layout).data, status=status.HTTP_201_CREATED)


class MachineListView(APIView):
    def get(self, request):
        machines = Machine.objects.filter(is_active=True).order_by("machine_no")
        serializer = MachineSerializer(machines, many=True)
        return Response(serializer.data)


class MachineMasterView(APIView):
    permission_classes = [IsAdmin]
    def get(self, request):
        machines = Machine.objects.all().order_by("machine_no").prefetch_related("assignments__code")
        result = []
        for m in machines:
            assignments = [
                {"code": a.code.code, "name": a.code.name, "assignment_class": a.assignment_class}
                for a in m.assignments.all()
            ]
            result.append({
                "id": m.id,
                "machine_no": m.machine_no,
                "machine_name": m.machine_name,
                "machine_class": m.machine_class,
                "shape_type": m.shape_type,
                "map_x": m.map_x,
                "map_y": m.map_y,
                "width": m.width,
                "height": m.height,
                "is_active": m.is_active,
                "assignments": assignments,
            })
        return Response(result)

    @transaction.atomic
    def put(self, request):
        serializer = MachineMasterSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        previous_master_ids = set()
        if data.get("id"):
            machine = get_object_or_404(Machine, id=data["id"])
            previous_master_ids = set(machine.assignments.values_list("code_id", flat=True))
            machine.machine_no = data["machine_no"]
            machine.machine_name = data["machine_name"]
            machine.machine_class = data.get("machine_class")
            machine.shape_type = data["shape_type"]
            machine.map_x = data["map_x"]
            machine.map_y = data["map_y"]
            machine.width = data["width"]
            machine.height = data["height"]
            machine.is_active = data["is_active"]
            machine.save()
        else:
            machine = Machine.objects.create(
                machine_no=data["machine_no"],
                machine_name=data["machine_name"],
                machine_class=data.get("machine_class"),
                shape_type=data["shape_type"],
                map_x=data["map_x"],
                map_y=data["map_y"],
                width=data["width"],
                height=data["height"],
                is_active=data["is_active"],
            )

        machine.assignments.all().delete()
        assignments_data = data.get("assignments", [])
        mc = machine.machine_class
        for item in assignments_data:
            code_str = item["code"]
            master = Master.objects.filter(code=code_str).first()
            if master:
                if mc in (1, 2):
                    ac = mc
                else:
                    ac = item.get("assignment_class")
                MachineAssignment.objects.create(
                    machine=machine,
                    code=master,
                    assignment_class=ac,
                )
        affected_master_ids = previous_master_ids | set(machine.assignments.values_list("code_id", flat=True))
        try:
            for master in Master.objects.filter(code__in=affected_master_ids):
                sync_master_class_from_assignment(master)
        except ClassificationError as exc:
            transaction.set_rollback(True)
            return classification_error_response(exc)

        return Response({
            "id": machine.id,
            "machine_no": machine.machine_no,
            "machine_name": machine.machine_name,
            "machine_class": machine.machine_class,
            "shape_type": machine.shape_type,
            "map_x": machine.map_x,
            "map_y": machine.map_y,
            "width": machine.width,
            "height": machine.height,
            "is_active": machine.is_active,
            "assignments": [
                {"code": a.code.code, "name": a.code.name, "assignment_class": a.assignment_class}
                for a in machine.assignments.select_related("code").all()
            ],
        })


class InspectionSheetIssueView(APIView):
    def post(self, request):
        target_date = request.data.get("date")
        job = create_job(Job.JobType.INSPECTION_SHEET_ISSUE, request.data, request.user)
        try:
            run_job(job, lambda: issue_inspection_sheets(target_date=target_date, user=request.user))
        except FileNotFoundError:
            return error_response("FILE_NOT_FOUND", "検査書テンプレートが保存場所に存在しません。", status.HTTP_500_INTERNAL_SERVER_ERROR)
        except RuntimeError as exc:
            return error_response("COM_FAILED", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as exc:
            return error_response(
                "INSPECTION_SHEET_ISSUE_FAILED",
                str(exc),
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({"status": "accepted", "job_id": job.job_id}, status=status.HTTP_202_ACCEPTED)


class DailyReportGenerateView(APIView):
    def post(self, request):
        serializer = DailyReportGenerateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_date = serializer.validated_data["date"]
        job = create_job(
            Job.JobType.DAILY_REPORT_GENERATE,
            {"date": str(target_date)},
            request.user,
        )

        try:
            run_job(job, lambda: generate_daily_report(target_date, request.user))
        except FileNotFoundError:
            return error_response("FILE_NOT_FOUND", "日報テンプレートが保存場所に存在しません。", status.HTTP_500_INTERNAL_SERVER_ERROR)
        except PermissionError as exc:
            return error_response("FILE_IN_USE", str(exc), status.HTTP_409_CONFLICT)
        except Exception as exc:
            return error_response(
                "DAILY_REPORT_GENERATE_FAILED",
                str(exc),
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"status": "accepted", "job_id": job.job_id}, status=status.HTTP_202_ACCEPTED)


class DailyReportIssueView(APIView):
    def post(self, request):
        serializer = DailyReportGenerateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_date = serializer.validated_data["date"]
        job = create_job(
            Job.JobType.DAILY_REPORT_GENERATE,
            {"date": str(target_date)},
            request.user,
        )

        try:
            run_job(job, lambda: issue_daily_report(target_date, request.user))
        except FileNotFoundError:
            return error_response("FILE_NOT_FOUND", "日報テンプレートが保存場所に存在しません。", status.HTTP_500_INTERNAL_SERVER_ERROR)
        except PermissionError as exc:
            return error_response("FILE_IN_USE", str(exc), status.HTTP_409_CONFLICT)
        except Exception as exc:
            return error_response(
                "DAILY_REPORT_ISSUE_FAILED",
                str(exc),
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"status": "accepted", "job_id": job.job_id}, status=status.HTTP_202_ACCEPTED)


class LayoutObjectTypeColorUpdateSerializer(serializers.Serializer):
    color = serializers.CharField(max_length=32)


class LayoutObjectTypeColorUpdateView(APIView):
    permission_classes = [IsAdmin]
    def patch(self, request, code):
        try:
            obj_type = LayoutObjectType.objects.get(code=code)
        except LayoutObjectType.DoesNotExist:
            return error_response("NOT_FOUND", "Object type not found.", status.HTTP_404_NOT_FOUND)

        serializer = LayoutObjectTypeColorUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj_type.color = serializer.validated_data["color"]
        obj_type.save()
        return Response(LayoutObjectTypeSerializer(obj_type).data)


class Class9SettingsView(APIView):
    permission_classes = [IsAdmin]
    def get(self, request):
        qs = SpecialInspectionClass9.objects.select_related("master").all()
        return Response([
            {
                "id": sic.id,
                "code": sic.master.code,
                "name": sic.master.name,
                "inspection_sheet_path": sic.inspection_sheet_path,
            }
            for sic in qs
        ])

    @transaction.atomic
    def post(self, request):
        serializer = Class9SettingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data["code"]
        inspection_sheet_path = serializer.validated_data.get("inspection_sheet_path", "")

        master = Master.objects.filter(code=code).first()
        if not master:
            return error_response("MASTER_NOT_FOUND", f"コード '{code}' が見つかりません。", status.HTTP_404_NOT_FOUND)

        sic, created = SpecialInspectionClass9.objects.update_or_create(
            master=master,
            defaults={
                "inspection_sheet_path": inspection_sheet_path,
            },
        )
        return Response({
            "id": sic.id,
            "code": master.code,
            "name": master.name,
            "inspection_sheet_path": sic.inspection_sheet_path,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, pk=None):
        if pk is None:
            pk = request.query_params.get("id")
        if not pk:
            return error_response("INVALID_REQUEST", "id is required.")
        sic = get_object_or_404(SpecialInspectionClass9, id=pk)
        sic.delete()
        return success_response()


class SeedMasterView(APIView):
    permission_classes = [IsAdmin]
    def post(self, request):
        items = request.data.get("items", [])
        if not isinstance(items, list):
            return error_response("INVALID_REQUEST", "items must be a list.")

        updated_count = 0
        for item in items:
            code = str(item.get("code", "")).strip().upper()
            name = str(item.get("name", "")).strip()
            if not code or not name:
                continue
            Master.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": item.get("category"),
                    "node_type": item.get("node_type", ""),
                    "node_type_1": item.get("node_type_1", ""),
                    "node_type_2": item.get("node_type_2", ""),
                    "product_category": item.get("product_category", ""),
                    "department": item.get("department", ""),
                    "updated_at": timezone.now(),
                },
            )
            updated_count += 1

        return success_response(updated_count=updated_count)


class InspectionFileOpenByCodeView(APIView):
    def get(self, request):
        code = request.query_params.get("code", "").strip().upper()
        if not code:
            return error_response("INVALID_REQUEST", "code is required.")

        master = Master.objects.filter(code=code).first()
        try:
            insp_file = resolve_unambiguous_inspection_file(master) if master else None
        except ClassificationError as exc:
            return classification_error_response(exc)
        if not insp_file:
            return error_response("FILE_NOT_FOUND", "検査書ファイルが見つかりません")

        file_path = insp_file["file_path"] if isinstance(insp_file, dict) else insp_file.file_path
        if not os.path.exists(file_path):
            return error_response("FILE_NOT_FOUND", "検査書ファイルが保存場所に存在しません。")

        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".xls", ".xlsx", ".xlsm"):
            try:
                os.startfile(file_path)
            except OSError as exc:
                return error_response(
                    "OPEN_FAILED", str(exc), http_status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            return success_response(message="ファイルを起動しました")

        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        response = FileResponse(open(file_path, "rb"), content_type=content_type)
        response["Content-Disposition"] = f'inline; filename="{os.path.basename(file_path)}"'
        return response


class InspectionFilePdfByCodeView(APIView):
    def get(self, request):
        code = request.query_params.get("code", "").strip().upper()
        if not code:
            return error_response("INVALID_REQUEST", "code is required.")

        master = Master.objects.filter(code=code).first()
        try:
            insp_file = resolve_unambiguous_inspection_file(master) if master else None
        except ClassificationError as exc:
            return classification_error_response(exc)
        if not insp_file:
            return error_response("FILE_NOT_FOUND", "検査書ファイルが見つかりません")

        file_path = insp_file["file_path"] if isinstance(insp_file, dict) else insp_file.file_path
        if not os.path.exists(file_path):
            return error_response("FILE_NOT_FOUND", "検査書ファイルが保存場所に存在しません。")

        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext in (".xls", ".xlsx", ".xlsm"):
                from quality.services import convert_excel_to_pdf
                pdf_path = convert_excel_to_pdf(file_path)
                cleanup = True
            elif ext == ".pdf":
                pdf_path = file_path
                cleanup = False
            else:
                return error_response("UNSUPPORTED", "対応していないファイル形式です")
        except Exception as exc:
            return error_response("CONVERT_FAILED", str(exc), http_status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            response = FileResponse(open(pdf_path, "rb"), content_type="application/pdf")
        except OSError as exc:
            if cleanup:
                try:
                    os.unlink(pdf_path)
                except OSError:
                    pass
            return error_response("OPEN_FAILED", str(exc), http_status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        response["Content-Disposition"] = f'inline; filename="{os.path.basename(file_path)}.pdf"'
        if cleanup:
            def _cleanup():
                try:
                    os.unlink(pdf_path)
                except OSError:
                    pass
            response._resource_closers.append(_cleanup)
        return response


class InspectionFilePrintByCodeView(APIView):
    def post(self, request):
        code = request.query_params.get("code", "").strip().upper()
        if not code:
            return error_response("INVALID_REQUEST", "code is required.")

        master = Master.objects.filter(code=code).first()
        try:
            insp_file = resolve_unambiguous_inspection_file(master) if master else None
        except ClassificationError as exc:
            return classification_error_response(exc)
        if not insp_file:
            return error_response("FILE_NOT_FOUND", "検査書ファイルが見つかりません")

        file_path = insp_file["file_path"] if isinstance(insp_file, dict) else insp_file.file_path
        if not os.path.exists(file_path):
            return error_response("FILE_NOT_FOUND", "検査書ファイルが保存場所に存在しません。")

        try:
            os.startfile(file_path, "print")
            return success_response(message="印刷を開始しました")
        except Exception as exc:
            return error_response("PRINT_FAILED", str(exc), http_status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class StructureView(APIView):
    def get(self, request):
        code = request.query_params.get("code", "").strip().upper()
        if not code:
            return error_response("INVALID_REQUEST", "code query parameter is required.")

        all_edges: list[Structure] = []
        visited: set[str] = set()
        queue = [code]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            records = list(Structure.objects.filter(parent_code=current))
            for r in records:
                all_edges.append(r)
                if r.child_code not in visited:
                    queue.append(r.child_code)

        codes = {code}
        for r in all_edges:
            codes.add(r.parent_code)
            codes.add(r.child_code)

        has_file_codes: set[str] = set(
            InspectionFile.objects.filter(master__code__in=list(codes))
            .values_list("master__code", flat=True)
        )

        master_map: dict[str, dict] = {}
        for m in Master.objects.filter(code__in=list(codes)):
            master_map[m.code] = {
                "name": m.name,
                "department": m.department,
                "node_type_1": m.node_type_1,
                "node_type_2": m.node_type_2,
                "has_inspection_file": m.code in has_file_codes,
            }

        EMPTY = {"name": "", "department": "", "node_type_1": "", "node_type_2": "", "has_inspection_file": False}
        root_info = master_map.get(code, {**EMPTY, "name": code})

        def get_info(c: str) -> dict:
            return master_map.get(c, {**EMPTY, "name": c})

        edges = []
        for r in all_edges:
            p = get_info(r.parent_code)
            c = get_info(r.child_code)
            edges.append({
                "parent_code": r.parent_code,
                "child_code": r.child_code,
                "parent_name": p["name"],
                "child_name": c["name"],
                "parent_department": p["department"],
                "parent_node_type_1": p["node_type_1"],
                "parent_node_type_2": p["node_type_2"],
                "parent_has_inspection_file": p["has_inspection_file"],
                "child_department": c["department"],
                "child_node_type_1": c["node_type_1"],
                "child_node_type_2": c["node_type_2"],
                "child_has_inspection_file": c["has_inspection_file"],
                "level": r.level,
                "quantity": float(r.quantity) if r.quantity is not None else None,
            })

        return Response({
            "root_code": code,
            "root_name": root_info["name"],
            "root_department": root_info["department"],
            "root_node_type_1": root_info["node_type_1"],
            "root_node_type_2": root_info["node_type_2"],
            "root_has_inspection_file": root_info["has_inspection_file"],
            "edges": edges,
        })


class StructureReverseRootsView(APIView):
    def get(self, request):
        code = request.query_params.get("code", "").strip().upper()
        if not code:
            return error_response("INVALID_REQUEST", "code query parameter is required.")

        roots: set[str] = set()
        visited_nodes: set[str] = set()
        queue = [code]

        while queue:
            cur = queue.pop(0)
            if cur in visited_nodes:
                continue
            visited_nodes.add(cur)
            parents = list(
                Structure.objects.filter(child_code=cur).values_list("parent_code", flat=True)
            )
            if not parents:
                roots.add(cur)
                continue
            for p in parents:
                if p in visited_nodes:
                    continue
                if not Structure.objects.filter(child_code=p).exists():
                    roots.add(p)
                else:
                    queue.append(p)

        roots = sorted(roots)
        data = []
        for rc in roots:
            m = Master.objects.filter(code=rc).first()
            data.append({"root_code": rc, "root_name": m.name if m else rc})
        return Response({"code": code, "roots": data})
