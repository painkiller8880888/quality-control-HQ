import mimetypes
import os
import sys
import uuid

from django.conf import settings
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db import models as db_models
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AppSetting,
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
)
from .serializers import (
    AppSettingSerializer,
    AssignmentInputSerializer,
    BulkHideTargetsRequestSerializer,
    BulkHistoryRequestSerializer,
    CreateLayoutSerializer,
    DailyReportGenerateRequestSerializer,
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
)
import subprocess
from pathlib import Path

from rest_framework import serializers
from .services import (
    add_manual_targets,
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
        "background_image_path": layout.background_image_path,
        "grid_width": layout.grid_width,
        "grid_height": layout.grid_height,
        "object_types": LayoutObjectTypeSerializer(object_types, many=True).data,
        "objects": LayoutObjectSerializer(objects, many=True).data,
    }


class JobDetailView(APIView):
    def get(self, request, job_id):
        job = get_object_or_404(Job, job_id=job_id)
        return Response(JobSerializer(job).data)


class MasterUpdateView(APIView):
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
        setting = AppSetting.objects.first()
        if setting and setting.inspection_folder_paths:
            folder_paths = setting.inspection_folder_paths

        payload = {
            "force": serializer.validated_data["force"],
            "master_file": getattr(master_file, "name", None),
            "csv_path": csv_path,
        }
        job = create_job(Job.JobType.MASTER_UPDATE, payload)
        try:
            run_job(
                job,
                lambda: import_master_csv(
                    master_file=master_file,
                    csv_path=csv_path,
                    inspection_folder_paths=folder_paths,
                ),
            )
        except FileNotFoundError as exc:
            return error_response("FILE_NOT_FOUND", str(exc), status.HTTP_404_NOT_FOUND)
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

        job = create_job(Job.JobType.MASTER_UPDATE, {"erp_path": erp_path, "csv_path": csv_path})

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
        job = create_job(
            Job.JobType.PLANS_IMPORT,
            {
                "target_date": str(serializer.validated_data["target_date"]),
                "scan_file": getattr(scan_file, "name", None),
                "excel_file": getattr(excel_file, "name", None),
            },
        )
        try:
            run_job(
                job,
                lambda: import_plan_targets(
                    serializer.validated_data["target_date"],
                    scan_file=scan_file,
                    excel_file=excel_file,
                ),
            )
        except FileNotFoundError as exc:
            return error_response("FILE_NOT_FOUND", str(exc), status.HTTP_404_NOT_FOUND)
        except Exception as exc:
            return error_response("JOB_FAILED", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"status": "accepted", "job_id": job.job_id}, status=status.HTTP_202_ACCEPTED)


class ManualTargetsView(APIView):
    def post(self, request):
        serializer = ManualTargetsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session, added_count = add_manual_targets(
            serializer.validated_data["date"],
            serializer.validated_data["codes"],
        )
        return success_response(session_id=session.id, added_count=added_count)


class InspectionTargetsView(APIView):
    def get(self, request):
        target_date = request.query_params.get("date")
        if not target_date:
            return error_response("INVALID_REQUEST", "date query parameter is required.")

        session = InspectionSession.objects.filter(target_date=target_date).first()
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
            context={"histories": history_map_for_date(target_date)},
        )
        return Response(serializer.data)


class InspectionTargetDetailView(APIView):
    def delete(self, request, target_id):
        target = get_object_or_404(InspectionTarget, id=target_id)
        target.visible = False
        target.save()
        return success_response()


class TargetInspectionFileView(APIView):
    def get(self, request, target_id):
        target = get_object_or_404(
            InspectionTarget.objects.select_related("master"), id=target_id
        )
        if not target.master:
            return error_response(
                "NO_MASTER", "検査対象にマスターが登録されていません"
            )

        insp_file = InspectionFile.objects.filter(master=target.master).first()
        if not insp_file:
            return error_response(
                "FILE_NOT_FOUND", "検査書ファイルが見つかりません"
            )

        file_path = insp_file.file_path
        if not os.path.exists(file_path):
            return error_response(
                "FILE_NOT_FOUND",
                f"ファイルが存在しません: {file_path}",
            )

        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".xls", ".xlsx", ".xlsm"):
            os.startfile(file_path)
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
            print_inspection_file(target_id)
            return success_response(message="印刷を開始しました")
        except InspectionTarget.DoesNotExist:
            return error_response(
                "NOT_FOUND",
                "検査対象が見つかりません",
                status=status.HTTP_404_NOT_FOUND,
            )
        except FileNotFoundError as exc:
            return error_response(
                "FILE_NOT_FOUND",
                str(exc),
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError as exc:
            return error_response("INVALID_REQUEST", str(exc))
        except Exception as exc:
            return error_response(
                "PRINT_FAILED", str(exc), status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BulkHideTargetsView(APIView):
    def post(self, request):
        serializer = BulkHideTargetsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        date = serializer.validated_data["date"]
        session = InspectionSession.objects.filter(target_date=date).first()
        if session is None:
            return success_response(hidden_count=0)
        ids = serializer.validated_data["target_ids"]
        hidden = InspectionTarget.objects.filter(session=session, id__in=ids).update(visible=False)
        return success_response(hidden_count=hidden)


class BulkHistoryView(APIView):
    def post(self, request):
        serializer = BulkHistoryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated_count = bulk_upsert_history(
                serializer.validated_data["date"],
                serializer.validated_data["items"],
            )
        except ValueError as exc:
            return error_response("UNKNOWN_CODE", str(exc))
        return success_response(updated_count=updated_count)


class SingleHistoryView(APIView):
    def patch(self, request):
        serializer = SingleHistoryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            set_check(
                serializer.validated_data["date"],
                serializer.validated_data["code"],
                serializer.validated_data["time"],
                serializer.validated_data["checked"],
            )
        except ValueError as exc:
            return error_response("UNKNOWN_CODE", str(exc))
        return success_response()

    def get(self, request):
        target_date = request.query_params.get("date")
        if not target_date:
            return error_response("INVALID_REQUEST", "date query parameter is required.")

        rows = (
            History.objects.filter(date=target_date)
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
            written_count = write_history_to_excel(target_date)
        except FileNotFoundError as exc:
            return error_response("FILE_NOT_FOUND", str(exc), status.HTTP_404_NOT_FOUND)
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
            session = InspectionSession.objects.filter(target_date=target_date).first()
            if session:
                targets = InspectionTarget.objects.filter(session=session, visible=True).select_related("master")
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
                "image_url": layout.background_image_path or "",
                "layout": serialize_layout(layout),
                "machines": machines,
                "warnings": warnings,
            }
        )


class FactoryMapLayoutView(APIView):
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

        layout.background_image_path = data["background_image_path"]
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
        layout = LayoutMaster.objects.create(layout_name=name)
        return Response(LayoutMasterListSerializer(layout).data, status=status.HTTP_201_CREATED)


class UploadBackgroundImageView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file = request.FILES.get("image")
        if not file:
            return error_response("NO_FILE", "画像ファイルが指定されていません。")
        ext = os.path.splitext(file.name)[1] or ".png"
        filename = f"bg_{uuid.uuid4().hex}{ext}"
        subdir = "uploads"
        upload_dir = settings.MEDIA_ROOT / subdir
        upload_dir.mkdir(parents=True, exist_ok=True)
        filepath = upload_dir / filename
        with open(filepath, "wb") as f:
            for chunk in file.chunks():
                f.write(chunk)
        url = f"{settings.MEDIA_URL}{subdir}/{filename}"
        return Response({"url": url, "filename": filename})


class MachineListView(APIView):
    def get(self, request):
        machines = Machine.objects.filter(is_active=True).order_by("machine_no")
        serializer = MachineSerializer(machines, many=True)
        return Response(serializer.data)


class MachineMasterView(APIView):
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

        if data.get("id"):
            machine = get_object_or_404(Machine, id=data["id"])
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
                sync_master_class_from_assignment(master)

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
        job = create_job(Job.JobType.INSPECTION_SHEET_ISSUE, request.data)
        try:
            run_job(job, lambda: issue_inspection_sheets(target_date=target_date))
        except FileNotFoundError as exc:
            return error_response("FILE_NOT_FOUND", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
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
        )

        try:
            run_job(job, lambda: generate_daily_report(target_date))
        except FileNotFoundError as exc:
            return error_response("FILE_NOT_FOUND", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
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
        )

        try:
            run_job(job, lambda: issue_daily_report(target_date))
        except FileNotFoundError as exc:
            return error_response("FILE_NOT_FOUND", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
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


class SeedMasterView(APIView):
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
