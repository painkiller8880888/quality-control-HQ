import csv
import logging
import re
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone
import fitz
from openpyxl import load_workbook
from pypdf import PdfReader
from rapidocr_onnxruntime import RapidOCR
import xlrd

from .constants import CHECK_SLOTS
from .models import (
    History,
    InspectionSession,
    InspectionTarget,
    InspectionTargetWarning,
    Job,
    Master,
)


CODE_PATTERN = re.compile(r"\b[A-Za-z]{3}\d{4}\b")
ALNUM_PATTERN = re.compile(r"[A-Za-z0-9]")
logger = logging.getLogger(__name__)
_OCR_ENGINE = None


def normalize_code(code):
    return str(code).strip().upper()


def inspection_sheet_required(master):
    return master is not None and master.category in (1, 6, 7)


def get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


@transaction.atomic
def upsert_targets(target_date, codes, source):
    session, _ = InspectionSession.objects.get_or_create(target_date=target_date)
    added_count = 0
    duplicate_count = 0

    for raw_code in codes:
        normalized_code = normalize_code(raw_code)
        if not normalized_code:
            continue
        master = Master.objects.filter(code=normalized_code).first()
        target, created = InspectionTarget.objects.get_or_create(
            session=session,
            normalized_code=normalized_code,
            defaults={
                "master": master,
                "raw_code": raw_code,
                "source_ocr": source == "ocr",
                "source_excel": source == "excel",
                "source_manual": source == "manual",
                "requires_inspection_sheet": inspection_sheet_required(master),
                "issue_status": (
                    InspectionTarget.IssueStatus.PENDING
                    if inspection_sheet_required(master)
                    else InspectionTarget.IssueStatus.NOT_REQUIRED
                ),
            },
        )

        if not created:
            duplicate_count += 1
            if source == "ocr":
                target.source_ocr = True
            elif source == "excel":
                target.source_excel = True
            elif source == "manual":
                target.source_manual = True
            if master and not target.master:
                target.master = master
            target.requires_inspection_sheet = inspection_sheet_required(target.master)
            if target.requires_inspection_sheet and target.issue_status == InspectionTarget.IssueStatus.NOT_REQUIRED:
                target.issue_status = InspectionTarget.IssueStatus.PENDING
            target.save(
                update_fields=[
                    "source_manual",
                    "source_ocr",
                    "source_excel",
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

    return session, added_count, duplicate_count


def add_manual_targets(target_date, codes):
    session, added_count, _ = upsert_targets(target_date, codes, "manual")
    return session, added_count


def extract_codes_from_text(text):
    return [normalize_code(match.group(0)) for match in CODE_PATTERN.finditer(text or "")]


def find_code_candidates(text):
    return [normalize_code(match.group(0)) for match in CODE_PATTERN.finditer(text or "")]


def extract_codes_from_uploaded_text(uploaded_file):
    raw = uploaded_file.read()
    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return find_code_candidates(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    return find_code_candidates(raw.decode("utf-8", errors="ignore"))


def press_plan_candidates(target_date):
    base_dir = Path(settings.PRESS_PLAN_DIR)
    candidates = []
    for suffix in ("xls", "xlsx", "xlsm"):
        candidates.append(base_dir / f"{target_date.year}.{target_date.month}.{target_date.day:02d}.{suffix}")
        candidates.append(base_dir / f"{target_date.year}.{target_date.month}.{target_date.day}.{suffix}")
    return candidates


def find_press_plan_file(target_date):
    candidates = press_plan_candidates(target_date)
    test_input_dir = Path(settings.TEST_INPUT_DIR)
    for candidate in list(candidates):
        candidates.append(test_input_dir / candidate.name)

    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


def extract_codes_from_plan_excel(path_or_file, file_name=None):
    name = file_name or str(path_or_file)
    suffix = Path(name).suffix.lower()
    if suffix == ".xls":
        if hasattr(path_or_file, "read"):
            workbook = xlrd.open_workbook(file_contents=path_or_file.read())
        else:
            workbook = xlrd.open_workbook(str(path_or_file))
        worksheet = workbook.sheet_by_name("雛形")
        values = []
        for row_index in range(4, worksheet.nrows):
            values.append(worksheet.cell_value(row_index, 6))
    else:
        workbook = load_workbook(path_or_file, read_only=True, data_only=True)
        worksheet = workbook["雛形"]
        values = [worksheet.cell(row=row, column=7).value for row in range(5, worksheet.max_row + 1)]

    codes = []
    for value in values:
        if value is None:
            continue
        codes.extend(find_code_candidates(str(value)))
    return codes


def extract_codes_and_match_failures_from_pdf(scan_file):
    temp_dir = Path(settings.TEST_INPUT_DIR)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_pdf_path = temp_dir / f"ocr_{uuid4().hex}.pdf"
    temp_pdf_path.write_bytes(scan_file.read())

    embedded_text = ""
    try:
        reader = PdfReader(str(temp_pdf_path))
        embedded_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        logger.warning("Embedded PDF text extraction failed: %s", exc)

    if embedded_text.strip():
        codes = find_code_candidates(embedded_text)
        match_failed_count = 0 if codes else 1
        temp_pdf_path.unlink(missing_ok=True)
        return {
            "codes": codes,
            "match_failed_count": match_failed_count,
            "page_count": len(reader.pages),
            "mode": "embedded_text",
        }

    pdf = fitz.open(str(temp_pdf_path))
    page_texts = []
    for page_index in range(pdf.page_count):
        pixmap = pdf[page_index].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
        image_path = temp_dir / f"{temp_pdf_path.stem}_page_{page_index + 1}.png"
        pixmap.save(str(image_path))
        result, _ = get_ocr_engine()(str(image_path))
        lines = [line[1] for line in result] if result else []
        page_texts.append("\n".join(lines))
        image_path.unlink(missing_ok=True)

    pdf.close()
    temp_pdf_path.unlink(missing_ok=True)

    codes = []
    match_failed_count = 0
    for text in page_texts:
        page_codes = find_code_candidates(text)
        codes.extend(page_codes)
        if not page_codes and ALNUM_PATTERN.search(text or ""):
            match_failed_count += 1

    return {
        "codes": codes,
        "match_failed_count": match_failed_count,
        "page_count": len(page_texts),
        "mode": "ocr",
    }


def load_master_rows_from_csv(path_or_file):
    if hasattr(path_or_file, "read"):
        raw = path_or_file.read()
        text = raw.decode("cp932", errors="replace")
    else:
        text = Path(path_or_file).read_text(encoding="cp932", errors="replace")

    rows = []
    reader = csv.reader(text.splitlines())
    header = next(reader, None)
    for row in reader:
        if len(row) < 17:
            continue
        code = normalize_code(row[9])
        name = str(row[10]).strip()
        department = str(row[16]).strip()
        if not code or not name:
            continue
        rows.append(
            {
                "code": code,
                "name": name,
                "department": department,
            }
        )
    return rows


@transaction.atomic
def import_master_csv(master_file=None):
    if master_file:
        rows = load_master_rows_from_csv(master_file)
        source = getattr(master_file, "name", "uploaded")
    else:
        source_path = Path(settings.TEST_INPUT_DIR) / "master.csv"
        rows = load_master_rows_from_csv(source_path)
        source = str(source_path)

    updated_count = 0
    for row in rows:
        Master.objects.update_or_create(
            code=row["code"],
            defaults={
                "name": row["name"],
                "node_type": None,
                "department": row["department"],
                "category": None,
            },
        )
        updated_count += 1

    return {
        "updated_master_count": updated_count,
        "source": source,
    }


@transaction.atomic
def import_plan_targets(target_date, scan_file=None, excel_file=None):
    sources = []
    missing_plan_file = False
    warning_summary = {
        "UNKNOWN_CODE": 0,
        "DUPLICATE_TARGET": 0,
        "MATCH_FAILED": 0,
    }

    if scan_file:
        scan_name = getattr(scan_file, "name", "").lower()
        if scan_name.endswith(".pdf"):
            ocr_result = extract_codes_and_match_failures_from_pdf(scan_file)
            ocr_codes = ocr_result["codes"]
            warning_summary["MATCH_FAILED"] += ocr_result["match_failed_count"]
            source_details = {
                "source": "ocr",
                "read_count": len(ocr_codes),
                "match_failed_count": ocr_result["match_failed_count"],
                "page_count": ocr_result["page_count"],
                "mode": ocr_result["mode"],
            }
        else:
            ocr_codes = extract_codes_from_uploaded_text(scan_file)
            source_details = {
                "source": "ocr",
                "read_count": len(ocr_codes),
                "match_failed_count": 0,
                "mode": "text",
            }

        _, added_count, duplicate_count = upsert_targets(target_date, ocr_codes, "ocr")
        warning_summary["DUPLICATE_TARGET"] += duplicate_count
        sources.append(
            {
                "added_count": added_count,
                "duplicate_count": duplicate_count,
                **source_details,
            }
        )

    if excel_file:
        excel_codes = extract_codes_from_plan_excel(excel_file, excel_file.name)
        _, added_count, duplicate_count = upsert_targets(target_date, excel_codes, "excel")
        warning_summary["DUPLICATE_TARGET"] += duplicate_count
        sources.append(
            {
                "source": "excel",
                "read_count": len(excel_codes),
                "added_count": added_count,
                "duplicate_count": duplicate_count,
            }
        )
    else:
        default_plan = find_press_plan_file(target_date)
        if default_plan:
            excel_codes = extract_codes_from_plan_excel(default_plan)
            _, added_count, duplicate_count = upsert_targets(target_date, excel_codes, "excel")
            warning_summary["DUPLICATE_TARGET"] += duplicate_count
            sources.append(
                {
                    "source": "excel",
                    "path": str(default_plan),
                    "read_count": len(excel_codes),
                    "added_count": added_count,
                    "duplicate_count": duplicate_count,
                }
            )
        else:
            missing_plan_file = True

    session, _ = InspectionSession.objects.get_or_create(target_date=target_date)
    warning_count = InspectionTargetWarning.objects.filter(target__session=session).count()
    warning_summary["UNKNOWN_CODE"] = warning_count
    imported_count = InspectionTarget.objects.filter(session=session).count()
    result = {
        "target_date": str(target_date),
        "session_id": session.id,
        "imported_count": imported_count,
        "warning_count": warning_count,
        "warning_summary": warning_summary,
        "sources": sources,
    }
    if missing_plan_file:
        result["missing_plan_file"] = True
    return result


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
