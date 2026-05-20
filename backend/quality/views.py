from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import History, InspectionSession, InspectionTarget, Job, Master
from .serializers import (
    BulkHistoryRequestSerializer,
    DailyReportGenerateRequestSerializer,
    InspectionTargetSerializer,
    JobSerializer,
    ManualTargetsRequestSerializer,
    SingleHistoryRequestSerializer,
)
from .services import (
    add_manual_targets,
    bulk_upsert_history,
    create_job,
    generate_daily_report,
    history_map_for_date,
    run_job,
    set_check,
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


class JobDetailView(APIView):
    def get(self, request, job_id):
        job = get_object_or_404(Job, job_id=job_id)
        return Response(JobSerializer(job).data)


class MasterUpdateView(APIView):
    def post(self, request):
        job = create_job(Job.JobType.MASTER_UPDATE, request.data)
        job.status = Job.Status.QUEUED
        job.save(update_fields=["status"])
        return Response({"status": "accepted", "job_id": job.job_id}, status=status.HTTP_202_ACCEPTED)


class PlansImportView(APIView):
    def post(self, request):
        if not request.FILES.get("scan_file") and not request.FILES.get("excel_file"):
            return error_response(
                "INVALID_REQUEST",
                "scan_file or excel_file is required.",
            )
        job = create_job(
            Job.JobType.PLANS_IMPORT,
            {"target_date": request.data.get("target_date")},
        )
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
            InspectionTarget.objects.filter(session=session)
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
        target.delete()
        return success_response()


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


class FactoryMapView(APIView):
    def get(self, request):
        return Response(
            {
                "image_url": "/media/maps/factory.png",
                "machines": [],
                "warnings": [],
            }
        )


class InspectionSheetIssueView(APIView):
    def post(self, request):
        job = create_job(Job.JobType.INSPECTION_SHEET_ISSUE, request.data)
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
                    "department": item.get("department", ""),
                    "updated_at": timezone.now(),
                },
            )
            updated_count += 1

        return success_response(updated_count=updated_count)
