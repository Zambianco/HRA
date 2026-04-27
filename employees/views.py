from calendar import monthrange
from urllib.parse import urlencode
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, timedelta

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Employee,
    EmployeeEvent,
    EmployeeTimeEntry,
    TimesheetMonthClosure,
    TimesheetMonthClosureCalendarPeriodSnapshot,
    TimesheetMonthClosureEmployeeEventSnapshot,
    TimesheetMonthClosureWorkScheduleSnapshot,
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
    normalized_value = (raw_value or "").strip().replace(",", ".")
    if not normalized_value:
        return 0, None

    if not normalized_value.isdigit():
        return None, f'Valor invalido para "{field_label}".'

    value = int(normalized_value)
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
    work_schedules = WorkSchedule.objects.all().order_by("nome")
    all_sectors = Sector.objects.all().order_by("deactivated_at", "nome")

    if request.method == "POST":
        matricula = (request.POST.get("matricula") or "").strip()
        nome_completo = (request.POST.get("nome_completo") or "").strip()
        tipo, regime_compensacao_jornada, characteristics_error = (
            _parse_employee_characteristics(request.POST)
        )
        sector_id = (request.POST.get("sector_id") or "").strip()
        work_schedule_id = (request.POST.get("work_schedule_id") or "").strip()

        if not matricula or not nome_completo or not sector_id:
            messages.error(request, "Matricula, nome completo e setor sao obrigatorios.")
            return redirect("employees_page")

        if characteristics_error:
            messages.error(request, characteristics_error)
            return redirect("employees_page")

        if Employee.objects.filter(matricula=matricula).exists():
            messages.error(request, "Ja existe empregado com essa matricula.")
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
            sector=sector,
            work_schedule=work_schedule,
        )

        messages.success(request, "Empregado cadastrado com sucesso.")
        return redirect("employees_page")

    employees = Employee.objects.select_related("sector", "work_schedule").order_by(
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


def _get_month_date_range(month_start):
    _, days_in_month = monthrange(month_start.year, month_start.month)
    month_end = date(month_start.year, month_start.month, days_in_month)
    return month_start, month_end


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
                # Raw delete avoids related-object cascade traversal in inconsistent schemas.
                closure_qs._raw_delete(closure_qs.db)
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
        Employee.objects.select_related("sector", "work_schedule"),
        id=employee_id,
    )
    active_sectors = Sector.objects.filter(deactivated_at__isnull=True).order_by("nome")
    work_schedules = WorkSchedule.objects.all().order_by("nome")
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
        sector_id = (request.POST.get("sector_id") or "").strip()
        work_schedule_id = (request.POST.get("work_schedule_id") or "").strip()

        if not matricula or not nome_completo or not sector_id:
            messages.error(request, "Matricula, nome completo e setor sao obrigatorios.")
            return redirect("employee_edit_page", employee_id=employee.id)

        if characteristics_error:
            messages.error(request, characteristics_error)
            return redirect("employee_edit_page", employee_id=employee.id)

        duplicate = Employee.objects.filter(matricula=matricula).exclude(id=employee.id)
        if duplicate.exists():
            messages.error(request, "Ja existe empregado com essa matricula.")
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
        previous_sector = employee.sector
        previous_work_schedule = employee.work_schedule
        previous_sector_id = previous_sector.id if previous_sector else None
        previous_work_schedule_id = (
            previous_work_schedule.id if previous_work_schedule else None
        )
        next_sector_id = sector.id if sector else None
        next_work_schedule_id = work_schedule.id if work_schedule else None

        sector_changed = previous_sector_id != next_sector_id
        work_schedule_changed = previous_work_schedule_id != next_work_schedule_id
        tipo_changed = previous_tipo != tipo
        has_allocation_change = sector_changed or work_schedule_changed or tipo_changed

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
        employee.sector = sector
        employee.work_schedule = work_schedule
        employee.save(
            update_fields=[
                "matricula",
                "nome_completo",
                "tipo",
                "regime_compensacao_jornada",
                "sector",
                "work_schedule",
            ]
        )

        if has_allocation_change and effective_date:
            change_notes = ""
            if tipo_changed:
                change_notes = f"Cargo (tipo): {previous_tipo} -> {tipo}"

            EmployeeEvent.objects.create(
                employee=employee,
                event_type=EmployeeEvent.EVENT_TYPE_ALLOCATION_CHANGE,
                effective_date=effective_date,
                notes=change_notes,
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







