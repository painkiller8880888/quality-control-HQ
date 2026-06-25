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
    ClassMaster,
    History,
    InspectionFile,
    InspectionSession,
    InspectionTarget,
    InspectionTargetWarning,
    Job,
    Master,
    MasterClass,
    Structure,
)


CODE_PATTERN = re.compile(r"\b[A-Za-z]{3}\d{4}\b")
FILE_CODE_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2,4}\d{4}(?![A-Za-z0-9])")
ALNUM_PATTERN = re.compile(r"[A-Za-z0-9]")
logger = logging.getLogger(__name__)
_OCR_ENGINE = None


def normalize_code(code):
    return str(code).strip().upper()


def inspection_sheet_required(master):
    if master is None:
        return False
    mc = MasterClass.objects.filter(master=master).first()
    return mc is not None and mc.class_master is not None and mc.class_master.class_no in (1, 6, 7)


# PRODUCT.md classification table
# (prefix, node_type_1, node_type_2, category)
PRODUCT_CLASSIFICATION = [
    ("BA", "", "", "スライド丁番"),
    ("BB", "", "", "丁番"),
    ("BC", "", "", "戸車"),
    ("BD", "", "", "吊り車"),
    ("BE", "", "", "キャッチ"),
    ("BF", "", "", "取手・つまみ・引き手"),
    ("BG", "", "", "手摺り"),
    ("BH", "", "", "レール"),
    ("BI", "", "", "カーテン・ブラインド金物"),
    ("BJ", "", "", ""),
    ("BK", "", "", "意匠系金物"),
    ("BL", "", "", "機能金物"),
    ("BM", "", "", "固定金物"),
    ("BN", "", "", "諸金物（その他）"),
    ("BO", "", "", "付属金物"),
    ("BP", "", "", "部品類"),
    ("BQ", "", "", ""),
    ("BR", "", "", ""),
    ("BS", "", "", ""),
    ("BT", "", "", "ラック"),
    ("BU", "", "", "POP"),
    ("BV", "", "", ""),
    ("BW", "", "", ""),
    ("BX", "", "", ""),
    ("BY", "", "", "提案品"),
    ("BZ", "", "", "その他製品"),
    ("CAA", "プレス", "", "スライド丁番"),
    ("CAD", "加工", "焼入れ", "スライド丁番"),
    ("CAE", "加工", "バレル", "スライド丁番"),
    ("CAG", "鍍金", "", "スライド丁番"),
    ("CAH", "塗装", "", "スライド丁番"),
    ("CAI", "組立", "", "スライド丁番"),
    ("CAK", "加工", "カシメ", "スライド丁番"),
    ("CAL", "加工", "タッピング", "スライド丁番"),
    ("CAM", "組立", "バネ入れ", "スライド丁番"),
    ("CAP", "組立", "自動機", "スライド丁番"),
    ("CAR", "袋入", "", "スライド丁番"),
    ("CAS", "梱包", "", "スライド丁番"),
    ("CAZ", "加工", "その他", "スライド丁番"),
    ("CBA", "プレス", "", "丁番"),
    ("CBB", "加工", "切断", "丁番"),
    ("CBC", "加工", "溶接", "丁番"),
    ("CBD", "加工", "焼入れ", "丁番"),
    ("CBE", "加工", "バレル", "丁番"),
    ("CBF", "加工", "皿もみ", "丁番"),
    ("CBG", "鍍金", "", "丁番"),
    ("CBH", "塗装", "", "丁番"),
    ("CBI", "組立", "", "丁番"),
    ("CBJ", "加工", "圧入", "丁番"),
    ("CBK", "加工", "カシメ", "丁番"),
    ("CBL", "加工", "タップ", "丁番"),
    ("CBO", "プレス", "ダボ出し", "丁番"),
    ("CBP", "組立", "自動機", "丁番"),
    ("CBQ", "検査", "", "丁番"),
    ("CBR", "袋入", "", "丁番"),
    ("CBS", "梱包", "", "丁番"),
    ("CBZ", "加工", "その他", "丁番"),
    ("CCA", "プレス", "", "戸車"),
    ("CCG", "鍍金", "", "戸車"),
    ("CCH", "塗装", "", "戸車"),
    ("CCI", "組立", "", "戸車"),
    ("CCK", "加工", "カシメ", "戸車"),
    ("CCL", "加工", "タップ", "戸車"),
    ("CCP", "組立", "自動機", "戸車"),
    ("CCS", "梱包", "", "戸車"),
    ("CCZ", "加工", "その他", "戸車"),
    ("CDA", "プレス", "", "吊車"),
    ("CDB", "加工", "切削", "吊車"),
    ("CDC", "加工", "溶接", "和金具"),
    ("CDD", "加工", "焼入れ", "吊車"),
    ("CDE", "加工", "研磨", "和金具"),
    ("CDF", "加工", "皿もみ", "吊車"),
    ("CDG", "鍍金", "", "吊車"),
    ("CDH", "塗装", "", "吊車"),
    ("CDI", "組立", "", "吊車"),
    ("CDJ", "加工", "圧入", "吊車"),
    ("CDK", "加工", "カシメ", "吊車"),
    ("CDL", "加工", "タップ", "吊車"),
    ("CDN", "加工", "油付け", "吊車"),
    ("CDP", "組立", "自動機", "吊車"),
    ("CDQ", "検査", "", "吊車"),
    ("CDR", "袋入", "", "吊車"),
    ("DCS", "梱包", "", "吊車"),
    ("CDZ", "加工", "その他", "吊車"),
    ("CEA", "プレス", "", "キャッチ"),
    ("CEG", "鍍金", "", "キャッチ"),
    ("CEI", "組立", "", "キャッチ"),
    ("CEL", "加工", "タップ", "キャッチ"),
    ("CER", "袋入", "", "キャッチ"),
    ("CES", "梱包", "", "キャッチ"),
    ("CEZ", "加工", "その他", "キャッチ"),
    ("CFA", "プレス", "", "取手/つまみ/引手"),
    ("CFB", "加工", "切断", "取手/つまみ/引手"),
    ("CFE", "加工", "研磨", "取手/つまみ/引手"),
    ("CFG", "鍍金", "", "取手/つまみ/引手"),
    ("CFH", "塗装", "", "取手/つまみ/引手"),
    ("CFI", "組立", "", "取手/つまみ/引手"),
    ("CFK", "加工", "カシメ", "取手/つまみ/引手"),
    ("CFL", "加工", "タップ", "取手/つまみ/引手"),
    ("CFR", "袋入", "", "取手/つまみ/引手"),
    ("CFS", "梱包", "", "取手/つまみ/引手"),
    ("CFZ", "加工", "その他", "取手/つまみ/引手"),
    ("CGA", "プレス", "", "手摺"),
    ("CGE", "加工", "研磨", "手摺"),
    ("CGF", "加工", "皿もみ", "手摺"),
    ("CGG", "鍍金", "", "手摺"),
    ("CGH", "塗装", "", "手摺"),
    ("CGI", "組立", "", "手摺"),
    ("CGK", "加工", "カシメ", "手摺"),
    ("CGL", "加工", "タップ", "手摺"),
    ("CGQ", "検査", "", "手摺"),
    ("CGR", "袋入", "", "手摺"),
    ("CGS", "梱包", "", "手摺"),
    ("CGZ", "加工", "その他", "手摺"),
    ("CHS", "梱包", "", "レール"),
    ("CIA", "プレス", "", "カーテン/ブラインド金物"),
    ("CIG", "鍍金", "", "カーテン/ブラインド金物"),
    ("CII", "組立", "", "カーテン/ブラインド金物"),
    ("CIS", "梱包", "", "カーテン/ブラインド金物"),
    ("CKS", "梱包", "", "意匠系金物"),
    ("CLA", "プレス", "", "機能金物"),
    ("CLB", "加工", "切断", "機能金物"),
    ("CLC", "加工", "溶接", "機能金物"),
    ("CLE", "加工", "研磨", "機能金物"),
    ("CLF", "加工", "皿もみ", "機能金物"),
    ("CLG", "鍍金", "", "機能金物"),
    ("CLH", "塗装", "", "機能金物"),
    ("CLI", "組立", "", "機能金物"),
    ("CLK", "加工", "カシメ", "機能金物"),
    ("CLL", "加工", "タップ", "機能金物"),
    ("CLS", "梱包", "", "機能金物"),
    ("CLZ", "加工", "その他", "機能金物"),
    ("CMA", "プレス", "", "固定金物"),
    ("CMC", "加工", "溶接", "固定金物"),
    ("CME", "加工", "研磨", "固定金物"),
    ("CMG", "鍍金", "", "固定金物"),
    ("CMH", "塗装", "", "固定金物"),
    ("CMI", "組立", "", "固定金物"),
    ("CMK", "加工", "カシメ", "固定金物"),
    ("CML", "加工", "タッピング", "固定金物"),
    ("CMQ", "検査", "", "固定金物"),
    ("CMR", "袋入", "", "固定金物"),
    ("CMS", "梱包", "", "固定金物"),
    ("CNA", "プレス", "", "諸金物"),
    ("CNB", "加工", "切断", "諸金物"),
    ("CNC", "加工", "溶接", "諸金物"),
    ("CNE", "加工", "研磨", "諸金物"),
    ("CNF", "加工", "皿もみ", "諸金物"),
    ("CNG", "鍍金", "", "諸金物"),
    ("CNH", "塗装", "", "諸金物"),
    ("CNI", "組立", "", "諸金物"),
    ("CNK", "加工", "カシメ", "諸金物"),
    ("CNL", "加工", "タップ", "諸金物"),
    ("CNS", "梱包", "", "諸金物"),
    ("CNZ", "加工", "その他", "諸金物"),
    ("COA", "プレス", "", "付属金物"),
    ("COB", "加工", "切断", "付属金物"),
    ("COC", "加工", "溶接", "付属金物"),
    ("COD", "加工", "焼入れ", "付属金物"),
    ("COE", "加工", "研磨", "付属金物"),
    ("COF", "加工", "皿もみ", "付属金物"),
    ("COG", "鍍金", "", "付属金物"),
    ("COH", "塗装", "", "付属金物"),
    ("COI", "組立", "", "付属金物"),
    ("COK", "加工", "カシメ", "付属金物"),
    ("COL", "加工", "タップ", "付属金物"),
    ("COR", "袋入", "", "付属金物"),
    ("COS", "梱包", "", "付属金物"),
    ("COZ", "加工", "その他", "付属金物"),
    ("CPA", "プレス", "", "部品類"),
    ("CPB", "加工", "切断", "部品類"),
    ("CPD", "加工", "焼入れ", "部品類"),
    ("CPG", "鍍金", "", "部品類"),
    ("CPH", "塗装", "", "部品類"),
    ("CPR", "袋入", "", "部品類"),
    ("CPS", "梱包", "", "部品類"),
    ("CPZ", "加工", "その他", "部品類"),
    ("CT", "", "", "ラック"),
    ("CTH", "塗装", "", "ラック"),
    ("CTS", "梱包", "", "ラック"),
    ("CTZ", "加工", "その他", "ラック"),
    ("CU", "", "", "POP"),
    ("CUS", "梱包", "", "POP"),
    ("CYA", "プレス", "", "提案品"),
    ("CY", "", "", "提案品"),
    ("CYE", "加工", "研磨", "提案品"),
    ("CYG", "鍍金", "", "提案品"),
    ("CYI", "組立", "", "提案品"),
    ("CYS", "梱包", "", "提案品"),
    ("CZ", "", "", "その他製品"),
    ("CZA", "プレス", "", "その他製品"),
    ("CZB", "加工", "切断", "その他製品"),
    ("CZC", "加工", "溶接", "その他製品"),
    ("CZE", "加工", "研磨", "その他製品"),
    ("CZG", "鍍金", "", "その他製品"),
    ("CZH", "塗装", "", "その他製品"),
    ("CZI", "組立", "", "その他製品"),
    ("CZK", "加工", "カシメ", "その他製品"),
    ("CZL", "加工", "タップ", "その他製品"),
    ("CZR", "袋入", "", "その他製品"),
    ("CZS", "梱包", "", "その他製品"),
    ("CZZ", "加工", "その他", "その他製品"),
    ("DA", "ダイカスト", "", ""),
    ("DAF", "塗装", "", ""),
    ("DAG", "鍍金", "", ""),
    ("DAH", "塗装", "", ""),
    ("DAZ", "加工", "その他", ""),
    ("DB", "樹脂", "", ""),
    ("DBB", "加工", "切断", ""),
    ("DBL", "加工", "タップ", ""),
    ("DBS", "梱包", "", ""),
    ("DBT", "樹脂", "", ""),
    ("DBZ", "加工", "その他", ""),
    ("DC", "ネジ", "", ""),
    ("DCZ", "ネジ", "", ""),
    ("DD", "バネ", "", ""),
    ("DE", "ワッシャー", "", ""),
    ("DF", "ピン", "", ""),
    ("DFG", "鍍金", "", ""),
    ("DG", "ベアリング", "", ""),
    ("DGZ", "加工", "その他", ""),
    ("DH", "鋼球", "", ""),
    ("DI", "磁石", "", ""),
    ("DJ", "ヘッダー", "", ""),
    ("DJG", "ヘッダー", "", ""),
    ("DJZ", "加工", "その他", ""),
    ("DK", "プレス", "", ""),
    ("DKG", "鍍金", "", ""),
    ("DKH", "塗装", "", ""),
    ("DKZ", "加工", "その他", ""),
    ("DL", "丁番用軸", "", ""),
    ("DN", "鋳造", "", ""),
    ("DZ", "その他", "", ""),
    ("DZF", "加工", "皿もみ", ""),
    ("DZG", "鍍金", "", ""),
    ("EA", "材料", "鉄", ""),
    ("EB", "材料", "ステンレス", ""),
    ("EC", "材料", "アルミ", ""),
    ("ED", "材料", "真鍮", ""),
    ("EZ", "材料", "青銅", ""),
    ("FA", "ダイカスト", "", ""),
    ("FAA", "加工", "切断", ""),
    ("FAE", "加工", "研磨", ""),
    ("FAF", "加工", "その他", ""),
    ("FAG", "鍍金", "", ""),
    ("FAL", "加工", "その他", ""),
    ("FAZ", "加工", "その他", ""),
    ("FB", "樹脂", "", ""),
    ("FC", "ネジ", "", ""),
    ("FF", "ピン", "", ""),
    ("FFG", "鍍金", "", ""),
    ("FFK", "加工", "カシメ", ""),
    ("FG", "ベアリング", "", ""),
    ("FJ", "ヘッダー", "", ""),
    ("FJZ", "加工", "その他", ""),
    ("FK", "プレス", "", ""),
    ("FKA", "プレス", "", ""),
    ("FKK", "加工", "皿もみ", ""),
    ("FKG", "鍍金", "", ""),
    ("FKI", "組立", "", ""),
    ("FZ", "プレス", "", ""),
    ("IZS", "梱包", "", ""),
    ("IZZ", "その他", "ピン", ""),
    ("JA", "その他", "", ""),
    ("JB", "樹脂", "", ""),
    ("JC", "ネジ", "", ""),
    ("JE", "FA-160-KY部品", "", ""),
    ("JF", "FA-160-KY部品", "", ""),
    ("JI", "マグネット", "", ""),
    ("JK", "鍍金", "", ""),
    ("JZ", "その他", "", ""),
    ("KZ", "その他", "", ""),
    ("NA", "支給品", "", ""),
    ("NF", "支給品", "", ""),
    ("NZ", "支給品", "", ""),
    ("PA", "梱包用ビニール袋", "", ""),
    ("PB", "梱包用小箱", "", ""),
    ("PC", "梱包用段ボール", "", ""),
    ("PZ", "その他", "", ""),
    ("SB", "その他", "", ""),
    ("SC", "その他", "", ""),
    ("SD", "その他", "", ""),
    ("SL", "その他", "", ""),
    ("YC", "ビニール袋", "", ""),
    ("YD", "小箱", "", ""),
    ("YE", "段ボール", "", ""),
    ("YZ", "その他", "", ""),
]

# Sort by prefix length descending for longest-match
PRODUCT_CLASSIFICATION_SORTED = sorted(PRODUCT_CLASSIFICATION, key=lambda x: len(x[0]), reverse=True)


def classify_master_by_product_code(code):
    for prefix, n1, n2, cat in PRODUCT_CLASSIFICATION_SORTED:
        if code.startswith(prefix):
            return {"node_type_1": n1, "node_type_2": n2, "category": cat}
    return {"node_type_1": "", "node_type_2": "", "category": ""}


def determine_inspection_class(master, file_codes_by_code):
    if master is None:
        return None
    code = master.code
    n1 = (master.node_type_1 or "").strip()
    dept = (master.department or "").strip()

    file_infos = file_codes_by_code.get(code, [])
    folder_classes = set()
    for fi in file_infos:
        fc = classify_folder(fi["file_path"])
        if fc:
            folder_classes.add(fc)

    if "auto1" in folder_classes:
        return 1
    if "auto2" in folder_classes and "auto1" not in folder_classes:
        return 2
    if "setter" in folder_classes:
        return 3
    if "product1" in folder_classes:
        return 6
    if "product2" in folder_classes:
        return 7

    if n1 == "プレス":
        return 4
    if n1 == "加工" and (dept == "製造管理部" or dept == "生残技術部"):
        return 5

    return 8


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


def _read_csv_text(path_or_file):
    if hasattr(path_or_file, "read"):
        raw = path_or_file.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp932", errors="replace")
    else:
        for enc in ("utf-8-sig", "cp932"):
            try:
                text = Path(path_or_file).read_text(encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            text = Path(path_or_file).read_text(encoding="cp932", errors="replace")
    return text


def load_master_rows_from_csv(path_or_file):
    text = _read_csv_text(path_or_file)
    rows = []
    reader = csv.reader(text.splitlines())
    header = next(reader, None)
    for row in reader:
        if len(row) < 17:
            continue
        code = normalize_code(row[9])
        name = str(row[10]).strip()
        department = str(row[16]).strip() if len(row) > 16 else ""
        root_code = normalize_code(row[1]) if len(row) > 1 else ""
        parent_code = normalize_code(row[8]) if len(row) > 8 else ""
        level_str = str(row[11]).strip() if len(row) > 11 else ""
        quantity_str = str(row[18]).strip() if len(row) > 18 else ""
        if not code or not name:
            continue
        try:
            level = int(level_str) if level_str else 0
        except ValueError:
            level = 0
        try:
            quantity = float(quantity_str) if quantity_str else 0
        except ValueError:
            quantity = 0
        rows.append(
            {
                "code": code,
                "name": name,
                "department": department,
                "root_code": root_code,
                "parent_code": parent_code,
                "level": level,
                "quantity": quantity,
            }
        )
    return rows


def setter_check(folders):
    return "setter" in folders


def product_inspection_1(folders):
    return "product1" in folders


def product_inspection_2(folders):
    return "product2" in folders


def scan_inspection_folders(folder_paths):
    file_map = {}
    warnings = []
    for path_str in folder_paths:
        path_str = path_str.strip()
        if not path_str:
            continue
        p = Path(path_str)
        if not p.exists() or not p.is_dir():
            warnings.append(f"Folder not found or inaccessible: {path_str}")
            continue
        for f in p.rglob("*"):
            if f.is_file():
                name = f.name
                matches = list(CODE_PATTERN.finditer(name.upper()))
                for m in matches:
                    code = normalize_code(m.group(0))
                    file_map.setdefault(code, []).append({
                        "file_name": name,
                        "file_path": str(f.resolve()),
                    })
    return file_map, warnings


def classify_folder(file_path):
    lower = file_path.lower()
    if "自動機" in lower and "工程内検査" in lower:
        return "auto1"
    if "巡回検査" in lower and "自動機" in lower:
        return "auto2"
    if "巡回検査" in lower and "セッター" in lower:
        return "setter"
    if "製品検査" in lower and "(1)" in lower:
        return "product1"
    if "製品検査" in lower and "(2)" in lower:
        return "product2"
    return None


def scan_and_classify_files(folder_paths):
    code_file_map = {}
    folder_warnings = []
    for path_str in folder_paths:
        path_str = path_str.strip()
        if not path_str:
            continue
        p = Path(path_str)
        if not p.exists() or not p.is_dir():
            folder_warnings.append(f"Folder not found or inaccessible: {path_str}")
            continue
        for f in p.rglob("*"):
            if f.is_file():
                name = f.name
                fpath = str(f.resolve())
                for m in FILE_CODE_PATTERN.finditer(name.upper()):
                    code = normalize_code(m.group(0))
                    code_file_map.setdefault(code, []).append({
                        "file_name": name,
                        "file_path": fpath,
                    })
    return code_file_map, folder_warnings


@transaction.atomic
def import_master_csv(master_file=None, csv_path=None, inspection_folder_paths=None):
    if master_file:
        rows = load_master_rows_from_csv(master_file)
        source = getattr(master_file, "name", "uploaded")
    elif csv_path:
        rows = load_master_rows_from_csv(csv_path)
        source = csv_path
    else:
        source_path = Path(settings.TEST_INPUT_DIR) / "master.csv"
        rows = load_master_rows_from_csv(source_path)
        source = str(source_path)

    folder_paths = inspection_folder_paths or []
    code_file_map, folder_warnings = scan_and_classify_files(folder_paths)

    processed_codes = set()
    master_count = 0
    class_count = 0
    structure_count = 0

    for row in rows:
        code = row["code"]
        if code in processed_codes:
            continue
        processed_codes.add(code)

        classification = classify_master_by_product_code(code)
        master, created = Master.objects.update_or_create(
            code=code,
            defaults={
                "name": row["name"],
                "node_type_1": classification["node_type_1"] or None,
                "node_type_2": classification["node_type_2"] or None,
                "product_category": classification["category"] or None,
                "department": row["department"],
            },
        )
        master_count += 1

        insp_class = determine_inspection_class(master, code_file_map)
        if insp_class is not None:
            cm = ClassMaster.objects.filter(class_no=insp_class).first()
            MasterClass.objects.update_or_create(
                master=master,
                defaults={"class_master": cm},
            )
            class_count += 1

    for row in rows:
        parent_code = row["parent_code"]
        child_code = row["code"]
        if not parent_code or not child_code:
            continue
        Structure.objects.update_or_create(
            parent_code=parent_code,
            child_code=child_code,
            defaults={
                "root_code": row["root_code"],
                "level": row["level"],
                "quantity": row["quantity"] if row["quantity"] != 0 else None,
            },
        )
        structure_count += 1

    InspectionFile.objects.all().delete()
    file_count = 0
    for code, file_infos in code_file_map.items():
        master = Master.objects.filter(code=code).first()
        if master is None:
            continue
        for fi in file_infos:
            InspectionFile.objects.create(
                master=master,
                file_name=fi["file_name"],
                file_path=fi["file_path"],
            )
            file_count += 1

    result = {
        "updated_master_count": master_count,
        "updated_class_count": class_count,
        "updated_structure_count": structure_count,
        "inspection_file_count": file_count,
        "source": source,
    }
    if folder_warnings:
        result["folder_warnings"] = folder_warnings
    return result


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
        .order_by("time_slot", "master__code")
    )

    master_ids = list(histories.values_list("master_id", flat=True).distinct())
    master_classes = {}
    for mc in MasterClass.objects.filter(master_id__in=master_ids).select_related("class_master"):
        master_classes[mc.master_id] = mc.class_master.class_no if mc.class_master else None

    for history in histories:
        slot = history.time_slot
        category = master_classes.get(history.master_id) or history.master.category
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
