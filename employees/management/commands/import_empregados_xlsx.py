from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from employees.models import (
    Area,
    Cargo,
    Department,
    Employee,
    EmployeeEvent,
    Sector,
    WorkSchedule,
)

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": MAIN_NS, "r": REL_NS, "p": PKG_REL_NS}


class Command(BaseCommand):
    help = (
        "Importa empregados de um XLSX com colunas: Matricula, Nome, Admissao, Cargo, Setor. "
        "Cria setor/cargo ausentes, vincula escala e cria evento de admissao."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="EMPREGADOS.xlsx",
            help="Caminho do arquivo XLSX (padrao: EMPREGADOS.xlsx na raiz).",
        )
        parser.add_argument(
            "--work-schedule",
            default="44diurno_0",
            help="Nome da escala para todos os empregados (padrao: 44diurno_0).",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"]).resolve()
        if not file_path.exists():
            raise CommandError(f"Arquivo nao encontrado: {file_path}")

        schedule_name = (options["work_schedule"] or "").strip()
        work_schedule = WorkSchedule.objects.filter(nome=schedule_name).first()
        if not work_schedule:
            raise CommandError(f"Escala '{schedule_name}' nao encontrada.")

        rows = _read_xlsx_rows(file_path)
        if not rows:
            self.stdout.write(self.style.WARNING("Arquivo vazio."))
            return

        header_map = {_normalize_header(h): idx for idx, h in enumerate(rows[0])}
        required = ("matricula", "nome", "admissao", "cargo", "setor")
        missing = [h for h in required if h not in header_map]
        if missing:
            raise CommandError(
                "Cabecalho invalido. Faltam colunas obrigatorias: " + ", ".join(missing)
            )

        _, department_zero = _get_or_create_default_area_department()

        imported = 0
        skipped = 0
        errors = []
        seen_file_matriculas = set()

        for line_no, row in enumerate(rows[1:], start=2):
            matricula = _cell(row, header_map["matricula"]).strip()
            nome = _cell(row, header_map["nome"]).strip()
            cargo_name = _cell(row, header_map["cargo"]).strip()
            setor_name = _cell(row, header_map["setor"]).strip()
            admission_raw = _cell(row, header_map["admissao"]).strip()

            if not matricula or not nome or not cargo_name or not setor_name or not admission_raw:
                skipped += 1
                errors.append(f"Linha {line_no}: campos obrigatorios ausentes.")
                continue

            if matricula in seen_file_matriculas:
                skipped += 1
                errors.append(f"Linha {line_no}: matricula '{matricula}' duplicada no arquivo.")
                continue
            seen_file_matriculas.add(matricula)

            if Employee.objects.filter(matricula=matricula).exists():
                skipped += 1
                errors.append(f"Linha {line_no}: matricula '{matricula}' ja existe.")
                continue

            try:
                admission_date = _parse_admission_date(admission_raw)
            except ValueError:
                skipped += 1
                errors.append(
                    f"Linha {line_no}: admissao '{admission_raw}' invalida. Use DD/MM/AAAA ou data valida no Excel."
                )
                continue

            cargo = Cargo.objects.filter(
                nome__iexact=cargo_name,
                deactivated_at__isnull=True,
            ).first()
            if not cargo:
                cargo = Cargo.objects.create(nome=cargo_name)

            sector = (
                Sector.objects.filter(nome__iexact=setor_name, deactivated_at__isnull=True)
                .order_by("id")
                .first()
            )
            if not sector:
                sector = Sector.objects.create(nome=setor_name, department=department_zero)

            with transaction.atomic():
                employee = Employee.objects.create(
                    matricula=matricula,
                    nome_completo=nome,
                    tipo=Employee.TYPE_DIRETO,
                    regime_compensacao_jornada=Employee.REGIME_COMPENSACAO_PARTICIPANTE,
                    cargo=cargo,
                    sector=sector,
                    work_schedule=work_schedule,
                )

                EmployeeEvent.objects.create(
                    employee=employee,
                    event_type=EmployeeEvent.EVENT_TYPE_HIRING,
                    effective_date=admission_date,
                    notes="Evento de admissao criado automaticamente por importacao XLSX.",
                )

            imported += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Importacao concluida. Importados: {imported}. Ignorados: {skipped}."
            )
        )
        if errors:
            self.stdout.write("Detalhes:")
            for error in errors:
                self.stdout.write(f"- {error}")


def _normalize_header(value: str) -> str:
    return _strip_accents((value or "").strip().lower())


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)
    )


def _cell(row: list[str], idx: int) -> str:
    if idx >= len(row):
        return ""
    return str(row[idx] or "")


def _parse_admission_date(raw: str) -> date:
    value = (raw or "").strip()

    if re.fullmatch(r"\d+(\.\d+)?", value):
        serial = float(value)
        # Excel serial date system (1900-based), handling modern dates only.
        return date(1899, 12, 30) + timedelta(days=serial)

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    raise ValueError("invalid date")


def _get_or_create_default_area_department():
    area_zero = Area.objects.filter(
        nome="0",
        deactivated_at__isnull=True,
    ).first()
    if not area_zero:
        area_zero = Area.objects.create(nome="0")

    department_zero = Department.objects.filter(
        area=area_zero,
        nome="0",
        deactivated_at__isnull=True,
    ).first()
    if not department_zero:
        department_zero = Department.objects.create(area=area_zero, nome="0")

    return area_zero, department_zero


def _read_xlsx_rows(file_path: Path) -> list[list[str]]:
    with zipfile.ZipFile(file_path) as archive:
        shared_strings = _load_shared_strings(archive)
        style_ids_with_date = _load_date_style_ids(archive)
        sheet_path = _first_sheet_path(archive)
        sheet_xml = ET.fromstring(archive.read(sheet_path))

    rows = []
    for row_node in sheet_xml.findall("a:sheetData/a:row", NS):
        parsed = []
        for cell_node in row_node.findall("a:c", NS):
            parsed.append(_parse_cell(cell_node, shared_strings, style_ids_with_date))
        rows.append(parsed)
    return rows


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))

    first_sheet = workbook.find("a:sheets/a:sheet", NS)
    if first_sheet is None:
        raise CommandError("XLSX sem planilhas.")

    rel_id = first_sheet.attrib.get(f"{{{REL_NS}}}id")
    if not rel_id:
        raise CommandError("Nao foi possivel localizar o relacionamento da planilha.")

    target = None
    for rel in rels.findall("p:Relationship", NS):
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib.get("Target")
            break

    if not target:
        raise CommandError("Nao foi possivel localizar o arquivo XML da planilha.")

    if target.startswith("/"):
        return target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return f"xl/{target}"


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        xml_bytes = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(xml_bytes)
    values = []
    for si in root.findall("a:si", NS):
        text = "".join(node.text or "" for node in si.findall(".//a:t", NS))
        values.append(text)
    return values


def _load_date_style_ids(archive: zipfile.ZipFile) -> set[int]:
    try:
        xml_bytes = archive.read("xl/styles.xml")
    except KeyError:
        return set()

    root = ET.fromstring(xml_bytes)
    custom_date_format_ids = set()
    for fmt in root.findall("a:numFmts/a:numFmt", NS):
        fmt_id = fmt.attrib.get("numFmtId")
        fmt_code = (fmt.attrib.get("formatCode") or "").lower()
        if not fmt_id:
            continue
        if any(token in fmt_code for token in ("d", "m", "y", "h", "s")):
            custom_date_format_ids.add(int(fmt_id))

    built_in_date_ids = {
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        27,
        30,
        36,
        45,
        46,
        47,
        50,
        57,
    }

    date_styles = set()
    cell_xfs = root.findall("a:cellXfs/a:xf", NS)
    for idx, xf in enumerate(cell_xfs):
        num_fmt_id = xf.attrib.get("numFmtId")
        if not num_fmt_id:
            continue
        num_fmt_id_int = int(num_fmt_id)
        if num_fmt_id_int in built_in_date_ids or num_fmt_id_int in custom_date_format_ids:
            date_styles.add(idx)
    return date_styles


def _parse_cell(cell_node: ET.Element, shared_strings: list[str], date_style_ids: set[int]) -> str:
    cell_type = cell_node.attrib.get("t")
    style_idx = cell_node.attrib.get("s")

    if cell_type == "inlineStr":
        inline_str = cell_node.find("a:is", NS)
        if inline_str is None:
            return ""
        return "".join(node.text or "" for node in inline_str.findall(".//a:t", NS)).strip()

    value_node = cell_node.find("a:v", NS)
    if value_node is None or value_node.text is None:
        return ""

    raw = value_node.text.strip()

    if cell_type == "s":
        idx = int(raw)
        if 0 <= idx < len(shared_strings):
            return shared_strings[idx].strip()
        return ""

    if style_idx is not None:
        try:
            if int(style_idx) in date_style_ids and re.fullmatch(r"\d+(\.\d+)?", raw):
                parsed = date(1899, 12, 30) + timedelta(days=float(raw))
                return parsed.strftime("%d/%m/%Y")
        except ValueError:
            pass

    return raw
