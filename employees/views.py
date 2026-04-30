from calendar import monthrange
from urllib.parse import urlencode
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, timedelta
import ast
import re
from collections import defaultdict

from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Employee,
    EmployeeEvent,
    BankHoursRule,
    EmployeeTimeEntry,
    TimesheetMonthClosure,
    TimesheetMonthClosureCalendarPeriodSnapshot,
    TimesheetMonthClosureEmployeeEventSnapshot,
    TimesheetMonthClosureWorkScheduleSnapshot,
    Cargo,
    Sector,
    WorkCalendar,
    WorkCalendarPeriod,
    WorkSchedule,
)

WEEKDAY_HOUR_FIELDS = (
    ("horas_segunda", "segunda-feira"),
    ("horas_terca", "terca-feira"),
    ("horas_quarta", "quarta-feira"),
    ("horas_quinta", "quinta-feira"),
    ("horas_sexta", "sexta-feira"),
    ("horas_sabado", "sabado"),
    ("horas_domingo", "domingo"),
)
SCHEDULE_FIELDS_IN_WEEKDAY_ORDER = tuple(
    field_name for field_name, _ in WEEKDAY_HOUR_FIELDS
)

TIME_ENTRY_MINUTE_FIELDS = (
    ("regular_minutes", "horas normais"),
    ("overtime_60_minutes", "horas extras 60%"),
    ("overtime_100_minutes", "horas extras 100%"),
    ("absence_unexcused_minutes", "ausencias por falta"),
    ("absence_excused_minutes", "ausencias justificadas"),
    ("absence_bank_minutes", "ausencias por banco"),
)


def _employees_redirect_with_flags(**params):
    base_url = reverse("employees_page")
    query = urlencode(params)
    return f"{base_url}?{query}" if query else base_url


def _events_redirect_with_filters(employee_id=None, event_type=None):
    params = {}
    if employee_id:
        params["employee_id"] = employee_id
    if event_type:
        params["event_type"] = event_type

    base_url = reverse("events_page")
    query = urlencode(params)
    return f"{base_url}?{query}" if query else base_url


def _timesheet_redirect_with_filters(competence_month=None):
    params = {}
    if competence_month:
        params["competence_month"] = competence_month

    base_url = reverse("timesheet_page")
    query = urlencode(params)
    return f"{base_url}?{query}" if query else base_url


def _bank_hours_redirect_with_filters(start_month=None, end_month=None):
    params = {}
    if start_month:
        params["start_month"] = start_month
    if end_month:
        params["end_month"] = end_month

    base_url = reverse("bank_hours_page")
    query = urlencode(params)
    return f"{base_url}?{query}" if query else base_url


def _bank_hours_rules_redirect_with_filters(start_month=None, end_month=None):
    params = {}
    if start_month:
        params["start_month"] = start_month
    if end_month:
        params["end_month"] = end_month

    base_url = reverse("bank_hours_rules_page")
    query = urlencode(params)
    return f"{base_url}?{query}" if query else base_url


def _snapshots_audit_redirect_with_filters(competence_month=None):
    params = {}
    if competence_month:
        params["competence_month"] = competence_month

    base_url = reverse("timesheet_snapshots_audit_page")
    query = urlencode(params)
    return f"{base_url}?{query}" if query else base_url


def _employee_edit_redirect_with_tab(employee_id, tab=None):
    base_url = reverse("employee_edit_page", kwargs={"employee_id": employee_id})
    query = urlencode({"tab": tab}) if tab else ""
    return f"{base_url}?{query}" if query else base_url


def _parse_daily_hours(request_data):
    parsed_hours = {}

    for field_name, label in WEEKDAY_HOUR_FIELDS:
        raw_value = (request_data.get(field_name) or "").strip().replace(",", ".")

        if not raw_value:
            return None, f'Informe a carga horaria para "{label}".'

        try:
            hours = Decimal(raw_value)
        except InvalidOperation:
            return None, f'Valor invalido de carga horaria para "{label}".'

        if hours < 0 or hours > 24:
            return None, f'A carga horaria de "{label}" deve estar entre 0 e 24.'

        parsed_hours[field_name] = hours

    return parsed_hours, None


def _parse_special_period_dates(request_data):
    start_date_raw = (request_data.get("start_date") or "").strip()
    end_date_raw = (request_data.get("end_date") or "").strip()

    if not start_date_raw:
        return None, None, 'Informe a data de inicio do periodo.'

    if not end_date_raw:
        return None, None, 'Informe a data de fim do periodo.'

    try:
        start_date = date.fromisoformat(start_date_raw)
    except ValueError:
        return None, None, 'Informe uma data de inicio valida.'

    try:
        end_date = date.fromisoformat(end_date_raw)
    except ValueError:
        return None, None, 'Informe uma data de fim valida.'

    if end_date < start_date:
        return None, None, 'A data de fim deve ser maior ou igual a data de inicio.'

    return start_date, end_date, None


def _parse_non_negative_minutes(raw_value, field_label):
    normalized_value = (raw_value or "").strip()
    if not normalized_value:
        return 0, None

    compact_value = normalized_value.replace(" ", "")
    value = None

    if compact_value.isdigit():
        value = int(compact_value)
    else:
        hhmm_match = re.fullmatch(r"(\d+):([0-5]?\d)", compact_value)
        if not hhmm_match:
            return None, f'Valor invalido para "{field_label}".'
        hours = int(hhmm_match.group(1))
        minutes = int(hhmm_match.group(2))
        value = (hours * 60) + minutes

    if value < 0:
        return None, f'O valor de "{field_label}" nao pode ser negativo.'

    if value > 59999:
        return None, f'O valor de "{field_label}" deve ser no maximo 59999 minutos.'

    return value, None


def _resolve_competence_month(raw_value):
    normalized = (raw_value or "").strip()
    if not normalized:
        today = timezone.localdate()
        month_start = date(today.year, today.month, 1)
        return month_start, month_start.strftime("%Y-%m"), None

    try:
        month_start = date.fromisoformat(f"{normalized}-01")
    except ValueError:
        return None, None, "Informe um mes de competencia valido."

    return month_start, normalized, None


def _resolve_competence_month_interval(raw_start, raw_end, raw_fallback=None):
    normalized_start = (raw_start or "").strip()
    normalized_end = (raw_end or "").strip()
    normalized_fallback = (raw_fallback or "").strip()

    # Backward compatibility for existing links that still pass competence_month.
    if not normalized_start and not normalized_end:
        fallback_month, fallback_value, error = _resolve_competence_month(normalized_fallback)
        if error:
            return None, None, None, None, error
        return fallback_month, fallback_month, fallback_value, fallback_value, None

    if not normalized_start:
        normalized_start = normalized_end
    if not normalized_end:
        normalized_end = normalized_start

    start_month, start_value, start_error = _resolve_competence_month(normalized_start)
    if start_error:
        return None, None, None, None, "Informe um mes inicial valido."

    end_month, end_value, end_error = _resolve_competence_month(normalized_end)
    if end_error:
        return None, None, None, None, "Informe um mes final valido."

    if end_month < start_month:
        return None, None, None, None, "O mes final deve ser maior ou igual ao mes inicial."

    return start_month, end_month, start_value, end_value, None


def _safe_decimal_formula_eval(expression, variables):
    normalized = (expression or "").strip()
    if not normalized:
        raise ValueError("Formula vazia.")
    normalized = normalized.replace(",", ".")
    parsed = ast.parse(normalized, mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("Divisao por zero.")
                return left / right
            raise ValueError("Operador nao permitido.")
        if isinstance(node, ast.UnaryOp):
            value = _eval(node.operand)
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.USub):
                return -value
            raise ValueError("Operador unario nao permitido.")
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"Variavel invalida: {node.id}.")
            return Decimal(variables[node.id])
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return Decimal(str(node.value))
            raise ValueError("Constante nao permitida.")
        raise ValueError("Expressao invalida.")

    return _eval(parsed)


def _normalize_rule_formula(target_column, raw_formula):
    formula = (raw_formula or "").strip()
    if not formula:
        return None, "Informe a formula."
    compact = re.sub(r"\s+", "", formula).upper()
    if "=" in compact:
        left, right = compact.split("=", 1)
        if left != target_column:
            return None, (
                f"O lado esquerdo deve ser {target_column}. "
                f"Exemplo: {target_column}=A/2*1.6"
            )
        compact = right
    if not compact:
        return None, "Formula invalida."
    return compact, None


def _resolve_bank_hours_formulas_for_month(competence_month):
    formulas = {"B": None, "C": None, "F": None}
    rules = (
        BankHoursRule.objects.filter(
            start_month__lte=competence_month,
            end_month__gte=competence_month,
        )
        .order_by("target_column", "-start_month", "-id")
    )
    latest_by_target = {}
    for rule in rules:
        latest_by_target.setdefault(rule.target_column, rule)
    for target_column, rule in latest_by_target.items():
        formulas[target_column] = rule.formula
    return formulas


def _calculate_bank_hours_columns(overtime_minutes, absence_minutes, manual_minutes, formulas):
    values = {
        "A": Decimal(overtime_minutes),
        "B": None,
        "C": None,
        "D": Decimal(absence_minutes),
        "E": Decimal(manual_minutes),
        "F": None,
    }
    missing_targets = []
    evaluation_errors = {}
    for target in ("B", "C", "F"):
        formula = formulas.get(target)
        if not formula:
            missing_targets.append(target)
            continue
        try:
            raw_result = _safe_decimal_formula_eval(formula, values)
            values[target] = raw_result.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        except Exception as error:
            missing_targets.append(target)
            evaluation_errors[target] = str(error)

    b_value = values["B"] if values["B"] is not None else Decimal(0)
    c_value = values["C"] if values["C"] is not None else Decimal(0)
    f_value = values["F"] if values["F"] is not None else Decimal(0)
    return {
        "overtime_minutes": int(values["A"]),
        "hour_bank_base_minutes": int(b_value),
        "hour_bank_bonus_minutes": int(c_value),
        "absence_minutes": int(values["D"]),
        "manual_minutes": int(values["E"]),
        "month_delta_minutes": int(f_value),
        "credit_minutes": int(b_value + c_value),
        "is_b_defined": values["B"] is not None,
        "is_c_defined": values["C"] is not None,
        "is_f_defined": values["F"] is not None,
        "missing_targets": missing_targets,
        "evaluation_errors": evaluation_errors,
        "formulas": formulas,
    }


def _count_weekday_occurrences_in_month(month_start):
    weekday_occurrences = [0] * 7
    _, days_in_month = monthrange(month_start.year, month_start.month)

    for day in range(1, days_in_month + 1):
        day_weekday = date(month_start.year, month_start.month, day).weekday()
        weekday_occurrences[day_weekday] += 1

    return weekday_occurrences


def _iter_clipped_dates_in_month(range_start, range_end, month_start, month_end):
    clipped_start = max(range_start, month_start)
    clipped_end = min(range_end, month_end)
    if clipped_end < clipped_start:
        return

    current_date = clipped_start
    while current_date <= clipped_end:
        yield current_date
        current_date += timedelta(days=1)


def _build_calendar_exception_dates_by_calendar(calendar_ids, month_start, month_end):
    if not calendar_ids:
        return {}

    periods = WorkCalendarPeriod.objects.filter(
        calendar_id__in=calendar_ids,
        start_date__lte=month_end,
        end_date__gte=month_start,
    )
    exception_dates_by_calendar = {}
    for period in periods:
        calendar_dates = exception_dates_by_calendar.setdefault(period.calendar_id, set())
        for period_day in _iter_clipped_dates_in_month(
            period.start_date,
            period.end_date,
            month_start,
            month_end,
        ):
            calendar_dates.add(period_day)

    return exception_dates_by_calendar


def _build_employee_exception_dates_by_employee(employee_ids, month_start, month_end):
    if not employee_ids:
        return {}

    exception_types = (
        EmployeeEvent.EVENT_TYPE_DAY_OFF,
        EmployeeEvent.EVENT_TYPE_VACATION,
        EmployeeEvent.EVENT_TYPE_ABSENCE,
        EmployeeEvent.EVENT_TYPE_MEDICAL_CERTIFICATE,
    )
    events = EmployeeEvent.objects.filter(
        employee_id__in=employee_ids,
        event_type__in=exception_types,
    ).filter(
        Q(end_date__isnull=True, effective_date__gte=month_start, effective_date__lte=month_end)
        | Q(end_date__isnull=False, effective_date__lte=month_end, end_date__gte=month_start)
    )

    exception_dates_by_employee = {}
    for event in events:
        event_end_date = event.end_date or event.effective_date
        employee_dates = exception_dates_by_employee.setdefault(event.employee_id, set())
        for event_day in _iter_clipped_dates_in_month(
            event.effective_date,
            event_end_date,
            month_start,
            month_end,
        ):
            employee_dates.add(event_day)

    return exception_dates_by_employee


def _calculate_expected_minutes_for_employee(
    employee,
    month_start,
    month_end,
    calendar_exception_dates_by_calendar,
    employee_exception_dates_by_employee,
):
    work_schedule = employee.work_schedule
    if not work_schedule:
        return 0

    excluded_dates = set()
    if work_schedule.calendar_id:
        excluded_dates.update(
            calendar_exception_dates_by_calendar.get(work_schedule.calendar_id, set())
        )
    excluded_dates.update(employee_exception_dates_by_employee.get(employee.id, set()))

    total_hours = Decimal("0")
    current_date = month_start
    while current_date <= month_end:
        if current_date not in excluded_dates:
            field_name = SCHEDULE_FIELDS_IN_WEEKDAY_ORDER[current_date.weekday()]
            day_hours = getattr(work_schedule, field_name, Decimal("0")) or Decimal("0")
            total_hours += day_hours
        current_date += timedelta(days=1)

    return int(
        (total_hours * Decimal("60")).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def _get_work_schedule_or_error(work_schedule_id):
    if not work_schedule_id:
        return None, None

    work_schedule = WorkSchedule.objects.filter(id=work_schedule_id).first()
    if not work_schedule:
        return None, "Selecione uma escala valida."

    return work_schedule, None


def _get_work_calendar_or_error(calendar_id):
    if not calendar_id:
        return None, "Selecione um calendario valido."

    calendar = WorkCalendar.objects.filter(id=calendar_id).first()
    if not calendar:
        return None, "Selecione um calendario valido."

    return calendar, None


def _parse_employee_characteristics(request_data):
    tipo = (request_data.get("tipo") or "").strip()
    regime_compensacao_jornada = (
        request_data.get("regime_compensacao_jornada") or ""
    ).strip()
    valid_types = {choice[0] for choice in Employee.TYPE_CHOICES}
    valid_compensation_regimes = {
        choice[0] for choice in Employee.REGIME_COMPENSACAO_JORNADA_CHOICES
    }

    if tipo not in valid_types:
        return None, None, "Selecione um tipo de empregado valido."

    if regime_compensacao_jornada not in valid_compensation_regimes:
        return (
            None,
            None,
            "Selecione um regime de compensacao de jornada valido.",
        )

    return tipo, regime_compensacao_jornada, None


def employees_page(request):
    active_sectors = Sector.objects.filter(deactivated_at__isnull=True).order_by("nome")
    active_cargos = Cargo.objects.filter(deactivated_at__isnull=True).order_by("nome")
    work_schedules = WorkSchedule.objects.all().order_by("nome")
    all_sectors = Sector.objects.all().order_by("deactivated_at", "nome")

    if request.method == "POST":
        matricula = (request.POST.get("matricula") or "").strip()
        nome_completo = (request.POST.get("nome_completo") or "").strip()
        tipo, regime_compensacao_jornada, characteristics_error = (
            _parse_employee_characteristics(request.POST)
        )
        cargo_id = (request.POST.get("cargo_id") or "").strip()
        sector_id = (request.POST.get("sector_id") or "").strip()
        work_schedule_id = (request.POST.get("work_schedule_id") or "").strip()

        if not matricula or not nome_completo or not cargo_id or not sector_id:
            messages.error(
                request,
                "Matricula, nome completo, cargo e setor sao obrigatorios.",
            )
            return redirect("employees_page")

        if characteristics_error:
            messages.error(request, characteristics_error)
            return redirect("employees_page")

        if Employee.objects.filter(matricula=matricula).exists():
            messages.error(request, "Ja existe empregado com essa matricula.")
            return redirect("employees_page")

        cargo = active_cargos.filter(id=cargo_id).first()
        if not cargo:
            messages.error(request, "Selecione um cargo ativo valido.")
            return redirect("employees_page")

        sector = active_sectors.filter(id=sector_id).first()
        if not sector:
            messages.error(request, "Selecione um setor ativo valido.")
            return redirect("employees_page")

        work_schedule, schedule_error = _get_work_schedule_or_error(work_schedule_id)
        if schedule_error:
            messages.error(request, schedule_error)
            return redirect("employees_page")

        Employee.objects.create(
            matricula=matricula,
            nome_completo=nome_completo,
            tipo=tipo,
            regime_compensacao_jornada=regime_compensacao_jornada,
            cargo=cargo,
            sector=sector,
            work_schedule=work_schedule,
        )

        messages.success(request, "Empregado cadastrado com sucesso.")
        return redirect("employees_page")

    employees = Employee.objects.select_related("cargo", "sector", "work_schedule").order_by(
        "deactivated_at",
        "nome_completo",
    )
    active_count = employees.filter(deactivated_at__isnull=True).count()
    inactive_count = employees.filter(deactivated_at__isnull=False).count()
    unassigned_count = employees.filter(sector__isnull=True).count()
    selected_sector_id = (request.GET.get("selected_sector") or "").strip()

    return render(
        request,
        "employees.html",
        {
            "employees": employees,
            "employees_count": employees.count(),
            "active_count": active_count,
            "inactive_count": inactive_count,
            "active_sectors": active_sectors,
            "active_cargos": active_cargos,
            "work_schedules": work_schedules,
            "all_sectors": all_sectors,
            "unassigned_count": unassigned_count,
            "employee_type_choices": Employee.TYPE_CHOICES,
            "compensation_regime_choices": Employee.REGIME_COMPENSACAO_JORNADA_CHOICES,
            "open_employee_modal": request.GET.get("open_employee_modal") == "1",
            "open_sector_modal": request.GET.get("open_sector_modal") == "1",
            "selected_sector_id": selected_sector_id,
        },
    )


def _iterate_competence_months(start_date, end_date):
    current_month = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)

    while current_month <= end_month:
        yield current_month
        if current_month.month == 12:
            current_month = date(current_month.year + 1, 1, 1)
        else:
            current_month = date(current_month.year, current_month.month + 1, 1)


def _find_first_closed_competence_month(start_date, end_date=None):
    range_end = end_date or start_date
    competence_months = list(_iterate_competence_months(start_date, range_end))
    return (
        TimesheetMonthClosure.objects.filter(competence_month__in=competence_months)
        .order_by("competence_month")
        .values_list("competence_month", flat=True)
        .first()
    )


def events_page(request):
    employees = Employee.objects.select_related("sector").order_by(
        "deactivated_at",
        "nome_completo",
    )
    event_type_choices = EmployeeEvent.EVENT_TYPE_CHOICES
    valid_event_types = {choice[0] for choice in event_type_choices}

    if request.method == "POST":
        employee_id = (request.POST.get("employee_id") or "").strip()
        event_type = (request.POST.get("event_type") or "").strip()
        raw_effective_date = (request.POST.get("effective_date") or "").strip()
        raw_end_date = (request.POST.get("end_date") or "").strip()
        raw_bank_hours_amount = (request.POST.get("bank_hours_amount") or "").strip()
        notes = (request.POST.get("notes") or "").strip()

        employee = Employee.objects.filter(id=employee_id).first()
        if not employee:
            messages.error(request, "Selecione um empregado valido.")
            return redirect(_events_redirect_with_filters())

        if event_type not in valid_event_types:
            messages.error(request, "Selecione um tipo de evento valido.")
            return redirect(_events_redirect_with_filters(employee_id=employee.id))

        if not raw_effective_date:
            messages.error(request, "Informe a data de inicio do evento.")
            return redirect(
                _events_redirect_with_filters(
                    employee_id=employee.id,
                    event_type=event_type,
                )
            )

        try:
            effective_date = date.fromisoformat(raw_effective_date)
        except ValueError:
            messages.error(request, "Informe uma data de inicio valida.")
            return redirect(
                _events_redirect_with_filters(
                    employee_id=employee.id,
                    event_type=event_type,
                )
            )

        end_date = None
        if raw_end_date:
            try:
                end_date = date.fromisoformat(raw_end_date)
            except ValueError:
                messages.error(request, "Informe uma data final valida.")
                return redirect(
                    _events_redirect_with_filters(
                        employee_id=employee.id,
                        event_type=event_type,
                    )
                )

            if end_date < effective_date:
                messages.error(
                    request,
                    "A data final nao pode ser menor que a data de inicio.",
                )
                return redirect(
                    _events_redirect_with_filters(
                        employee_id=employee.id,
                        event_type=event_type,
                    )
                )

        first_closed_month = _find_first_closed_competence_month(
            effective_date,
            end_date or effective_date,
        )
        if first_closed_month:
            messages.error(
                request,
                "Nao e permitido registrar evento/ajuste com data em competencia encerrada "
                f"({_format_competence_month_label(first_closed_month)}).",
            )
            return redirect(
                _events_redirect_with_filters(
                    employee_id=employee.id,
                    event_type=event_type,
                )
            )
        bank_hours_amount = None
        if raw_bank_hours_amount:
            try:
                bank_hours_amount = Decimal(raw_bank_hours_amount.replace(",", "."))
            except InvalidOperation:
                messages.error(request, "Informe um valor valido para banco de horas.")
                return redirect(
                    _events_redirect_with_filters(
                        employee_id=employee.id,
                        event_type=event_type,
                    )
                )

        if event_type == EmployeeEvent.EVENT_TYPE_BANK_HOURS_MOVEMENT:
            if bank_hours_amount is None or bank_hours_amount == 0:
                messages.error(
                    request,
                    "Informe o valor em horas para movimento de banco de horas.",
                )
                return redirect(
                    _events_redirect_with_filters(
                        employee_id=employee.id,
                        event_type=event_type,
                    )
                )
        else:
            bank_hours_amount = None

        EmployeeEvent.objects.create(
            employee=employee,
            event_type=event_type,
            effective_date=effective_date,
            end_date=end_date,
            bank_hours_amount=bank_hours_amount,
            notes=notes,
        )
        messages.success(request, "Evento registrado com sucesso.")
        return redirect(
            _events_redirect_with_filters(
                employee_id=employee.id,
                event_type=event_type,
            )
        )

    selected_employee = None
    employee_id = (request.GET.get("employee_id") or "").strip()
    selected_event_type = (request.GET.get("event_type") or "").strip()

    if employee_id.isdigit():
        selected_employee = employees.filter(id=employee_id).first()

    if selected_event_type not in valid_event_types:
        selected_event_type = ""

    events = EmployeeEvent.objects.select_related(
        "employee",
        "previous_sector",
        "new_sector",
        "previous_work_schedule",
        "new_work_schedule",
    )
    if selected_employee:
        events = events.filter(employee=selected_employee)
    if selected_event_type:
        events = events.filter(event_type=selected_event_type)

    return render(
        request,
        "events.html",
        {
            "employees": employees,
            "selected_employee": selected_employee,
            "selected_event_type": selected_event_type,
            "event_type_choices": event_type_choices,
            "events": events,
            "events_count": events.count(),
        },
    )


def _format_competence_month_label(competence_month):
    return competence_month.strftime("%m/%Y")


def _format_minutes_as_hour_label(total_minutes):
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def _format_signed_minutes_as_hour_label(total_minutes):
    sign = "-" if total_minutes < 0 else ""
    absolute_minutes = abs(total_minutes)
    hours = absolute_minutes // 60
    minutes = absolute_minutes % 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def _get_month_date_range(month_start):
    _, days_in_month = monthrange(month_start.year, month_start.month)
    month_end = date(month_start.year, month_start.month, days_in_month)
    return month_start, month_end


def _month_start_for_date(value):
    return date(value.year, value.month, 1)


def _minutes_from_decimal_hours(raw_hours):
    decimal_hours = Decimal(raw_hours)
    return int((decimal_hours * Decimal("60")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _calc_bank_credit_minutes(overtime_minutes):
    return int(
        (
            Decimal(overtime_minutes)
            * Decimal("0.5")
            * Decimal("1.6")
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def _create_month_closure_snapshots(closure):
    month_start, month_end = _get_month_date_range(closure.competence_month)

    active_employees = Employee.objects.select_related("work_schedule__calendar").filter(
        deactivated_at__isnull=True
    )

    schedules_by_id = {}
    calendar_names_by_id = {}
    for employee in active_employees:
        schedule = employee.work_schedule
        if not schedule:
            continue
        schedules_by_id[schedule.id] = schedule
        if schedule.calendar_id:
            calendar_names_by_id[schedule.calendar_id] = schedule.calendar.nome

    schedule_snapshots = []
    for schedule in schedules_by_id.values():
        calendar = schedule.calendar
        schedule_snapshots.append(
            TimesheetMonthClosureWorkScheduleSnapshot(
                closure=closure,
                source_work_schedule_id=schedule.id,
                work_schedule_name=schedule.nome,
                source_calendar_id=calendar.id if calendar else None,
                calendar_name=calendar.nome if calendar else "",
                horas_segunda=schedule.horas_segunda,
                horas_terca=schedule.horas_terca,
                horas_quarta=schedule.horas_quarta,
                horas_quinta=schedule.horas_quinta,
                horas_sexta=schedule.horas_sexta,
                horas_sabado=schedule.horas_sabado,
                horas_domingo=schedule.horas_domingo,
            )
        )

    if schedule_snapshots:
        TimesheetMonthClosureWorkScheduleSnapshot.objects.bulk_create(schedule_snapshots)

    if not calendar_names_by_id:
        return

    period_snapshots = []
    periods = WorkCalendarPeriod.objects.filter(
        calendar_id__in=calendar_names_by_id.keys(),
        start_date__lte=month_end,
        end_date__gte=month_start,
    ).order_by("calendar_id", "start_date", "id")

    for period in periods:
        period_snapshots.append(
            TimesheetMonthClosureCalendarPeriodSnapshot(
                closure=closure,
                source_calendar_id=period.calendar_id,
                calendar_name=calendar_names_by_id.get(period.calendar_id, ""),
                period_type=period.period_type,
                start_date=period.start_date,
                end_date=period.end_date,
                description=period.description,
            )
        )

    if period_snapshots:
        TimesheetMonthClosureCalendarPeriodSnapshot.objects.bulk_create(period_snapshots)

    individual_exception_types = (
        EmployeeEvent.EVENT_TYPE_VACATION,
        EmployeeEvent.EVENT_TYPE_DAY_OFF,
        EmployeeEvent.EVENT_TYPE_ABSENCE,
        EmployeeEvent.EVENT_TYPE_MEDICAL_CERTIFICATE,
    )
    event_snapshots = []
    exception_events = (
        EmployeeEvent.objects.select_related("employee")
        .filter(
            event_type__in=individual_exception_types,
            effective_date__lte=month_end,
        )
        .filter(
            Q(end_date__gte=month_start)
            | Q(end_date__isnull=True, effective_date__gte=month_start)
        )
        .order_by("employee__nome_completo", "effective_date", "id")
    )
    for event in exception_events:
        event_snapshots.append(
            TimesheetMonthClosureEmployeeEventSnapshot(
                closure=closure,
                source_employee_event_id=event.id,
                source_employee_id=event.employee_id,
                employee_registration=event.employee.matricula,
                employee_name=event.employee.nome_completo,
                event_type=event.event_type,
                effective_date=event.effective_date,
                end_date=event.end_date,
                notes=event.notes,
            )
        )

    if event_snapshots:
        TimesheetMonthClosureEmployeeEventSnapshot.objects.bulk_create(event_snapshots)


def _delete_month_closures_with_snapshots(closure_qs):
    closure_ids = list(closure_qs.values_list("id", flat=True))
    if not closure_ids:
        return 0

    TimesheetMonthClosureWorkScheduleSnapshot.objects.filter(
        closure_id__in=closure_ids
    )._raw_delete(closure_qs.db)
    TimesheetMonthClosureCalendarPeriodSnapshot.objects.filter(
        closure_id__in=closure_ids
    )._raw_delete(closure_qs.db)
    TimesheetMonthClosureEmployeeEventSnapshot.objects.filter(
        closure_id__in=closure_ids
    )._raw_delete(closure_qs.db)
    return TimesheetMonthClosure.objects.filter(id__in=closure_ids)._raw_delete(
        closure_qs.db
    )


def _get_latest_closure_for_schedule(schedule_id):
    schedule_snapshot = (
        TimesheetMonthClosureWorkScheduleSnapshot.objects.select_related("closure")
        .filter(source_work_schedule_id=schedule_id)
        .order_by("-closure__competence_month")
        .first()
    )
    return schedule_snapshot.closure if schedule_snapshot else None


def _get_latest_closure_for_calendar(calendar_id):
    schedule_hit = (
        TimesheetMonthClosureWorkScheduleSnapshot.objects.select_related("closure")
        .filter(source_calendar_id=calendar_id)
        .order_by("-closure__competence_month")
        .first()
    )
    period_hit = (
        TimesheetMonthClosureCalendarPeriodSnapshot.objects.select_related("closure")
        .filter(source_calendar_id=calendar_id)
        .order_by("-closure__competence_month")
        .first()
    )

    candidates = [hit.closure for hit in (schedule_hit, period_hit) if hit]
    if not candidates:
        return None

    return max(candidates, key=lambda closure: closure.competence_month)


def timesheet_page(request):
    employees = list(
        Employee.objects.select_related("sector", "work_schedule")
        .filter(deactivated_at__isnull=True)
        .order_by("nome_completo")
    )

    if request.method == "POST":
        competence_month, competence_month_value, error = _resolve_competence_month(
            request.POST.get("competence_month")
        )
        if error:
            messages.error(request, error)
            return redirect(_timesheet_redirect_with_filters())

        action = (request.POST.get("action") or "save").strip()
        competence_month_label = _format_competence_month_label(competence_month)

        if action == "close_month":
            closure, created = TimesheetMonthClosure.objects.get_or_create(
                competence_month=competence_month
            )
            if created:
                _create_month_closure_snapshots(closure)
                messages.success(
                    request,
                    f"Timesheet de {competence_month_label} encerrado. Alteracoes estao bloqueadas.",
                )
            else:
                messages.info(
                    request,
                    f"Timesheet de {competence_month_label} ja estava encerrado.",
                )
            return redirect(
                _timesheet_redirect_with_filters(competence_month=competence_month_value)
            )

        if action == "reopen_month":
            closure_qs = TimesheetMonthClosure.objects.filter(
                competence_month=competence_month
            )
            was_closed = closure_qs.exists()
            if was_closed:
                try:
                    _delete_month_closures_with_snapshots(closure_qs)
                except IntegrityError:
                    messages.error(
                        request,
                        (
                            f"Nao foi possivel reabrir o timesheet de {competence_month_label} "
                            "porque existem dependencias no banco. "
                            "Revise referencias de snapshot para esta competencia."
                        ),
                    )
                    return redirect(
                        _timesheet_redirect_with_filters(
                            competence_month=competence_month_value
                        )
                    )
                messages.success(
                    request,
                    f"Timesheet de {competence_month_label} reaberto. Alteracoes estao liberadas.",
                )
            else:
                messages.info(
                    request,
                    f"Timesheet de {competence_month_label} ja estava aberto.",
                )
            return redirect(
                _timesheet_redirect_with_filters(competence_month=competence_month_value)
            )

        if TimesheetMonthClosure.objects.filter(competence_month=competence_month).exists():
            messages.error(
                request,
                f"O timesheet de {competence_month_label} esta encerrado. Reabra o mes para salvar alteracoes.",
            )
            return redirect(
                _timesheet_redirect_with_filters(competence_month=competence_month_value)
            )

        entries_in_month = {
            entry.employee_id: entry
            for entry in EmployeeTimeEntry.objects.filter(
                competence_month=competence_month
            ).only("id", "employee_id")
        }

        updated_count = 0
        removed_count = 0
        for employee in employees:
            parsed_values = {}
            for field_name, field_label in TIME_ENTRY_MINUTE_FIELDS:
                value, value_error = _parse_non_negative_minutes(
                    request.POST.get(f"{field_name}_{employee.id}"),
                    f"{field_label} - {employee.nome_completo}",
                )
                if value_error:
                    messages.error(request, value_error)
                    return redirect(
                        _timesheet_redirect_with_filters(
                            competence_month=competence_month_value
                        )
                    )
                parsed_values[field_name] = value

            if (
                employee.regime_compensacao_jornada
                != Employee.REGIME_COMPENSACAO_PARTICIPANTE
            ):
                parsed_values["absence_bank_minutes"] = 0

            notes = (request.POST.get(f"notes_{employee.id}") or "").strip()
            has_content = any(value > 0 for value in parsed_values.values()) or notes
            existing_entry = entries_in_month.get(employee.id)

            if has_content:
                EmployeeTimeEntry.objects.update_or_create(
                    employee=employee,
                    competence_month=competence_month,
                    defaults={
                        **parsed_values,
                        "notes": notes,
                    },
                )
                updated_count += 1
                continue

            if existing_entry:
                existing_entry.delete()
                removed_count += 1

        messages.success(
            request,
            f"Timesheet mensal salvo para {updated_count} empregado(s).",
        )
        if removed_count:
            messages.info(
                request,
                f"{removed_count} empregado(s) sem valores foram removidos do mes.",
            )

        return redirect(
            _timesheet_redirect_with_filters(competence_month=competence_month_value)
        )

    competence_month, selected_competence_month, error = _resolve_competence_month(
        request.GET.get("competence_month")
    )
    if error:
        messages.error(request, error)
        return redirect(_timesheet_redirect_with_filters())

    is_month_closed = TimesheetMonthClosure.objects.filter(
        competence_month=competence_month
    ).exists()

    month_entries = EmployeeTimeEntry.objects.select_related("employee").filter(
        competence_month=competence_month
    )
    entries_by_employee = {entry.employee_id: entry for entry in month_entries}

    month_start, month_end = _get_month_date_range(competence_month)
    calendar_ids = {
        employee.work_schedule.calendar_id
        for employee in employees
        if employee.work_schedule and employee.work_schedule.calendar_id
    }
    employee_ids = [employee.id for employee in employees]

    calendar_exception_dates_by_calendar = _build_calendar_exception_dates_by_calendar(
        calendar_ids,
        month_start,
        month_end,
    )
    employee_exception_dates_by_employee = _build_employee_exception_dates_by_employee(
        employee_ids,
        month_start,
        month_end,
    )

    rows = []
    total_expected_minutes = 0
    for employee in employees:
        expected_minutes = _calculate_expected_minutes_for_employee(
            employee,
            month_start,
            month_end,
            calendar_exception_dates_by_calendar,
            employee_exception_dates_by_employee,
        )
        total_expected_minutes += expected_minutes
        rows.append(
            {
                "employee": employee,
                "entry": entries_by_employee.get(employee.id),
                "expected_minutes": expected_minutes,
            }
        )

    timesheet_entries_list = list(entries_by_employee.values())
    total_regular_minutes = sum(
        (entry.regular_minutes for entry in timesheet_entries_list),
        0,
    )
    total_overtime_60_minutes = sum(
        (entry.overtime_60_minutes for entry in timesheet_entries_list),
        0,
    )
    total_overtime_100_minutes = sum(
        (entry.overtime_100_minutes for entry in timesheet_entries_list),
        0,
    )
    total_overtime_minutes = total_overtime_60_minutes + total_overtime_100_minutes
    total_worked_minutes = total_regular_minutes + total_overtime_minutes
    total_absence_unexcused_minutes = sum(
        (entry.absence_unexcused_minutes for entry in timesheet_entries_list),
        0,
    )
    total_absence_excused_minutes = sum(
        (entry.absence_excused_minutes for entry in timesheet_entries_list),
        0,
    )
    total_absence_bank_minutes = sum(
        (
            entry.absence_bank_minutes
            if entry.employee.regime_compensacao_jornada
            == Employee.REGIME_COMPENSACAO_PARTICIPANTE
            else 0
            for entry in timesheet_entries_list
        ),
        0,
    )
    total_absence_minutes = (
        total_absence_unexcused_minutes
        + total_absence_excused_minutes
        + total_absence_bank_minutes
    )
    return render(
        request,
        "timesheet.html",
        {
            "rows": rows,
            "selected_competence_month": selected_competence_month,
            "is_month_closed": is_month_closed,
            "registered_employees_count": len(entries_by_employee),
            "employees_count": len(employees),
            "total_regular_minutes": total_regular_minutes,
            "total_worked_minutes": total_worked_minutes,
            "total_overtime_minutes": total_overtime_minutes,
            "total_overtime_60_minutes": total_overtime_60_minutes,
            "total_overtime_100_minutes": total_overtime_100_minutes,
            "total_absence_unexcused_minutes": total_absence_unexcused_minutes,
            "total_absence_excused_minutes": total_absence_excused_minutes,
            "total_absence_bank_minutes": total_absence_bank_minutes,
            "total_absence_minutes": total_absence_minutes,
            "total_expected_minutes": total_expected_minutes,
        },
    )


def timesheet_snapshots_audit_page(request):
    competence_month, selected_competence_month, error = _resolve_competence_month(
        request.GET.get("competence_month")
    )
    if error:
        messages.error(request, error)
        return redirect(_snapshots_audit_redirect_with_filters())

    closure = TimesheetMonthClosure.objects.filter(competence_month=competence_month).first()

    schedule_snapshots = []
    calendar_period_snapshots = []
    employee_event_snapshots = []
    if closure:
        schedule_snapshots = list(
            TimesheetMonthClosureWorkScheduleSnapshot.objects.filter(closure=closure).order_by(
                "work_schedule_name",
                "source_work_schedule_id",
            )
        )
        calendar_period_snapshots = list(
            TimesheetMonthClosureCalendarPeriodSnapshot.objects.filter(closure=closure).order_by(
                "calendar_name",
                "start_date",
                "id",
            )
        )
        employee_event_snapshots = list(
            TimesheetMonthClosureEmployeeEventSnapshot.objects.filter(closure=closure).order_by(
                "employee_name",
                "effective_date",
                "source_employee_event_id",
            )
        )

    closed_months = list(
        TimesheetMonthClosure.objects.order_by("-competence_month").values_list(
            "competence_month", flat=True
        )[:24]
    )

    return render(
        request,
        "timesheet_snapshots_audit.html",
        {
            "selected_competence_month": selected_competence_month,
            "closure": closure,
            "schedule_snapshots": schedule_snapshots,
            "calendar_period_snapshots": calendar_period_snapshots,
            "employee_event_snapshots": employee_event_snapshots,
            "closed_months": closed_months,
            "closed_months_count": len(closed_months),
        },
    )


def timesheet_dashboard_page(request):
    start_month, end_month, selected_start_month, selected_end_month, error = (
        _resolve_competence_month_interval(
            request.GET.get("start_month"),
            request.GET.get("end_month"),
            request.GET.get("competence_month"),
        )
    )
    if error:
        messages.error(request, error)
        return redirect(_timesheet_redirect_with_filters())

    employees = list(
        Employee.objects.select_related("sector", "work_schedule")
        .filter(deactivated_at__isnull=True)
        .order_by("nome_completo")
    )

    competence_months = list(_iterate_competence_months(start_month, end_month))
    month_entries = EmployeeTimeEntry.objects.select_related("employee", "employee__sector").filter(
        competence_month__in=competence_months
    )
    entries_by_employee = {}
    for entry in month_entries:
        employee_entry = entries_by_employee.setdefault(
            entry.employee_id,
            {
                "regular_minutes": 0,
                "overtime_60_minutes": 0,
                "overtime_100_minutes": 0,
                "absence_unexcused_minutes": 0,
                "absence_excused_minutes": 0,
                "absence_bank_minutes": 0,
            },
        )
        employee_entry["regular_minutes"] += entry.regular_minutes
        employee_entry["overtime_60_minutes"] += entry.overtime_60_minutes
        employee_entry["overtime_100_minutes"] += entry.overtime_100_minutes
        employee_entry["absence_unexcused_minutes"] += entry.absence_unexcused_minutes
        employee_entry["absence_excused_minutes"] += entry.absence_excused_minutes
        employee_entry["absence_bank_minutes"] += entry.absence_bank_minutes

    calendar_ids = {
        employee.work_schedule.calendar_id
        for employee in employees
        if employee.work_schedule and employee.work_schedule.calendar_id
    }
    employee_ids = [employee.id for employee in employees]

    calendar_exception_dates_by_calendar = _build_calendar_exception_dates_by_calendar(
        calendar_ids,
        start_month,
        _get_month_date_range(end_month)[1],
    )
    employee_exception_dates_by_employee = _build_employee_exception_dates_by_employee(
        employee_ids,
        start_month,
        _get_month_date_range(end_month)[1],
    )

    sector_data = {}
    total_expected_minutes = 0
    total_regular_minutes = 0
    total_overtime_60_minutes = 0
    total_overtime_100_minutes = 0
    total_absence_unexcused_minutes = 0
    total_absence_excused_minutes = 0
    total_absence_bank_minutes = 0
    total_mod_minutes = 0
    total_moi_minutes = 0

    for employee in employees:
        expected_minutes = 0
        for competence_month in competence_months:
            month_start, month_end = _get_month_date_range(competence_month)
            expected_minutes += _calculate_expected_minutes_for_employee(
                employee,
                month_start,
                month_end,
                calendar_exception_dates_by_calendar,
                employee_exception_dates_by_employee,
            )
        total_expected_minutes += expected_minutes

        entry = entries_by_employee.get(employee.id)
        regular_minutes = entry["regular_minutes"] if entry else 0
        overtime_60_minutes = entry["overtime_60_minutes"] if entry else 0
        overtime_100_minutes = entry["overtime_100_minutes"] if entry else 0
        absence_unexcused_minutes = entry["absence_unexcused_minutes"] if entry else 0
        absence_excused_minutes = entry["absence_excused_minutes"] if entry else 0
        absence_bank_minutes = 0
        if entry and employee.regime_compensacao_jornada == Employee.REGIME_COMPENSACAO_PARTICIPANTE:
            absence_bank_minutes = entry["absence_bank_minutes"]

        worked_minutes = regular_minutes + overtime_60_minutes + overtime_100_minutes

        total_regular_minutes += regular_minutes
        total_overtime_60_minutes += overtime_60_minutes
        total_overtime_100_minutes += overtime_100_minutes
        total_absence_unexcused_minutes += absence_unexcused_minutes
        total_absence_excused_minutes += absence_excused_minutes
        total_absence_bank_minutes += absence_bank_minutes

        if employee.tipo == Employee.TYPE_DIRETO:
            total_mod_minutes += worked_minutes
        else:
            total_moi_minutes += worked_minutes

        sector_name = employee.sector.nome if employee.sector else "Sem setor"
        if sector_name not in sector_data:
            sector_data[sector_name] = {
                "name": sector_name,
                "expected_minutes": 0,
                "regular_minutes": 0,
                "overtime_60_minutes": 0,
                "overtime_100_minutes": 0,
                "worked_minutes": 0,
                "absence_unexcused_minutes": 0,
                "absence_excused_minutes": 0,
                "absence_bank_minutes": 0,
            }

        sector_bucket = sector_data[sector_name]
        sector_bucket["expected_minutes"] += expected_minutes
        sector_bucket["regular_minutes"] += regular_minutes
        sector_bucket["overtime_60_minutes"] += overtime_60_minutes
        sector_bucket["overtime_100_minutes"] += overtime_100_minutes
        sector_bucket["worked_minutes"] += worked_minutes
        sector_bucket["absence_unexcused_minutes"] += absence_unexcused_minutes
        sector_bucket["absence_excused_minutes"] += absence_excused_minutes
        sector_bucket["absence_bank_minutes"] += absence_bank_minutes

    total_overtime_minutes = total_overtime_60_minutes + total_overtime_100_minutes
    total_worked_minutes = total_regular_minutes + total_overtime_minutes
    total_absence_minutes = (
        total_absence_unexcused_minutes
        + total_absence_excused_minutes
        + total_absence_bank_minutes
    )

    total_type_minutes = total_mod_minutes + total_moi_minutes
    mod_share_percent = (
        round((total_mod_minutes * 100) / total_type_minutes) if total_type_minutes else 0
    )
    moi_share_percent = 100 - mod_share_percent if total_type_minutes else 0

    sector_rows = sorted(
        sector_data.values(),
        key=lambda row: row["expected_minutes"],
        reverse=True,
    )[:12]
    for row in sector_rows:
        row["balance_minutes"] = row["worked_minutes"] - row["expected_minutes"]
        row["expected_hhmm"] = _format_minutes_as_hour_label(row["expected_minutes"])
        row["worked_hhmm"] = _format_minutes_as_hour_label(row["worked_minutes"])
        row["overtime_60_hhmm"] = _format_minutes_as_hour_label(row["overtime_60_minutes"])
        row["overtime_100_hhmm"] = _format_minutes_as_hour_label(row["overtime_100_minutes"])
        row["balance_hhmm"] = _format_signed_minutes_as_hour_label(row["balance_minutes"])
        row["absence_unexcused_hhmm"] = _format_minutes_as_hour_label(
            row["absence_unexcused_minutes"]
        )
        row["absence_excused_hhmm"] = _format_minutes_as_hour_label(
            row["absence_excused_minutes"]
        )
        row["absence_bank_hhmm"] = _format_minutes_as_hour_label(
            row["absence_bank_minutes"]
        )
        row["utilization_percent"] = (
            round((row["worked_minutes"] * 100) / row["expected_minutes"])
            if row["expected_minutes"] > 0
            else 0
        )

    top_expected_minutes = max((row["expected_minutes"] for row in sector_rows), default=0)

    chart_labels = [row["name"] for row in sector_rows]
    chart_expected_hours = [round(row["expected_minutes"] / 60, 2) for row in sector_rows]
    chart_worked_hours = [round(row["regular_minutes"] / 60, 2) for row in sector_rows]
    chart_overtime_60_hours = [round(row["overtime_60_minutes"] / 60, 2) for row in sector_rows]
    chart_overtime_100_hours = [round(row["overtime_100_minutes"] / 60, 2) for row in sector_rows]
    chart_balance_hours = [
        round((row["worked_minutes"] - row["expected_minutes"]) / 60, 2)
        for row in sector_rows
    ]
    chart_absence_hours = [
        round(row["absence_unexcused_minutes"] / 60, 2) for row in sector_rows
    ]
    chart_excused_hours = [
        round(row["absence_excused_minutes"] / 60, 2) for row in sector_rows
    ]

    range_start = _get_month_date_range(start_month)[0]
    range_end = _get_month_date_range(end_month)[1]
    month_reference_label = f"{range_start.strftime('%d/%m')} - {range_end.strftime('%d/%m/%Y')}"
    if start_month == end_month:
        competence_month_label = _format_competence_month_label(start_month)
    else:
        competence_month_label = (
            f"{_format_competence_month_label(start_month)} a "
            f"{_format_competence_month_label(end_month)}"
        )

    return render(
        request,
        "dashboard_horas_grouped_stacked.html",
        {
            "selected_competence_month": selected_end_month,
            "selected_start_month": selected_start_month,
            "selected_end_month": selected_end_month,
            "competence_month_label": competence_month_label,
            "month_reference_label": month_reference_label,
            "employees_count": len(employees),
            "registered_employees_count": len(entries_by_employee),
            "total_expected_minutes": total_expected_minutes,
            "total_regular_minutes": total_regular_minutes,
            "total_worked_minutes": total_worked_minutes,
            "total_overtime_minutes": total_overtime_minutes,
            "total_absence_minutes": total_absence_minutes,
            "total_absence_unexcused_minutes": total_absence_unexcused_minutes,
            "total_absence_excused_minutes": total_absence_excused_minutes,
            "total_absence_bank_minutes": total_absence_bank_minutes,
            "mod_share_percent": mod_share_percent,
            "moi_share_percent": moi_share_percent,
            "sector_rows": sector_rows,
            "top_expected_minutes": top_expected_minutes,
            "chart_labels": chart_labels,
            "chart_expected_hours": chart_expected_hours,
            "chart_worked_hours": chart_worked_hours,
            "chart_overtime_60_hours": chart_overtime_60_hours,
            "chart_overtime_100_hours": chart_overtime_100_hours,
            "chart_balance_hours": chart_balance_hours,
            "chart_absence_hours": chart_absence_hours,
            "chart_excused_hours": chart_excused_hours,
            "total_expected_hhmm": _format_minutes_as_hour_label(total_expected_minutes),
            "total_worked_hhmm": _format_minutes_as_hour_label(total_worked_minutes),
            "total_overtime_hhmm": _format_minutes_as_hour_label(total_overtime_minutes),
            "total_absence_hhmm": _format_minutes_as_hour_label(total_absence_minutes),
        },
    )


def bank_hours_page(request):
    start_month, end_month, selected_start_month, selected_end_month, error = (
        _resolve_competence_month_interval(
            request.GET.get("start_month"),
            request.GET.get("end_month"),
            request.GET.get("competence_month"),
        )
    )
    if error:
        messages.error(request, error)
        return redirect(_bank_hours_redirect_with_filters())

    participants = list(
        Employee.objects.select_related("sector")
        .filter(
            deactivated_at__isnull=True,
            regime_compensacao_jornada=Employee.REGIME_COMPENSACAO_PARTICIPANTE,
        )
        .order_by("nome_completo")
    )

    competence_months = list(_iterate_competence_months(start_month, end_month))
    competence_month_set = set(competence_months)
    participant_ids = [employee.id for employee in participants]

    entries_qs = EmployeeTimeEntry.objects.filter(employee_id__in=participant_ids)
    entries_in_range = entries_qs.filter(competence_month__in=competence_months)
    entries_before_range = entries_qs.filter(competence_month__lt=start_month)

    monthly_entry_data = defaultdict(
        lambda: {
            "overtime_minutes": 0,
            "absence_minutes": 0,
            "manual_minutes": 0,
        }
    )
    opening_balance_by_employee = defaultdict(int)
    opening_balance_known_by_employee = defaultdict(lambda: True)

    for entry in entries_in_range:
        key = (entry.employee_id, entry.competence_month)
        overtime_minutes = entry.overtime_60_minutes + entry.overtime_100_minutes
        absence_minutes = (
            entry.absence_unexcused_minutes
            + entry.absence_bank_minutes
        )
        monthly_entry_data[key]["overtime_minutes"] += overtime_minutes
        monthly_entry_data[key]["absence_minutes"] += absence_minutes

    for entry in entries_before_range:
        competence_month = entry.competence_month
        overtime_minutes = entry.overtime_60_minutes + entry.overtime_100_minutes
        absence_minutes = (
            entry.absence_unexcused_minutes
            + entry.absence_bank_minutes
        )
        formulas = _resolve_bank_hours_formulas_for_month(competence_month)
        calc = _calculate_bank_hours_columns(
            overtime_minutes=overtime_minutes,
            absence_minutes=absence_minutes,
            manual_minutes=0,
            formulas=formulas,
        )
        if calc["is_f_defined"]:
            opening_balance_by_employee[entry.employee_id] += calc["month_delta_minutes"]
        else:
            opening_balance_known_by_employee[entry.employee_id] = False

    movement_events_qs = EmployeeEvent.objects.filter(
        employee_id__in=participant_ids,
        event_type=EmployeeEvent.EVENT_TYPE_BANK_HOURS_MOVEMENT,
        bank_hours_amount__isnull=False,
    )

    for movement in movement_events_qs.filter(
        effective_date__lt=start_month,
    ):
        opening_balance_by_employee[movement.employee_id] += _minutes_from_decimal_hours(
            movement.bank_hours_amount
        )

    for movement in movement_events_qs.filter(
        effective_date__gte=start_month,
        effective_date__lte=_get_month_date_range(end_month)[1],
    ):
        month_key = _month_start_for_date(movement.effective_date)
        if month_key not in competence_month_set:
            continue
        monthly_entry_data[(movement.employee_id, month_key)]["manual_minutes"] += (
            _minutes_from_decimal_hours(movement.bank_hours_amount)
        )

    rows = []
    total_credit_minutes = 0
    total_hour_bank_base_minutes = 0
    total_hour_bank_bonus_minutes = 0
    total_absence_minutes = 0
    total_manual_minutes = 0
    total_month_delta_minutes = 0
    total_closing_balance_minutes = 0
    has_missing_rule_b = False
    has_missing_rule_c = False
    has_missing_rule_f = False
    applied_formulas_map = {}

    for employee in participants:
        running_balance = opening_balance_by_employee[employee.id]
        running_balance_known = opening_balance_known_by_employee[employee.id]
        for competence_month in competence_months:
            payload = monthly_entry_data[(employee.id, competence_month)]
            formulas = _resolve_bank_hours_formulas_for_month(competence_month)
            applied_formulas_map[competence_month] = formulas
            calc = _calculate_bank_hours_columns(
                overtime_minutes=payload["overtime_minutes"],
                absence_minutes=payload["absence_minutes"],
                manual_minutes=payload["manual_minutes"],
                formulas=formulas,
            )
            month_delta_minutes = calc["month_delta_minutes"] if calc["is_f_defined"] else None
            if calc["is_f_defined"] and running_balance_known:
                running_balance += month_delta_minutes
            else:
                running_balance_known = False

            has_missing_rule_b = has_missing_rule_b or (not calc["is_b_defined"])
            has_missing_rule_c = has_missing_rule_c or (not calc["is_c_defined"])
            has_missing_rule_f = has_missing_rule_f or (not calc["is_f_defined"])
            rows.append(
                {
                    "employee": employee,
                    "competence_month": competence_month,
                    "overtime_minutes": calc["overtime_minutes"],
                    "overtime_hhmm": _format_minutes_as_hour_label(
                        calc["overtime_minutes"]
                    ),
                    "hour_bank_base_minutes": calc["hour_bank_base_minutes"],
                    "hour_bank_base_hhmm": _format_minutes_as_hour_label(
                        calc["hour_bank_base_minutes"]
                    ),
                    "is_b_defined": calc["is_b_defined"],
                    "hour_bank_bonus_minutes": calc["hour_bank_bonus_minutes"],
                    "hour_bank_bonus_hhmm": _format_minutes_as_hour_label(
                        calc["hour_bank_bonus_minutes"]
                    ),
                    "is_c_defined": calc["is_c_defined"],
                    "credit_minutes": calc["credit_minutes"],
                    "credit_hhmm": _format_minutes_as_hour_label(
                        calc["credit_minutes"]
                    ),
                    "absence_minutes": calc["absence_minutes"],
                    "absence_hhmm": _format_minutes_as_hour_label(
                        calc["absence_minutes"]
                    ),
                    "manual_minutes": calc["manual_minutes"],
                    "manual_hhmm": _format_signed_minutes_as_hour_label(
                        calc["manual_minutes"]
                    ),
                    "month_delta_minutes": month_delta_minutes if month_delta_minutes is not None else 0,
                    "month_delta_hhmm": _format_signed_minutes_as_hour_label(month_delta_minutes or 0),
                    "is_f_defined": calc["is_f_defined"],
                    "running_balance_minutes": running_balance if running_balance_known else 0,
                    "running_balance_hhmm": _format_signed_minutes_as_hour_label(running_balance if running_balance_known else 0),
                    "running_balance_defined": running_balance_known,
                }
            )
            total_credit_minutes += calc["credit_minutes"]
            total_hour_bank_base_minutes += calc["hour_bank_base_minutes"]
            total_hour_bank_bonus_minutes += calc["hour_bank_bonus_minutes"]
            total_absence_minutes += calc["absence_minutes"]
            total_manual_minutes += calc["manual_minutes"]
            if month_delta_minutes is not None:
                total_month_delta_minutes += month_delta_minutes

        if running_balance_known:
            total_closing_balance_minutes += running_balance

    return render(
        request,
        "bank_hours.html",
        {
            "rows": rows,
            "participants": participants,
            "participants_count": len(participants),
            "selected_start_month": selected_start_month,
            "selected_end_month": selected_end_month,
            "total_credit_minutes": total_credit_minutes,
            "total_credit_hhmm": _format_minutes_as_hour_label(total_credit_minutes),
            "total_hour_bank_base_minutes": total_hour_bank_base_minutes,
            "total_hour_bank_base_hhmm": _format_minutes_as_hour_label(
                total_hour_bank_base_minutes
            ),
            "total_hour_bank_bonus_minutes": total_hour_bank_bonus_minutes,
            "total_hour_bank_bonus_hhmm": _format_minutes_as_hour_label(
                total_hour_bank_bonus_minutes
            ),
            "total_absence_minutes": total_absence_minutes,
            "total_absence_hhmm": _format_minutes_as_hour_label(total_absence_minutes),
            "total_manual_minutes": total_manual_minutes,
            "total_manual_hhmm": _format_signed_minutes_as_hour_label(
                total_manual_minutes
            ),
            "total_month_delta_minutes": total_month_delta_minutes,
            "total_month_delta_hhmm": _format_signed_minutes_as_hour_label(
                total_month_delta_minutes
            ),
            "total_closing_balance_minutes": total_closing_balance_minutes,
            "total_closing_balance_hhmm": _format_signed_minutes_as_hour_label(
                total_closing_balance_minutes
            ),
            "rule_example": "Sem regra padrao. Cadastre formulas para B, C e F.",
            "has_missing_rule_b": has_missing_rule_b,
            "has_missing_rule_c": has_missing_rule_c,
            "has_missing_rule_f": has_missing_rule_f,
            "applied_formulas_map": applied_formulas_map,
        },
    )


def bank_hours_rules_page(request):
    start_month, end_month, selected_start_month, selected_end_month, error = (
        _resolve_competence_month_interval(
            request.GET.get("start_month"),
            request.GET.get("end_month"),
            request.GET.get("competence_month"),
        )
    )
    if error:
        messages.error(request, error)
        return redirect(_bank_hours_rules_redirect_with_filters())

    if request.method == "POST":
        target_column = (request.POST.get("target_column") or "").strip().upper()
        raw_formula = request.POST.get("formula")
        raw_start = (request.POST.get("start_month") or "").strip()
        raw_end = (request.POST.get("end_month") or "").strip()

        if target_column not in {"B", "C", "F"}:
            messages.error(request, "Selecione uma coluna de destino valida.")
            return redirect(
                _bank_hours_rules_redirect_with_filters(selected_start_month, selected_end_month)
            )

        start_month_input, _, start_error = _resolve_competence_month(raw_start)
        if start_error:
            messages.error(request, "Informe um mes inicial valido.")
            return redirect(
                _bank_hours_rules_redirect_with_filters(selected_start_month, selected_end_month)
            )

        end_month_input, _, end_error = _resolve_competence_month(raw_end)
        if end_error:
            messages.error(request, "Informe um mes final valido.")
            return redirect(
                _bank_hours_rules_redirect_with_filters(selected_start_month, selected_end_month)
            )
        if end_month_input < start_month_input:
            messages.error(request, "Mes final deve ser maior ou igual ao mes inicial.")
            return redirect(
                _bank_hours_rules_redirect_with_filters(selected_start_month, selected_end_month)
            )

        formula, formula_error = _normalize_rule_formula(target_column, raw_formula)
        if formula_error:
            messages.error(request, formula_error)
            return redirect(
                _bank_hours_rules_redirect_with_filters(selected_start_month, selected_end_month)
            )

        sample_values = {
            "A": Decimal(120),
            "B": Decimal(60),
            "C": Decimal(36),
            "D": Decimal(30),
            "E": Decimal(0),
            "F": Decimal(6),
        }
        try:
            _safe_decimal_formula_eval(formula, sample_values)
        except (ValueError, InvalidOperation):
            messages.error(request, "Formula invalida. Use somente A..F, numeros e + - * /.")
            return redirect(
                _bank_hours_rules_redirect_with_filters(selected_start_month, selected_end_month)
            )

        BankHoursRule.objects.create(
            start_month=start_month_input,
            end_month=end_month_input,
            target_column=target_column,
            formula=formula,
        )
        messages.success(request, "Regra cadastrada com sucesso.")
        return redirect(
            _bank_hours_rules_redirect_with_filters(selected_start_month, selected_end_month)
        )

    filter_column = (request.GET.get("filter_column") or "").strip().upper()
    filter_query = (request.GET.get("q") or "").strip()
    raw_filter_start_month = (request.GET.get("filter_start_month") or "").strip()
    raw_filter_end_month = (request.GET.get("filter_end_month") or "").strip()

    filter_start_month = None
    filter_end_month = None

    if raw_filter_start_month:
        filter_start_month, _, filter_start_error = _resolve_competence_month(raw_filter_start_month)
        if filter_start_error:
            messages.error(request, "Filtro de mes inicial invalido.")
            filter_start_month = None
            raw_filter_start_month = ""
    if raw_filter_end_month:
        filter_end_month, _, filter_end_error = _resolve_competence_month(raw_filter_end_month)
        if filter_end_error:
            messages.error(request, "Filtro de mes final invalido.")
            filter_end_month = None
            raw_filter_end_month = ""

    rules = BankHoursRule.objects.all()
    if filter_column in {"B", "C", "F"}:
        rules = rules.filter(target_column=filter_column)
    if filter_query:
        rules = rules.filter(formula__icontains=filter_query)
    if filter_start_month:
        rules = rules.filter(end_month__gte=filter_start_month)
    if filter_end_month:
        rules = rules.filter(start_month__lte=filter_end_month)
    rules = rules.order_by("-start_month", "target_column", "-id")

    return render(
        request,
        "bank_hours_rules.html",
        {
            "rules": rules,
            "selected_start_month": selected_start_month,
            "selected_end_month": selected_end_month,
            "default_formulas": {"B": "S/Regra", "C": "S/Regra", "F": "S/Regra"},
            "filter_column": filter_column,
            "filter_query": filter_query,
            "filter_start_month": raw_filter_start_month,
            "filter_end_month": raw_filter_end_month,
        },
    )


@require_POST
def bank_hours_rule_delete(request, rule_id):
    start_month = (request.POST.get("start_month") or "").strip()
    end_month = (request.POST.get("end_month") or "").strip()
    rule = get_object_or_404(BankHoursRule, id=rule_id)
    rule.delete()
    messages.success(request, "Regra removida.")
    return redirect(_bank_hours_rules_redirect_with_filters(start_month, end_month))




@require_POST
def employee_create_sector(request):
    nome = (request.POST.get("nome") or "").strip()

    if not nome:
        messages.error(request, "Nome do setor e obrigatorio.")
        return redirect(
            _employees_redirect_with_flags(
                open_employee_modal=1,
                open_sector_modal=1,
            )
        )

    if Sector.objects.filter(nome__iexact=nome, deactivated_at__isnull=True).exists():
        messages.error(request, "Ja existe um setor com esse nome.")
        return redirect(
            _employees_redirect_with_flags(
                open_employee_modal=1,
                open_sector_modal=1,
            )
        )

    sector = Sector.objects.create(nome=nome)
    messages.success(request, "Setor cadastrado com sucesso.")
    return redirect(
        _employees_redirect_with_flags(
            open_employee_modal=1,
            selected_sector=sector.id,
        )
    )


def employee_edit_page(request, employee_id):
    employee = get_object_or_404(
        Employee.objects.select_related("cargo", "sector", "work_schedule"),
        id=employee_id,
    )
    active_cargos = Cargo.objects.filter(deactivated_at__isnull=True).order_by("nome")
    active_sectors = Sector.objects.filter(deactivated_at__isnull=True).order_by("nome")
    work_schedules = WorkSchedule.objects.all().order_by("nome")
    current_cargo = employee.cargo
    current_sector = employee.sector
    allocation_events = EmployeeEvent.objects.filter(
        employee=employee,
        event_type=EmployeeEvent.EVENT_TYPE_ALLOCATION_CHANGE,
    ).select_related(
        "previous_sector",
        "new_sector",
        "previous_work_schedule",
        "new_work_schedule",
    )
    sector_history = [
        event
        for event in allocation_events
        if (
            event.previous_sector_id != event.new_sector_id
            or (event.notes or "").strip()
        )
    ]
    work_schedule_history = [
        event
        for event in allocation_events
        if event.previous_work_schedule_id != event.new_work_schedule_id
    ]
    calendar_exception_types = (
        EmployeeEvent.EVENT_TYPE_DAY_OFF,
        EmployeeEvent.EVENT_TYPE_VACATION,
        EmployeeEvent.EVENT_TYPE_ABSENCE,
    )
    calendar_exception_events = EmployeeEvent.objects.filter(
        employee=employee,
        event_type__in=calendar_exception_types,
    ).order_by("-effective_date", "-created_at", "-id")
    selected_tab = (request.GET.get("tab") or "").strip()
    if selected_tab not in ("info", "cargo-setor", "escala", "calendar-exceptions"):
        selected_tab = "info"

    if request.method == "POST":
        form_type = (request.POST.get("form_type") or "").strip()
        if form_type == "calendar_exception":
            event_type = (request.POST.get("exception_type") or "").strip()
            if event_type not in calendar_exception_types:
                messages.error(request, "Selecione um tipo de excessao valido.")
                return redirect(
                    _employee_edit_redirect_with_tab(employee.id, "calendar-exceptions")
                )

            start_date, end_date, date_error = _parse_special_period_dates(request.POST)
            if date_error:
                messages.error(request, date_error)
                return redirect(
                    _employee_edit_redirect_with_tab(employee.id, "calendar-exceptions")
                )

            closed_month = _find_first_closed_competence_month(start_date, end_date)
            if closed_month:
                messages.error(
                    request,
                    "Nao e permitido registrar evento/ajuste com data em competencia encerrada "
                    f"({_format_competence_month_label(closed_month)}).",
                )
                return redirect(
                    _employee_edit_redirect_with_tab(employee.id, "calendar-exceptions")
                )

            EmployeeEvent.objects.create(
                employee=employee,
                event_type=event_type,
                effective_date=start_date,
                end_date=end_date,
            )
            messages.success(request, "Excessao de calendario registrada com sucesso.")
            return redirect(
                _employee_edit_redirect_with_tab(employee.id, "calendar-exceptions")
            )
        matricula = (request.POST.get("matricula") or "").strip()
        nome_completo = (request.POST.get("nome_completo") or "").strip()
        tipo, regime_compensacao_jornada, characteristics_error = (
            _parse_employee_characteristics(request.POST)
        )
        cargo_id = (request.POST.get("cargo_id") or "").strip()
        sector_id = (request.POST.get("sector_id") or "").strip()
        work_schedule_id = (request.POST.get("work_schedule_id") or "").strip()

        if not matricula or not nome_completo or not cargo_id or not sector_id:
            messages.error(
                request,
                "Matricula, nome completo, cargo e setor sao obrigatorios.",
            )
            return redirect("employee_edit_page", employee_id=employee.id)

        if characteristics_error:
            messages.error(request, characteristics_error)
            return redirect("employee_edit_page", employee_id=employee.id)

        duplicate = Employee.objects.filter(matricula=matricula).exclude(id=employee.id)
        if duplicate.exists():
            messages.error(request, "Ja existe empregado com essa matricula.")
            return redirect("employee_edit_page", employee_id=employee.id)

        cargo = active_cargos.filter(id=cargo_id).first()
        if (
            not cargo
            and current_cargo
            and current_cargo.deactivated_at
            and str(current_cargo.id) == cargo_id
        ):
            cargo = current_cargo

        if not cargo:
            messages.error(request, "Selecione um cargo valido.")
            return redirect("employee_edit_page", employee_id=employee.id)

        sector = active_sectors.filter(id=sector_id).first()
        if (
            not sector
            and current_sector
            and current_sector.deactivated_at
            and str(current_sector.id) == sector_id
        ):
            sector = current_sector

        if not sector:
            messages.error(request, "Selecione um setor valido.")
            return redirect("employee_edit_page", employee_id=employee.id)

        work_schedule, schedule_error = _get_work_schedule_or_error(work_schedule_id)
        if schedule_error:
            messages.error(request, schedule_error)
            return redirect("employee_edit_page", employee_id=employee.id)

        previous_tipo = employee.tipo
        previous_cargo = employee.cargo
        previous_sector = employee.sector
        previous_work_schedule = employee.work_schedule
        previous_cargo_id = previous_cargo.id if previous_cargo else None
        previous_sector_id = previous_sector.id if previous_sector else None
        previous_work_schedule_id = (
            previous_work_schedule.id if previous_work_schedule else None
        )
        next_cargo_id = cargo.id if cargo else None
        next_sector_id = sector.id if sector else None
        next_work_schedule_id = work_schedule.id if work_schedule else None

        cargo_changed = previous_cargo_id != next_cargo_id
        sector_changed = previous_sector_id != next_sector_id
        work_schedule_changed = previous_work_schedule_id != next_work_schedule_id
        tipo_changed = previous_tipo != tipo
        has_allocation_change = (
            cargo_changed or sector_changed or work_schedule_changed or tipo_changed
        )

        effective_date = None
        if has_allocation_change:
            raw_effective_date = (request.POST.get("change_effective_date") or "").strip()
            if not raw_effective_date:
                messages.error(
                    request,
                    "Informe a data de vigencia para alteracao de setor/escala.",
                )
                return redirect("employee_edit_page", employee_id=employee.id)

            try:
                effective_date = date.fromisoformat(raw_effective_date)
            except ValueError:
                messages.error(request, "Informe uma data de vigencia valida.")
                return redirect("employee_edit_page", employee_id=employee.id)

            minimum_effective_date = timezone.localdate() - timedelta(days=30)
            if effective_date < minimum_effective_date:
                messages.error(
                    request,
                    "Nao e permitido registrar alteracoes de cargo/setor/escala com vigencia superior a 30 dias no passado.",
                )
                return redirect("employee_edit_page", employee_id=employee.id)

        if has_allocation_change and effective_date:
            closed_month = _find_first_closed_competence_month(effective_date)
            if closed_month:
                messages.error(
                    request,
                    "Nao e permitido registrar ajuste retroativo com vigencia em competencia encerrada "
                    f"({_format_competence_month_label(closed_month)}).",
                )
                return redirect("employee_edit_page", employee_id=employee.id)
        employee.matricula = matricula
        employee.nome_completo = nome_completo
        employee.tipo = tipo
        employee.regime_compensacao_jornada = regime_compensacao_jornada
        employee.cargo = cargo
        employee.sector = sector
        employee.work_schedule = work_schedule
        employee.save(
            update_fields=[
                "matricula",
                "nome_completo",
                "tipo",
                "regime_compensacao_jornada",
                "cargo",
                "sector",
                "work_schedule",
            ]
        )

        if has_allocation_change and effective_date:
            change_notes_parts = []
            if cargo_changed:
                previous_cargo_label = previous_cargo.nome if previous_cargo else "Sem cargo"
                next_cargo_label = cargo.nome if cargo else "Sem cargo"
                change_notes_parts.append(
                    f"Cargo: {previous_cargo_label} -> {next_cargo_label}"
                )
            if tipo_changed:
                change_notes_parts.append(f"Tipo: {previous_tipo} -> {tipo}")

            EmployeeEvent.objects.create(
                employee=employee,
                event_type=EmployeeEvent.EVENT_TYPE_ALLOCATION_CHANGE,
                effective_date=effective_date,
                notes=" | ".join(change_notes_parts),
                previous_sector=previous_sector,
                new_sector=sector,
                previous_work_schedule=previous_work_schedule,
                new_work_schedule=work_schedule,
            )

        messages.success(request, "Empregado atualizado com sucesso.")
        return redirect("employee_edit_page", employee_id=employee.id)

    return render(
        request,
        "employee_edit.html",
        {
            "employee": employee,
            "active_cargos": active_cargos,
            "active_sectors": active_sectors,
            "work_schedules": work_schedules,
            "sector_history": sector_history,
            "work_schedule_history": work_schedule_history,
            "employee_type_choices": Employee.TYPE_CHOICES,
            "compensation_regime_choices": Employee.REGIME_COMPENSACAO_JORNADA_CHOICES,
            "calendar_exception_events": calendar_exception_events,
            "selected_tab": selected_tab,
        },
    )


@require_POST
def employee_deactivate(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id, deactivated_at__isnull=True)
    employee.deactivated_at = timezone.now()
    employee.save(update_fields=["deactivated_at"])
    messages.success(request, "Empregado desativado com sucesso.")
    return redirect("employees_page")


@require_POST
def employee_activate(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id, deactivated_at__isnull=False)
    employee.deactivated_at = None
    employee.save(update_fields=["deactivated_at"])
    messages.success(request, "Empregado ativado com sucesso.")
    return redirect("employees_page")


def cargos_page(request):
    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip()

        if not nome:
            messages.error(request, "Nome do cargo e obrigatorio.")
            return redirect("cargos_page")

        if Cargo.objects.filter(nome__iexact=nome, deactivated_at__isnull=True).exists():
            messages.error(request, "Ja existe um cargo com esse nome.")
            return redirect("cargos_page")

        Cargo.objects.create(nome=nome)
        messages.success(request, "Cargo cadastrado com sucesso.")
        return redirect("cargos_page")

    cargos = (
        Cargo.objects.annotate(employee_count=Count("employees"))
        .order_by("deactivated_at", "nome")
    )
    active_count = cargos.filter(deactivated_at__isnull=True).count()
    deactivated_count = cargos.filter(deactivated_at__isnull=False).count()
    return render(
        request,
        "cargos.html",
        {
            "cargos": cargos,
            "active_count": active_count,
            "deactivated_count": deactivated_count,
        },
    )


def cargo_edit_page(request, cargo_id):
    cargo = get_object_or_404(Cargo, id=cargo_id, deactivated_at__isnull=True)

    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip()

        if not nome:
            messages.error(request, "Nome do cargo e obrigatorio.")
            return redirect("cargo_edit_page", cargo_id=cargo.id)

        duplicate = Cargo.objects.filter(
            nome__iexact=nome,
            deactivated_at__isnull=True,
        ).exclude(id=cargo.id)
        if duplicate.exists():
            messages.error(request, "Ja existe um cargo com esse nome.")
            return redirect("cargo_edit_page", cargo_id=cargo.id)

        cargo.nome = nome
        cargo.save(update_fields=["nome"])
        messages.success(request, "Cargo atualizado com sucesso.")
        return redirect("cargos_page")

    return render(request, "cargo_edit.html", {"cargo": cargo})


@require_POST
def cargo_deactivate(request, cargo_id):
    cargo = get_object_or_404(Cargo, id=cargo_id, deactivated_at__isnull=True)
    cargo.deactivated_at = timezone.now()
    cargo.save(update_fields=["deactivated_at"])
    messages.success(request, "Cargo desativado com sucesso.")
    return redirect("cargos_page")


@require_POST
def cargo_activate(request, cargo_id):
    cargo = get_object_or_404(Cargo, id=cargo_id, deactivated_at__isnull=False)
    cargo.deactivated_at = None
    cargo.save(update_fields=["deactivated_at"])
    messages.success(request, "Cargo ativado com sucesso.")
    return redirect("cargos_page")


def sectors_page(request):
    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip()

        if not nome:
            messages.error(request, "Nome do setor e obrigatorio.")
            return redirect("sectors_page")

        if Sector.objects.filter(nome__iexact=nome, deactivated_at__isnull=True).exists():
            messages.error(request, "Ja existe um setor com esse nome.")
            return redirect("sectors_page")

        Sector.objects.create(nome=nome)
        messages.success(request, "Setor cadastrado com sucesso.")
        return redirect("sectors_page")

    sectors = Sector.objects.all().order_by("deactivated_at", "nome")
    active_count = sectors.filter(deactivated_at__isnull=True).count()
    deactivated_count = sectors.filter(deactivated_at__isnull=False).count()
    return render(
        request,
        "sectors.html",
        {
            "sectors": sectors,
            "active_count": active_count,
            "deactivated_count": deactivated_count,
        },
    )


def work_schedules_page(request):
    if request.method == "POST":
        form_type = (request.POST.get("form_type") or "work_schedule").strip()

        if form_type == "calendar":
            calendar_name = (request.POST.get("calendar_name") or "").strip()
            if not calendar_name:
                messages.error(request, "Nome do calendario e obrigatorio.")
                return redirect("work_schedules_page")

            if WorkCalendar.objects.filter(nome__iexact=calendar_name).exists():
                messages.error(request, "Ja existe um calendario com esse nome.")
                return redirect("work_schedules_page")

            WorkCalendar.objects.create(nome=calendar_name)
            messages.success(request, "Calendario cadastrado com sucesso.")
            return redirect("work_schedules_page")

        if form_type == "special_period":
            calendar_id = (request.POST.get("calendar_id") or "").strip()
            calendar, calendar_error = _get_work_calendar_or_error(calendar_id)
            if calendar_error:
                messages.error(request, calendar_error)
                return redirect("work_schedules_page")

            latest_closure = _get_latest_closure_for_calendar(calendar.id)
            if latest_closure:
                month_label = _format_competence_month_label(latest_closure.competence_month)
                messages.error(
                    request,
                    f"Nao e permitido alterar este calendario, pois ele ja foi usado em mes fechado ({month_label}). Crie um novo calendario.",
                )
                return redirect("work_schedules_page")

            period_type = (request.POST.get("period_type") or "").strip()
            valid_types = {choice for choice, _ in WorkCalendarPeriod.TYPE_CHOICES}
            if period_type not in valid_types:
                messages.error(request, "Selecione um tipo valido de periodo.")
                return redirect("work_schedules_page")

            start_date, end_date, date_error = _parse_special_period_dates(request.POST)
            if date_error:
                messages.error(request, date_error)
                return redirect("work_schedules_page")

            today = timezone.localdate()
            if start_date < today or end_date < today:
                messages.error(
                    request,
                    "Nao e permitido incluir excecoes com datas que ja passaram.",
                )
                return redirect("work_schedules_page")

            description = (request.POST.get("description") or "").strip()

            WorkCalendarPeriod.objects.create(
                calendar=calendar,
                period_type=period_type,
                start_date=start_date,
                end_date=end_date,
                description=description,
            )
            messages.success(request, "Periodo especial cadastrado com sucesso.")
            return redirect("work_schedules_page")

        if form_type == "work_schedule_edit":
            work_schedule_id = (request.POST.get("work_schedule_id") or "").strip()
            work_schedule = WorkSchedule.objects.filter(id=work_schedule_id).first()
            if not work_schedule:
                messages.error(request, "Selecione uma escala valida.")
                return redirect("work_schedules_page")

            latest_closure = _get_latest_closure_for_schedule(work_schedule.id)
            if latest_closure:
                month_label = _format_competence_month_label(latest_closure.competence_month)
                messages.error(
                    request,
                    f"Nao e permitido alterar esta escala, pois ela ja foi usada em mes fechado ({month_label}). Crie uma nova escala.",
                )
                return redirect("work_schedules_page")

            nome = (request.POST.get("nome") or "").strip()
            if not nome:
                messages.error(request, "Nome da escala e obrigatorio.")
                return redirect("work_schedules_page")

            duplicate = WorkSchedule.objects.filter(nome__iexact=nome).exclude(
                id=work_schedule.id
            )
            if duplicate.exists():
                messages.error(request, "Ja existe uma escala com esse nome.")
                return redirect("work_schedules_page")

            calendar_id = (request.POST.get("calendar_id") or "").strip()
            calendar, calendar_error = _get_work_calendar_or_error(calendar_id)
            if calendar_error:
                messages.error(request, calendar_error)
                return redirect("work_schedules_page")

            daily_hours, error = _parse_daily_hours(request.POST)
            if error:
                messages.error(request, error)
                return redirect("work_schedules_page")

            work_schedule.nome = nome
            work_schedule.calendar = calendar
            for field_name, _ in WEEKDAY_HOUR_FIELDS:
                setattr(work_schedule, field_name, daily_hours[field_name])
            work_schedule.save(
                update_fields=[
                    "nome",
                    "calendar",
                    *SCHEDULE_FIELDS_IN_WEEKDAY_ORDER,
                ]
            )
            messages.success(request, "Escala atualizada com sucesso.")
            return redirect("work_schedules_page")

        nome = (request.POST.get("nome") or "").strip()

        if not nome:
            messages.error(request, "Nome da escala e obrigatorio.")
            return redirect("work_schedules_page")

        if WorkSchedule.objects.filter(nome__iexact=nome).exists():
            messages.error(request, "Ja existe uma escala com esse nome.")
            return redirect("work_schedules_page")

        calendar_id = (request.POST.get("calendar_id") or "").strip()
        calendar, calendar_error = _get_work_calendar_or_error(calendar_id)
        if calendar_error:
            messages.error(request, calendar_error)
            return redirect("work_schedules_page")

        daily_hours, error = _parse_daily_hours(request.POST)
        if error:
            messages.error(request, error)
            return redirect("work_schedules_page")

        WorkSchedule.objects.create(nome=nome, calendar=calendar, **daily_hours)
        messages.success(request, "Escala cadastrada com sucesso.")
        return redirect("work_schedules_page")

    work_schedules = WorkSchedule.objects.select_related("calendar").order_by("nome")
    work_calendars = WorkCalendar.objects.all().order_by("nome")

    selected_calendar_id = (request.GET.get("calendar_id") or "").strip()
    selected_calendar = None
    if selected_calendar_id:
        selected_calendar = work_calendars.filter(id=selected_calendar_id).first()

    all_special_periods = WorkCalendarPeriod.objects.select_related("calendar").order_by(
        "start_date",
        "end_date",
        "id",
    )
    if selected_calendar:
        all_special_periods = all_special_periods.filter(calendar=selected_calendar)
    else:
        all_special_periods = all_special_periods.none()

    today = timezone.localdate()
    old_period_cutoff = today - timedelta(days=60)
    recent_special_periods = all_special_periods.filter(end_date__gte=old_period_cutoff)
    old_special_periods = all_special_periods.filter(end_date__lt=old_period_cutoff)

    return render(
        request,
        "work_schedules.html",
        {
            "work_schedules": work_schedules,
            "work_calendars": work_calendars,
            "recent_special_periods": recent_special_periods,
            "old_special_periods": old_special_periods,
            "selected_calendar": selected_calendar,
            "selected_calendar_id": str(selected_calendar.id) if selected_calendar else "",
            "today": today,
            "today_iso": today.isoformat(),
            "old_period_cutoff": old_period_cutoff,
        },
    )


def sector_edit_page(request, sector_id):
    sector = get_object_or_404(Sector, id=sector_id, deactivated_at__isnull=True)

    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip()

        if not nome:
            messages.error(request, "Nome do setor e obrigatorio.")
            return redirect("sector_edit_page", sector_id=sector.id)

        duplicate = Sector.objects.filter(
            nome__iexact=nome,
            deactivated_at__isnull=True,
        ).exclude(id=sector.id)
        if duplicate.exists():
            messages.error(request, "Ja existe um setor com esse nome.")
            return redirect("sector_edit_page", sector_id=sector.id)

        sector.nome = nome
        sector.save(update_fields=["nome"])
        messages.success(request, "Setor atualizado com sucesso.")
        return redirect("sectors_page")

    return render(request, "sector_edit.html", {"sector": sector})


@require_POST
def sector_deactivate(request, sector_id):
    sector = get_object_or_404(Sector, id=sector_id, deactivated_at__isnull=True)
    sector.deactivated_at = timezone.now()
    sector.save(update_fields=["deactivated_at"])
    messages.success(request, "Setor desativado com sucesso.")
    return redirect("sectors_page")


@require_POST
def sector_activate(request, sector_id):
    sector = get_object_or_404(Sector, id=sector_id, deactivated_at__isnull=False)
    sector.deactivated_at = None
    sector.save(update_fields=["deactivated_at"])
    messages.success(request, "Setor ativado com sucesso.")
    return redirect("sectors_page")







