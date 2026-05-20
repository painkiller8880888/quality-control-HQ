from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from .constants import CHECK_SLOTS
from .models import (
    History,
    InspectionSession,
    InspectionTarget,
    InspectionTargetWarning,
    Job,
    Master,
)


def normalize_code(code):
    return str(code).strip().upper()


def inspection_sheet_required(master):
    return master is not None and master.category in (1, 6)


@transaction.atomic
def add_manual_targets(target_date, codes):
    session, _ = InspectionSession.objects.get_or_create(target_date=target_date)
    added_count = 0

    for raw_code in codes:
        normalized_code = normalize_code(raw_code)
        master = Master.objects.filter(code=normalized_code).first()
        target, created = InspectionTarget.objects.get_or_create(
            session=session,
            normalized_code=normalized_code,
            defaults={
                "master": master,
                "raw_code": raw_code,
                "source_manual": True,
                "requires_inspection_sheet": inspection_sheet_required(master),
                "issue_status": (
                    InspectionTarget.IssueStatus.PENDING
                    if inspection_sheet_required(master)
                    else InspectionTarget.IssueStatus.NOT_REQUIRED
                ),
            },
        )

        if not created:
            target.source_manual = True
            if master and not target.master:
                target.master = master
            target.requires_inspection_sheet = inspection_sheet_required(target.master)
            if target.requires_inspection_sheet and target.issue_status == InspectionTarget.IssueStatus.NOT_REQUIRED:
                target.issue_status = InspectionTarget.IssueStatus.PENDING
            target.save(
                update_fields=[
                    "source_manual",
                    "master",
                    "requires_inspection_sheet",
                    "issue_status",
                    "updated_at",
                ]
            )
        else:
            added_count += 1

        if master is None:
            InspectionTargetWarning.objects.get_or_create(
                target=target,
                error_code="UNKNOWN_CODE",
                defaults={
                    "message": f"Unknown code: {normalized_code}",
                    "details": {"code": normalized_code},
                },
            )

    return session, added_count


def history_map_for_date(target_date):
    rows = History.objects.filter(date=target_date).values_list("master_id", "time_slot")
    history_map = {}
    for master_id, time_slot in rows:
        history_map.setdefault(master_id, set()).add(time_slot)
    return history_map


@transaction.atomic
def set_check(target_date, code, time_slot, checked):
    normalized_code = normalize_code(code)
    master = Master.objects.filter(code=normalized_code).first()
    if master is None:
        raise ValueError(f"Unknown code: {normalized_code}")

    if checked:
        History.objects.update_or_create(
            date=target_date,
            master=master,
            time_slot=time_slot,
            defaults={},
        )
    else:
        History.objects.filter(date=target_date, master=master, time_slot=time_slot).delete()


@transaction.atomic
def bulk_upsert_history(target_date, items):
    updated = 0
    for item in items:
        for slot, checked in item["checks"].items():
            set_check(target_date, item["code"], slot, checked)
        updated += 1
    return updated


def create_job(job_type, payload):
    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    return Job.objects.create(
        job_id=f"job_{timestamp}_{uuid4().hex[:8]}",
        job_type=job_type,
        request_payload=payload,
    )


def run_job(job, fn):
    job.status = Job.Status.RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])
    try:
        result = fn()
    except Exception as exc:
        job.status = Job.Status.FAILED
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at"])
        raise

    job.status = Job.Status.SUCCEEDED
    job.result = result
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "result", "finished_at"])
    return result


def generate_daily_report(target_date):
    template_path = Path(settings.DAILY_REPORT_TEMPLATE)
    if not template_path.exists():
        raise FileNotFoundError(f"Daily report template not found: {template_path}")

    output_dir = Path(settings.DAILY_REPORT_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{target_date}.xlsm"

    workbook = load_workbook(template_path, keep_vba=True)
    sheet = workbook["日報"] if "日報" in workbook.sheetnames else workbook.active

    slot_columns = {"A": "C", "B": "F", "C": "I", "D": "L"}
    category_start_rows = {
        2: 4,
        3: 4,
        6: 18,
        7: 22,
        1: 26,
    }
    row_offsets = {slot: {category: 0 for category in category_start_rows} for slot in CHECK_SLOTS}
    category_45_counts = {slot: 0 for slot in CHECK_SLOTS}

    histories = (
        History.objects.filter(date=target_date)
        .select_related("master")
        .order_by("time_slot", "master__category", "master__code")
    )

    for history in histories:
        slot = history.time_slot
        category = history.master.category
        column = slot_columns[slot]

        if category in (4, 5):
            category_45_counts[slot] += 1
            continue

        start_row = category_start_rows.get(category)
        if start_row is None:
            continue

        row = start_row + row_offsets[slot][category]
        sheet[f"{column}{row}"] = history.master.name
        row_offsets[slot][category] += 1

    for slot, count in category_45_counts.items():
        sheet[f"{slot_columns[slot]}38"] = count

    workbook.save(output_path)
    return {
        "date": str(target_date),
        "excel_path": str(output_path),
    }
