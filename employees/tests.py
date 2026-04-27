from datetime import date, timedelta
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

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


class EmployeeViewTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.url = reverse("employees_page")

    def test_get_employees_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_create_employee(self):
        active_sector = Sector.objects.create(nome="RH")
        response = self.client.post(
            self.url,
            data={
                "matricula": "1001",
                "nome_completo": "Teste RH",
                "tipo": Employee.TYPE_DIRETO,
                "regime_compensacao_jornada": Employee.REGIME_COMPENSACAO_PARTICIPANTE,
                "sector_id": str(active_sector.id),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Employee.objects.count(), 1)
        self.assertEqual(Employee.objects.first().sector, active_sector)
        self.assertEqual(Employee.objects.first().tipo, Employee.TYPE_DIRETO)
        self.assertEqual(
            Employee.objects.first().regime_compensacao_jornada,
            Employee.REGIME_COMPENSACAO_PARTICIPANTE,
        )
        self.assertIsNone(Employee.objects.first().work_schedule)
        self.assertIsNone(Employee.objects.first().deactivated_at)

    def test_create_employee_with_work_schedule(self):
        active_sector = Sector.objects.create(nome="RH")
        work_schedule = WorkSchedule.objects.create(
            nome="Escala ADM",
            horas_segunda="8.00",
            horas_terca="8.00",
            horas_quarta="8.00",
            horas_quinta="8.00",
            horas_sexta="8.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )
        response = self.client.post(
            self.url,
            data={
                "matricula": "1001A",
                "nome_completo": "Teste com Escala",
                "tipo": Employee.TYPE_INDIRETO,
                "regime_compensacao_jornada": Employee.REGIME_COMPENSACAO_NAO_PARTICIPANTE,
                "sector_id": str(active_sector.id),
                "work_schedule_id": str(work_schedule.id),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Employee.objects.count(), 1)
        self.assertEqual(Employee.objects.first().work_schedule, work_schedule)
        self.assertEqual(Employee.objects.first().tipo, Employee.TYPE_INDIRETO)

    def test_duplicate_matricula(self):
        active_sector = Sector.objects.create(nome="RH")
        Employee.objects.create(
            matricula="1001",
            nome_completo="Primeiro",
            sector=active_sector,
        )
        response = self.client.post(
            self.url,
            data={
                "matricula": "1001",
                "nome_completo": "Duplicado",
                "tipo": Employee.TYPE_DIRETO,
                "regime_compensacao_jornada": Employee.REGIME_COMPENSACAO_NAO_PARTICIPANTE,
                "sector_id": str(active_sector.id),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Employee.objects.count(), 1)
        self.assertContains(response, "Ja existe empregado com essa matricula.")

    def test_create_employee_requires_active_sector(self):
        inactive_sector = Sector.objects.create(nome="TI", deactivated_at=timezone.now())
        response = self.client.post(
            self.url,
            data={
                "matricula": "1002",
                "nome_completo": "Sem Setor Ativo",
                "tipo": Employee.TYPE_DIRETO,
                "regime_compensacao_jornada": Employee.REGIME_COMPENSACAO_PARTICIPANTE,
                "sector_id": str(inactive_sector.id),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Employee.objects.count(), 0)
        self.assertContains(response, "Selecione um setor ativo valido.")

    def test_create_sector_from_employee_page(self):
        response = self.client.post(
            reverse("employee_create_sector"),
            data={"nome": "Operacoes"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Sector.objects.filter(nome="Operacoes").exists())
        self.assertContains(response, "Setor cadastrado com sucesso.")
        self.assertEqual(response.request["PATH_INFO"], reverse("employees_page"))
        self.assertIn("open_employee_modal=1", response.request.get("QUERY_STRING", ""))

    def test_duplicate_sector_from_employee_page(self):
        Sector.objects.create(nome="Operacoes")
        response = self.client.post(
            reverse("employee_create_sector"),
            data={"nome": "operacoes"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Sector.objects.filter(nome__iexact="Operacoes").count(), 1)
        self.assertContains(response, "Ja existe um setor com esse nome.")
        self.assertEqual(response.request["PATH_INFO"], reverse("employees_page"))
        self.assertIn("open_sector_modal=1", response.request.get("QUERY_STRING", ""))

    def test_deactivate_employee_via_page(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="2001",
            nome_completo="Empregado Ativo",
            sector=sector,
        )
        response = self.client.post(
            reverse("employee_deactivate", kwargs={"employee_id": employee.id}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        employee.refresh_from_db()
        self.assertIsNotNone(employee.deactivated_at)
        self.assertContains(response, "Empregado desativado com sucesso.")

    def test_activate_employee_via_page(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="2002",
            nome_completo="Empregado Inativo",
            sector=sector,
            deactivated_at=timezone.now(),
        )
        response = self.client.post(
            reverse("employee_activate", kwargs={"employee_id": employee.id}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        employee.refresh_from_db()
        self.assertIsNone(employee.deactivated_at)
        self.assertContains(response, "Empregado ativado com sucesso.")

    def test_get_employee_edit_page(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="3001",
            nome_completo="Editar Empregado",
            sector=sector,
        )
        response = self.client.get(
            reverse("employee_edit_page", kwargs={"employee_id": employee.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Editar Empregado")
        self.assertContains(response, employee.matricula)
        self.assertContains(response, "Excessoes de calendario")

    def test_create_calendar_exception_via_employee_edit_page(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="3001EX",
            nome_completo="Editar com Excecao",
            sector=sector,
        )

        response = self.client.post(
            reverse("employee_edit_page", kwargs={"employee_id": employee.id}),
            data={
                "form_type": "calendar_exception",
                "exception_type": EmployeeEvent.EVENT_TYPE_VACATION,
                "start_date": "2026-05-01",
                "end_date": "2026-05-10",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmployeeEvent.objects.count(), 1)
        event = EmployeeEvent.objects.first()
        self.assertEqual(event.employee, employee)
        self.assertEqual(event.event_type, EmployeeEvent.EVENT_TYPE_VACATION)
        self.assertEqual(str(event.effective_date), "2026-05-01")
        self.assertEqual(str(event.end_date), "2026-05-10")
        self.assertContains(response, "Excessao de calendario registrada com sucesso.")
        self.assertEqual(response.request["PATH_INFO"], reverse("employee_edit_page", kwargs={"employee_id": employee.id}))
        self.assertIn("tab=calendar-exceptions", response.request.get("QUERY_STRING", ""))

    def test_create_calendar_exception_rejects_invalid_type(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="3001EX2",
            nome_completo="Tipo Invalido",
            sector=sector,
        )

        response = self.client.post(
            reverse("employee_edit_page", kwargs={"employee_id": employee.id}),
            data={
                "form_type": "calendar_exception",
                "exception_type": EmployeeEvent.EVENT_TYPE_MEDICAL_CERTIFICATE,
                "start_date": "2026-05-01",
                "end_date": "2026-05-10",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmployeeEvent.objects.count(), 0)
        self.assertContains(response, "Selecione um tipo de excessao valido.")

    def test_create_calendar_exception_rejects_end_date_before_start_date(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="3001EX3",
            nome_completo="Periodo Invalido",
            sector=sector,
        )

        response = self.client.post(
            reverse("employee_edit_page", kwargs={"employee_id": employee.id}),
            data={
                "form_type": "calendar_exception",
                "exception_type": EmployeeEvent.EVENT_TYPE_DAY_OFF,
                "start_date": "2026-05-10",
                "end_date": "2026-05-01",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmployeeEvent.objects.count(), 0)
        self.assertContains(response, "A data de fim deve ser maior ou igual a data de inicio.")

    def test_edit_employee_via_page(self):
        sector_a = Sector.objects.create(nome="RH")
        sector_b = Sector.objects.create(nome="Financeiro")
        work_schedule = WorkSchedule.objects.create(
            nome="Escala 12x36",
            horas_segunda="12.00",
            horas_terca="0.00",
            horas_quarta="12.00",
            horas_quinta="0.00",
            horas_sexta="12.00",
            horas_sabado="0.00",
            horas_domingo="12.00",
        )
        employee = Employee.objects.create(
            matricula="3002",
            nome_completo="Nome Antigo",
            sector=sector_a,
        )
        response = self.client.post(
            reverse("employee_edit_page", kwargs={"employee_id": employee.id}),
            data={
                "matricula": "3002A",
                "nome_completo": "Nome Novo",
                "tipo": Employee.TYPE_INDIRETO,
                "regime_compensacao_jornada": Employee.REGIME_COMPENSACAO_PARTICIPANTE,
                "sector_id": str(sector_b.id),
                "work_schedule_id": str(work_schedule.id),
                "change_effective_date": "2026-04-24",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        employee.refresh_from_db()
        self.assertEqual(employee.matricula, "3002A")
        self.assertEqual(employee.nome_completo, "Nome Novo")
        self.assertEqual(employee.tipo, Employee.TYPE_INDIRETO)
        self.assertEqual(
            employee.regime_compensacao_jornada,
            Employee.REGIME_COMPENSACAO_PARTICIPANTE,
        )
        self.assertEqual(employee.sector, sector_b)
        self.assertEqual(employee.work_schedule, work_schedule)
        self.assertContains(response, "Empregado atualizado com sucesso.")
        self.assertEqual(EmployeeEvent.objects.count(), 1)
        event = EmployeeEvent.objects.first()
        self.assertEqual(event.employee, employee)
        self.assertEqual(event.event_type, EmployeeEvent.EVENT_TYPE_ALLOCATION_CHANGE)
        self.assertEqual(event.previous_sector, sector_a)
        self.assertEqual(event.new_sector, sector_b)
        self.assertIsNone(event.previous_work_schedule)
        self.assertEqual(event.new_work_schedule, work_schedule)

    def test_edit_employee_requires_effective_date_when_sector_changes(self):
        sector_a = Sector.objects.create(nome="RH")
        sector_b = Sector.objects.create(nome="Financeiro")
        employee = Employee.objects.create(
            matricula="3002B",
            nome_completo="Sem Data de Vigencia",
            sector=sector_a,
        )

        response = self.client.post(
            reverse("employee_edit_page", kwargs={"employee_id": employee.id}),
            data={
                "matricula": "3002B",
                "nome_completo": "Sem Data de Vigencia",
                "tipo": Employee.TYPE_DIRETO,
                "regime_compensacao_jornada": Employee.REGIME_COMPENSACAO_PARTICIPANTE,
                "sector_id": str(sector_b.id),
                "work_schedule_id": "",
                "change_effective_date": "",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        employee.refresh_from_db()
        self.assertEqual(employee.sector, sector_a)
        self.assertContains(
            response,
            "Informe a data de vigencia para alteracao de setor/escala.",
        )
        self.assertEqual(EmployeeEvent.objects.count(), 0)

    def test_edit_employee_rejects_effective_date_older_than_30_days(self):
        sector_a = Sector.objects.create(nome="RH")
        sector_b = Sector.objects.create(nome="Financeiro")
        employee = Employee.objects.create(
            matricula="3002B30",
            nome_completo="Data Antiga",
            sector=sector_a,
        )

        old_date = timezone.localdate() - timedelta(days=31)
        response = self.client.post(
            reverse("employee_edit_page", kwargs={"employee_id": employee.id}),
            data={
                "matricula": "3002B30",
                "nome_completo": "Data Antiga",
                "tipo": Employee.TYPE_DIRETO,
                "regime_compensacao_jornada": Employee.REGIME_COMPENSACAO_PARTICIPANTE,
                "sector_id": str(sector_b.id),
                "work_schedule_id": "",
                "change_effective_date": old_date.isoformat(),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        employee.refresh_from_db()
        self.assertEqual(employee.sector, sector_a)
        self.assertContains(
            response,
            "Nao e permitido registrar alteracoes de cargo/setor/escala com vigencia superior a 30 dias no passado.",
        )
        self.assertEqual(EmployeeEvent.objects.count(), 0)

    def test_edit_employee_rejects_effective_date_in_closed_competence_month(self):
        sector_a = Sector.objects.create(nome="RH")
        sector_b = Sector.objects.create(nome="Financeiro")
        employee = Employee.objects.create(
            matricula="3002BLOCK",
            nome_completo="Mes Fechado",
            sector=sector_a,
        )
        TimesheetMonthClosure.objects.create(competence_month="2026-04-01")

        response = self.client.post(
            reverse("employee_edit_page", kwargs={"employee_id": employee.id}),
            data={
                "matricula": "3002BLOCK",
                "nome_completo": "Mes Fechado",
                "tipo": Employee.TYPE_DIRETO,
                "regime_compensacao_jornada": Employee.REGIME_COMPENSACAO_PARTICIPANTE,
                "sector_id": str(sector_b.id),
                "work_schedule_id": "",
                "change_effective_date": "2026-04-24",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        employee.refresh_from_db()
        self.assertEqual(employee.sector, sector_a)
        self.assertContains(response, "vigencia em competencia encerrada")
        self.assertEqual(EmployeeEvent.objects.count(), 0)
    def test_edit_employee_allows_update_without_effective_date_when_no_allocation_change(self):
        sector = Sector.objects.create(nome="RH")
        work_schedule = WorkSchedule.objects.create(
            nome="Escala ADM",
            horas_segunda="8.00",
            horas_terca="8.00",
            horas_quarta="8.00",
            horas_quinta="8.00",
            horas_sexta="8.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )
        employee = Employee.objects.create(
            matricula="3002C",
            nome_completo="Nome Atual",
            sector=sector,
            work_schedule=work_schedule,
        )

        response = self.client.post(
            reverse("employee_edit_page", kwargs={"employee_id": employee.id}),
            data={
                "matricula": "3002C",
                "nome_completo": "Nome Atualizado",
                "tipo": Employee.TYPE_DIRETO,
                "regime_compensacao_jornada": Employee.REGIME_COMPENSACAO_NAO_PARTICIPANTE,
                "sector_id": str(sector.id),
                "work_schedule_id": str(work_schedule.id),
                "change_effective_date": "",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        employee.refresh_from_db()
        self.assertEqual(employee.nome_completo, "Nome Atualizado")
        self.assertEqual(employee.sector, sector)
        self.assertEqual(employee.work_schedule, work_schedule)
        self.assertContains(response, "Empregado atualizado com sucesso.")
        self.assertEqual(EmployeeEvent.objects.count(), 0)

    def test_employees_page_actions_are_edit_and_events(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="3003",
            nome_completo="Acoes da Tabela",
            sector=sector,
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("employee_edit_page", kwargs={"employee_id": employee.id}),
        )
        self.assertContains(
            response,
            f"{reverse('events_page')}?employee_id={employee.id}",
        )
        self.assertNotContains(
            response,
            reverse("employee_deactivate", kwargs={"employee_id": employee.id}),
        )
        self.assertNotContains(
            response,
            reverse("employee_activate", kwargs={"employee_id": employee.id}),
        )

    def test_events_page(self):
        response = self.client.get(reverse("events_page"))
        self.assertEqual(response.status_code, 200)

    def test_create_event_via_events_page(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="3004A",
            nome_completo="Evento Manual",
            sector=sector,
        )
        response = self.client.post(
            reverse("events_page"),
            data={
                "employee_id": str(employee.id),
                "event_type": EmployeeEvent.EVENT_TYPE_ABSENCE,
                "effective_date": "2026-04-24",
                "end_date": "2026-04-25",
                "notes": "Ausencia justificada",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmployeeEvent.objects.count(), 1)
        event = EmployeeEvent.objects.first()
        self.assertEqual(event.employee, employee)
        self.assertEqual(event.event_type, EmployeeEvent.EVENT_TYPE_ABSENCE)
        self.assertEqual(str(event.effective_date), "2026-04-24")
        self.assertEqual(str(event.end_date), "2026-04-25")
        self.assertEqual(event.notes, "Ausencia justificada")
        self.assertContains(response, "Evento registrado com sucesso.")

    def test_create_event_is_blocked_when_competence_month_is_closed(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="3004ALOCK",
            nome_completo="Evento Bloqueado",
            sector=sector,
        )
        TimesheetMonthClosure.objects.create(competence_month="2026-04-01")

        response = self.client.post(
            reverse("events_page"),
            data={
                "employee_id": str(employee.id),
                "event_type": EmployeeEvent.EVENT_TYPE_ABSENCE,
                "effective_date": "2026-04-24",
                "end_date": "2026-04-25",
                "notes": "Tentativa bloqueada",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmployeeEvent.objects.count(), 0)
        self.assertContains(response, "competencia encerrada")
    def test_create_bank_hours_event_requires_amount(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="3004B",
            nome_completo="Banco de Horas",
            sector=sector,
        )
        response = self.client.post(
            reverse("events_page"),
            data={
                "employee_id": str(employee.id),
                "event_type": EmployeeEvent.EVENT_TYPE_BANK_HOURS_MOVEMENT,
                "effective_date": "2026-04-24",
                "end_date": "",
                "bank_hours_amount": "",
                "notes": "Lancamento sem valor",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmployeeEvent.objects.count(), 0)
        self.assertContains(
            response,
            "Informe o valor em horas para movimento de banco de horas.",
        )

    def test_absences_legacy_url_redirects_to_events(self):
        response = self.client.get("/ausencias/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], reverse("events_page"))

    def test_absences_legacy_url_preserves_query_string(self):
        response = self.client.get("/ausencias/?employee_id=123")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], f"{reverse('events_page')}?employee_id=123")

    def test_events_page_with_employee_query(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="3004",
            nome_completo="Evento Vinculado",
            sector=sector,
        )
        response = self.client.get(f"{reverse('events_page')}?employee_id={employee.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, employee.nome_completo)

    def test_get_timesheet_page(self):
        response = self.client.get(reverse("timesheet_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Timesheet Mensal")

    def test_get_timesheet_snapshots_audit_page(self):
        response = self.client.get(reverse("timesheet_snapshots_audit_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Auditoria de Snapshot Mensal")

    def test_get_timesheet_dashboard_page(self):
        response = self.client.get(reverse("timesheet_dashboard_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Painel de horas")

    def test_timesheet_dashboard_page_supports_month_range(self):
        sector = Sector.objects.create(nome="Engenharia")
        work_schedule = WorkSchedule.objects.create(
            nome="Escala ADM",
            horas_segunda="8.00",
            horas_terca="8.00",
            horas_quarta="8.00",
            horas_quinta="8.00",
            horas_sexta="8.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )
        employee = Employee.objects.create(
            matricula="RANGE-01",
            nome_completo="Funcionario Range",
            sector=sector,
            work_schedule=work_schedule,
            tipo=Employee.TYPE_DIRETO,
            regime_compensacao_jornada=Employee.REGIME_COMPENSACAO_PARTICIPANTE,
        )
        EmployeeTimeEntry.objects.create(
            employee=employee,
            competence_month="2026-04-01",
            regular_minutes=60,
            overtime_60_minutes=30,
            overtime_100_minutes=0,
            absence_unexcused_minutes=10,
            absence_excused_minutes=0,
            absence_bank_minutes=5,
        )
        EmployeeTimeEntry.objects.create(
            employee=employee,
            competence_month="2026-05-01",
            regular_minutes=120,
            overtime_60_minutes=0,
            overtime_100_minutes=0,
            absence_unexcused_minutes=0,
            absence_excused_minutes=15,
            absence_bank_minutes=0,
        )

        response = self.client.get(
            reverse("timesheet_dashboard_page"),
            data={"start_month": "2026-04", "end_month": "2026-05"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "04/2026 a 05/2026")
        self.assertContains(response, "01/04 - 31/05/2026")
        self.assertContains(response, "03:30")
        self.assertContains(response, "00:30")
        self.assertContains(response, "00:30")

    def test_timesheet_page_shows_dashboard_link_with_selected_month(self):
        response = self.client.get(f"{reverse('timesheet_page')}?competence_month=2026-04")
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f"{reverse('timesheet_dashboard_page')}?competence_month=2026-04",
        )

    def test_timesheet_snapshots_audit_page_shows_closed_month_snapshots(self):
        sector = Sector.objects.create(nome="Setor Auditoria")
        calendar = WorkCalendar.objects.create(nome="Calendario Auditoria")
        WorkCalendarPeriod.objects.create(
            calendar=calendar,
            period_type=WorkCalendarPeriod.TYPE_HOLIDAY,
            start_date=date(2026, 4, 21),
            end_date=date(2026, 4, 21),
            description="Feriado Auditoria",
        )
        work_schedule = WorkSchedule.objects.create(
            nome="Escala Auditoria",
            calendar=calendar,
            horas_segunda="8.00",
            horas_terca="8.00",
            horas_quarta="8.00",
            horas_quinta="8.00",
            horas_sexta="8.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )
        employee = Employee.objects.create(
            matricula="AUD-01",
            nome_completo="Funcionario Auditoria",
            sector=sector,
            work_schedule=work_schedule,
        )
        EmployeeEvent.objects.create(
            employee=employee,
            event_type=EmployeeEvent.EVENT_TYPE_VACATION,
            effective_date=date(2026, 4, 10),
            end_date=date(2026, 4, 14),
            notes="Ferias programadas",
        )

        self.client.post(
            reverse("timesheet_page"),
            data={"competence_month": "2026-04", "action": "close_month"},
            follow=True,
        )

        closure = TimesheetMonthClosure.objects.get(competence_month="2026-04-01")
        self.assertTrue(
            TimesheetMonthClosureEmployeeEventSnapshot.objects.filter(
                closure=closure,
                source_employee_id=employee.id,
                event_type=EmployeeEvent.EVENT_TYPE_VACATION,
            ).exists()
        )

        response = self.client.get(
            reverse("timesheet_snapshots_audit_page"),
            data={"competence_month": "2026-04"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escala Auditoria")
        self.assertContains(response, "Calendario Auditoria")
        self.assertContains(response, "Feriado Auditoria")
        self.assertContains(response, "Funcionario Auditoria")
        self.assertContains(response, "Ferias programadas")

    def test_timesheet_page_calculates_total_expected_minutes_from_work_schedules(self):
        sector = Sector.objects.create(nome="Engenharia")
        comercial = WorkSchedule.objects.create(
            nome="Comercial",
            horas_segunda="8.00",
            horas_terca="8.00",
            horas_quarta="8.00",
            horas_quinta="8.00",
            horas_sexta="8.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )
        diurno = WorkSchedule.objects.create(
            nome="Diurno",
            horas_segunda="12.00",
            horas_terca="0.00",
            horas_quarta="12.00",
            horas_quinta="0.00",
            horas_sexta="12.00",
            horas_sabado="0.00",
            horas_domingo="12.00",
        )
        comercial_employee = Employee.objects.create(
            matricula="3004F",
            nome_completo="Escala Comercial",
            sector=sector,
            work_schedule=comercial,
        )
        diurno_employee = Employee.objects.create(
            matricula="3004G",
            nome_completo="Escala Diurna",
            sector=sector,
            work_schedule=diurno,
        )
        sem_escala_employee = Employee.objects.create(
            matricula="3004H",
            nome_completo="Sem Escala",
            sector=sector,
        )

        response = self.client.get(f"{reverse('timesheet_page')}?competence_month=2026-04")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_expected_minutes"], 22800)
        self.assertContains(response, 'data-minutes="22800"')
        rows_by_employee = {
            row["employee"].id: row["expected_minutes"] for row in response.context["rows"]
        }
        self.assertEqual(rows_by_employee[comercial_employee.id], 10560)
        self.assertEqual(rows_by_employee[diurno_employee.id], 12240)
        self.assertEqual(rows_by_employee[sem_escala_employee.id], 0)
        self.assertContains(response, 'data-minutes="10560"')
        self.assertContains(response, 'data-minutes="12240"')

    def test_timesheet_expected_minutes_subtracts_calendar_exceptions_by_weekday_hours(self):
        sector = Sector.objects.create(nome="Engenharia")
        calendar = WorkCalendar.objects.create(nome="Calendario Operacional")
        schedule = WorkSchedule.objects.create(
            nome="Escala Operacional",
            calendar=calendar,
            horas_segunda="8.00",
            horas_terca="0.00",
            horas_quarta="0.00",
            horas_quinta="0.00",
            horas_sexta="0.00",
            horas_sabado="4.00",
            horas_domingo="0.00",
        )
        employee = Employee.objects.create(
            matricula="3004I",
            nome_completo="Calendario com Excecao",
            sector=sector,
            work_schedule=schedule,
        )

        baseline_response = self.client.get(
            f"{reverse('timesheet_page')}?competence_month=2026-04"
        )
        baseline_rows = {
            row["employee"].id: row["expected_minutes"]
            for row in baseline_response.context["rows"]
        }
        baseline_minutes = baseline_rows[employee.id]

        WorkCalendarPeriod.objects.create(
            calendar=calendar,
            period_type=WorkCalendarPeriod.TYPE_HOLIDAY,
            start_date=date(2026, 4, 6),
            end_date=date(2026, 4, 6),
            description="Feriado segunda",
        )
        WorkCalendarPeriod.objects.create(
            calendar=calendar,
            period_type=WorkCalendarPeriod.TYPE_BRIDGE,
            start_date=date(2026, 4, 11),
            end_date=date(2026, 4, 11),
            description="Ponte sabado",
        )

        response = self.client.get(f"{reverse('timesheet_page')}?competence_month=2026-04")
        self.assertEqual(response.status_code, 200)
        rows_by_employee = {
            row["employee"].id: row["expected_minutes"] for row in response.context["rows"]
        }
        self.assertEqual(rows_by_employee[employee.id], baseline_minutes - 720)

    def test_timesheet_expected_minutes_uses_union_of_calendar_and_employee_exceptions(self):
        sector = Sector.objects.create(nome="Engenharia")
        calendar = WorkCalendar.objects.create(nome="Calendario Integrado")
        schedule = WorkSchedule.objects.create(
            nome="Escala Integrada",
            calendar=calendar,
            horas_segunda="8.00",
            horas_terca="7.00",
            horas_quarta="0.00",
            horas_quinta="0.00",
            horas_sexta="0.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )
        employee = Employee.objects.create(
            matricula="3004J",
            nome_completo="Excecao Individual",
            sector=sector,
            work_schedule=schedule,
        )

        baseline_response = self.client.get(
            f"{reverse('timesheet_page')}?competence_month=2026-04"
        )
        baseline_rows = {
            row["employee"].id: row["expected_minutes"]
            for row in baseline_response.context["rows"]
        }
        baseline_minutes = baseline_rows[employee.id]

        WorkCalendarPeriod.objects.create(
            calendar=calendar,
            period_type=WorkCalendarPeriod.TYPE_HOLIDAY,
            start_date=date(2026, 4, 6),
            end_date=date(2026, 4, 6),
            description="Feriado",
        )
        EmployeeEvent.objects.create(
            employee=employee,
            event_type=EmployeeEvent.EVENT_TYPE_VACATION,
            effective_date=date(2026, 4, 6),
            end_date=date(2026, 4, 7),
            notes="Ferias com sobreposicao",
        )

        response = self.client.get(f"{reverse('timesheet_page')}?competence_month=2026-04")
        self.assertEqual(response.status_code, 200)
        rows_by_employee = {
            row["employee"].id: row["expected_minutes"] for row in response.context["rows"]
        }
        self.assertEqual(rows_by_employee[employee.id], baseline_minutes - 900)

    def test_legacy_point_url_redirects_to_timesheet(self):
        response = self.client.get("/ponto/?competence_month=2026-04")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response["Location"],
            f"{reverse('timesheet_page')}?competence_month=2026-04",
        )

    def test_save_monthly_timesheet_compiled_table(self):
        sector = Sector.objects.create(nome="RH")
        employee = Employee.objects.create(
            matricula="3004C",
            nome_completo="Ponto Manual",
            regime_compensacao_jornada=Employee.REGIME_COMPENSACAO_PARTICIPANTE,
            sector=sector,
        )
        response = self.client.post(
            reverse("timesheet_page"),
            data={
                "competence_month": "2026-04",
                f"regular_minutes_{employee.id}": "9600",
                f"overtime_60_minutes_{employee.id}": "720",
                f"overtime_100_minutes_{employee.id}": "240",
                f"absence_unexcused_minutes_{employee.id}": "480",
                f"absence_excused_minutes_{employee.id}": "120",
                f"absence_bank_minutes_{employee.id}": "0",
                f"notes_{employee.id}": "Fechamento mensal",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmployeeTimeEntry.objects.count(), 1)
        entry = EmployeeTimeEntry.objects.first()
        self.assertEqual(entry.employee, employee)
        self.assertEqual(str(entry.competence_month), "2026-04-01")
        self.assertEqual(entry.regular_minutes, 9600)
        self.assertEqual(entry.overtime_60_minutes, 720)
        self.assertEqual(entry.overtime_100_minutes, 240)
        self.assertEqual(entry.absence_unexcused_minutes, 480)
        self.assertEqual(entry.absence_excused_minutes, 120)
        self.assertEqual(entry.absence_bank_minutes, 0)
        self.assertEqual(entry.notes, "Fechamento mensal")
        self.assertContains(response, "Timesheet mensal salvo para 1 empregado(s).")
        self.assertEqual(response.context["total_worked_minutes"], 10560)
        self.assertEqual(response.context["total_overtime_minutes"], 960)
        self.assertEqual(response.context["total_overtime_60_minutes"], 720)
        self.assertEqual(response.context["total_overtime_100_minutes"], 240)
        self.assertEqual(response.context["total_absence_unexcused_minutes"], 480)
        self.assertEqual(response.context["total_absence_excused_minutes"], 120)
        self.assertEqual(response.context["total_absence_bank_minutes"], 0)
        self.assertContains(response, "Horas totais")
        self.assertContains(response, "Horas extras")
        self.assertContains(response, 'data-minutes="10560"')
        self.assertContains(response, 'data-minutes="960"')

    def test_save_monthly_timesheet_accepts_hhmm_above_24_hours(self):
        sector = Sector.objects.create(nome="Financeiro")
        employee = Employee.objects.create(
            matricula="3004HHMM",
            nome_completo="Ponto HHMM",
            regime_compensacao_jornada=Employee.REGIME_COMPENSACAO_PARTICIPANTE,
            sector=sector,
        )

        response = self.client.post(
            reverse("timesheet_page"),
            data={
                "competence_month": "2026-04",
                f"regular_minutes_{employee.id}": "26:30",
                f"overtime_60_minutes_{employee.id}": "01:15",
                f"overtime_100_minutes_{employee.id}": "0",
                f"absence_unexcused_minutes_{employee.id}": "0:45",
                f"absence_excused_minutes_{employee.id}": "0",
                f"absence_bank_minutes_{employee.id}": "0",
                f"notes_{employee.id}": "Entrada em HH:MM",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        entry = EmployeeTimeEntry.objects.get(employee=employee, competence_month="2026-04-01")
        self.assertEqual(entry.regular_minutes, 1590)
        self.assertEqual(entry.overtime_60_minutes, 75)
        self.assertEqual(entry.overtime_100_minutes, 0)
        self.assertEqual(entry.absence_unexcused_minutes, 45)
        self.assertEqual(entry.absence_excused_minutes, 0)
        self.assertEqual(entry.absence_bank_minutes, 0)

    def test_close_month_action_creates_month_closure(self):
        response = self.client.post(
            reverse("timesheet_page"),
            data={
                "competence_month": "2026-04",
                "action": "close_month",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            TimesheetMonthClosure.objects.filter(competence_month="2026-04-01").exists()
        )
        self.assertContains(response, "Timesheet de 04/2026 encerrado")

    def test_close_month_action_creates_schedule_snapshot(self):
        sector = Sector.objects.create(nome="Engenharia")
        calendar = WorkCalendar.objects.create(nome="Calendario Snapshot")
        WorkCalendarPeriod.objects.create(
            calendar=calendar,
            period_type=WorkCalendarPeriod.TYPE_HOLIDAY,
            start_date=date(2026, 4, 21),
            end_date=date(2026, 4, 21),
            description="Tiradentes",
        )
        work_schedule = WorkSchedule.objects.create(
            nome="Escala Snapshot",
            calendar=calendar,
            horas_segunda="8.00",
            horas_terca="8.00",
            horas_quarta="8.00",
            horas_quinta="8.00",
            horas_sexta="8.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )
        Employee.objects.create(
            matricula="TS-SNAP-01",
            nome_completo="Funcionario Snapshot",
            sector=sector,
            work_schedule=work_schedule,
        )

        response = self.client.post(
            reverse("timesheet_page"),
            data={
                "competence_month": "2026-04",
                "action": "close_month",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        closure = TimesheetMonthClosure.objects.get(competence_month="2026-04-01")
        self.assertTrue(
            TimesheetMonthClosureWorkScheduleSnapshot.objects.filter(
                closure=closure,
                source_work_schedule_id=work_schedule.id,
            ).exists()
        )
        self.assertTrue(
            TimesheetMonthClosureCalendarPeriodSnapshot.objects.filter(
                closure=closure,
                source_calendar_id=calendar.id,
                start_date="2026-04-21",
            ).exists()
        )

    def test_save_monthly_timesheet_is_blocked_when_month_is_closed(self):
        sector = Sector.objects.create(nome="Qualidade")
        employee = Employee.objects.create(
            matricula="3004LOCK",
            nome_completo="Mes Encerrado",
            regime_compensacao_jornada=Employee.REGIME_COMPENSACAO_PARTICIPANTE,
            sector=sector,
        )
        TimesheetMonthClosure.objects.create(competence_month="2026-04-01")

        response = self.client.post(
            reverse("timesheet_page"),
            data={
                "competence_month": "2026-04",
                f"regular_minutes_{employee.id}": "9600",
                f"overtime_60_minutes_{employee.id}": "0",
                f"overtime_100_minutes_{employee.id}": "0",
                f"absence_unexcused_minutes_{employee.id}": "0",
                f"absence_excused_minutes_{employee.id}": "0",
                f"absence_bank_minutes_{employee.id}": "0",
                f"notes_{employee.id}": "Tentativa bloqueada",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmployeeTimeEntry.objects.count(), 0)
        self.assertContains(response, "esta encerrado")

    def test_reopen_month_action_removes_month_closure(self):
        TimesheetMonthClosure.objects.create(competence_month="2026-04-01")

        response = self.client.post(
            reverse("timesheet_page"),
            data={
                "competence_month": "2026-04",
                "action": "reopen_month",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            TimesheetMonthClosure.objects.filter(competence_month="2026-04-01").exists()
        )
        self.assertContains(response, "Timesheet de 04/2026 reaberto")
    def test_save_timesheet_for_non_participant_forces_bank_minutes_zero(self):
        sector = Sector.objects.create(nome="Logistica")
        employee = Employee.objects.create(
            matricula="3004NP",
            nome_completo="Nao Participante",
            regime_compensacao_jornada=Employee.REGIME_COMPENSACAO_NAO_PARTICIPANTE,
            sector=sector,
        )

        response = self.client.post(
            reverse("timesheet_page"),
            data={
                "competence_month": "2026-04",
                f"regular_minutes_{employee.id}": "9600",
                f"overtime_60_minutes_{employee.id}": "0",
                f"overtime_100_minutes_{employee.id}": "0",
                f"absence_unexcused_minutes_{employee.id}": "0",
                f"absence_excused_minutes_{employee.id}": "0",
                f"absence_bank_minutes_{employee.id}": "180",
                f"notes_{employee.id}": "Tentativa de banco",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmployeeTimeEntry.objects.count(), 1)
        entry = EmployeeTimeEntry.objects.first()
        self.assertEqual(entry.employee, employee)
        self.assertEqual(entry.absence_bank_minutes, 0)

    def test_save_monthly_timesheet_removes_row_without_values(self):
        sector = Sector.objects.create(nome="Operacoes")
        employee = Employee.objects.create(
            matricula="3004D",
            nome_completo="Ponto Atualizado",
            sector=sector,
        )
        EmployeeTimeEntry.objects.create(
            employee=employee,
            competence_month="2026-04-01",
            regular_minutes=9600,
            overtime_60_minutes=600,
            overtime_100_minutes=180,
            absence_unexcused_minutes=0,
            absence_excused_minutes=0,
            absence_bank_minutes=0,
            notes="Registro inicial",
        )

        response = self.client.post(
            reverse("timesheet_page"),
            data={
                "competence_month": "2026-04",
                f"regular_minutes_{employee.id}": "",
                f"overtime_60_minutes_{employee.id}": "",
                f"overtime_100_minutes_{employee.id}": "",
                f"absence_unexcused_minutes_{employee.id}": "",
                f"absence_excused_minutes_{employee.id}": "",
                f"absence_bank_minutes_{employee.id}": "",
                f"notes_{employee.id}": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmployeeTimeEntry.objects.count(), 0)
        self.assertNotContains(response, "0 empregado(s) sem valores foram removidos do mes.")
        self.assertContains(response, "1 empregado(s) sem valores foram removidos do mes.")

    def test_timesheet_page_filters_by_competence_month(self):
        sector = Sector.objects.create(nome="Manutencao")
        employee = Employee.objects.create(
            matricula="3004E",
            nome_completo="Filtro Mensal",
            sector=sector,
        )
        EmployeeTimeEntry.objects.create(
            employee=employee,
            competence_month="2026-04-01",
            regular_minutes=9600,
            overtime_60_minutes=0,
            overtime_100_minutes=0,
            absence_unexcused_minutes=0,
            absence_excused_minutes=0,
            absence_bank_minutes=0,
            notes="Competencia Abril",
        )
        EmployeeTimeEntry.objects.create(
            employee=employee,
            competence_month="2026-05-01",
            regular_minutes=10080,
            overtime_60_minutes=240,
            overtime_100_minutes=0,
            absence_unexcused_minutes=0,
            absence_excused_minutes=0,
            absence_bank_minutes=0,
            notes="Competencia Maio",
        )

        response = self.client.get(f"{reverse('timesheet_page')}?competence_month=2026-04")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Competencia Abril")
        self.assertNotContains(response, "Competencia Maio")

    def test_events_page_lists_allocation_change_event(self):
        sector_old = Sector.objects.create(nome="RH")
        sector_new = Sector.objects.create(nome="Operacoes")
        work_schedule_old = WorkSchedule.objects.create(
            nome="Escala Antiga",
            horas_segunda="8.00",
            horas_terca="8.00",
            horas_quarta="8.00",
            horas_quinta="8.00",
            horas_sexta="8.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )
        work_schedule_new = WorkSchedule.objects.create(
            nome="Escala Nova",
            horas_segunda="12.00",
            horas_terca="0.00",
            horas_quarta="12.00",
            horas_quinta="0.00",
            horas_sexta="12.00",
            horas_sabado="0.00",
            horas_domingo="12.00",
        )
        employee = Employee.objects.create(
            matricula="3004A",
            nome_completo="Evento Alteracao",
            sector=sector_new,
            work_schedule=work_schedule_new,
        )
        EmployeeEvent.objects.create(
            employee=employee,
            event_type=EmployeeEvent.EVENT_TYPE_ALLOCATION_CHANGE,
            effective_date="2026-04-24",
            previous_sector=sector_old,
            new_sector=sector_new,
            previous_work_schedule=work_schedule_old,
            new_work_schedule=work_schedule_new,
        )

        response = self.client.get(reverse("events_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "24/04/2026")
        self.assertContains(response, employee.nome_completo)
        self.assertContains(response, "RH")
        self.assertContains(response, "Operacoes")
        self.assertContains(response, "Escala Antiga")
        self.assertContains(response, "Escala Nova")

    def test_get_sectors_page(self):
        response = self.client.get(reverse("sectors_page"))
        self.assertEqual(response.status_code, 200)

    def test_create_sector_via_page(self):
        response = self.client.post(
            reverse("sectors_page"),
            data={"nome": "Financeiro"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Sector.objects.count(), 1)

    def test_duplicate_sector_via_page(self):
        Sector.objects.create(nome="RH")
        response = self.client.post(
            reverse("sectors_page"),
            data={"nome": "rh"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Sector.objects.count(), 1)
        self.assertContains(response, "Ja existe um setor com esse nome.")

    def test_edit_sector_via_page(self):
        sector = Sector.objects.create(nome="Financeiro")
        response = self.client.post(
            reverse("sector_edit_page", kwargs={"sector_id": sector.id}),
            data={"nome": "Controladoria"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        sector.refresh_from_db()
        self.assertEqual(sector.nome, "Controladoria")

    def test_deactivate_sector_via_page(self):
        sector = Sector.objects.create(nome="Comercial")
        response = self.client.post(
            reverse("sector_deactivate", kwargs={"sector_id": sector.id}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        sector.refresh_from_db()
        self.assertIsNotNone(sector.deactivated_at)
        self.assertContains(response, "Comercial")
        self.assertContains(response, "Desativado")
        self.assertContains(response, "Ativar")
        self.assertNotContains(response, "Desativar")

    def test_activate_sector_via_page(self):
        sector = Sector.objects.create(nome="TI", deactivated_at=timezone.now())
        response = self.client.post(
            reverse("sector_activate", kwargs={"sector_id": sector.id}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        sector.refresh_from_db()
        self.assertIsNone(sector.deactivated_at)
        self.assertContains(response, "Ativado")

    def test_create_sector_after_soft_delete_same_name(self):
        sector = Sector.objects.create(nome="Juridico")
        self.client.post(
            reverse("sector_deactivate", kwargs={"sector_id": sector.id}),
            follow=True,
        )
        response = self.client.post(
            reverse("sectors_page"),
            data={"nome": "Juridico"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Sector.objects.filter(nome="Juridico").count(), 2)

    def test_get_work_schedules_page(self):
        response = self.client.get(reverse("work_schedules_page"))
        self.assertEqual(response.status_code, 200)

    def test_create_calendar_via_work_schedules_page(self):
        response = self.client.post(
            reverse("work_schedules_page"),
            data={"form_type": "calendar", "calendar_name": "Calendario ADM"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkCalendar.objects.count(), 1)
        self.assertContains(response, "Calendario cadastrado com sucesso.")

    def test_create_work_schedule_via_page(self):
        calendar = WorkCalendar.objects.create(nome="Calendario ADM")
        response = self.client.post(
            reverse("work_schedules_page"),
            data={
                "form_type": "work_schedule",
                "nome": "Escala Comercial",
                "calendar_id": str(calendar.id),
                "horas_segunda": "8",
                "horas_terca": "8",
                "horas_quarta": "8",
                "horas_quinta": "8",
                "horas_sexta": "8",
                "horas_sabado": "4",
                "horas_domingo": "0",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkSchedule.objects.count(), 1)
        self.assertEqual(WorkSchedule.objects.first().calendar, calendar)
        self.assertContains(response, "Escala cadastrada com sucesso.")

    def test_edit_work_schedule_via_page(self):
        calendar_a = WorkCalendar.objects.create(nome="Calendario A")
        calendar_b = WorkCalendar.objects.create(nome="Calendario B")
        work_schedule = WorkSchedule.objects.create(
            nome="Escala Original",
            calendar=calendar_a,
            horas_segunda="8.00",
            horas_terca="8.00",
            horas_quarta="8.00",
            horas_quinta="8.00",
            horas_sexta="8.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )

        response = self.client.post(
            reverse("work_schedules_page"),
            data={
                "form_type": "work_schedule_edit",
                "work_schedule_id": str(work_schedule.id),
                "nome": "Escala Atualizada",
                "calendar_id": str(calendar_b.id),
                "horas_segunda": "7.5",
                "horas_terca": "7.5",
                "horas_quarta": "7.5",
                "horas_quinta": "7.5",
                "horas_sexta": "7.5",
                "horas_sabado": "0",
                "horas_domingo": "0",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        work_schedule.refresh_from_db()
        self.assertEqual(work_schedule.nome, "Escala Atualizada")
        self.assertEqual(work_schedule.calendar, calendar_b)
        self.assertContains(response, "Escala atualizada com sucesso.")

    def test_edit_work_schedule_is_blocked_when_month_closed_snapshot_exists(self):
        sector = Sector.objects.create(nome="Bloqueio Setor")
        calendar = WorkCalendar.objects.create(nome="Calendario Bloqueio")
        work_schedule = WorkSchedule.objects.create(
            nome="Escala Bloqueada",
            calendar=calendar,
            horas_segunda="8.00",
            horas_terca="8.00",
            horas_quarta="8.00",
            horas_quinta="8.00",
            horas_sexta="8.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )
        Employee.objects.create(
            matricula="BLK-ESC-01",
            nome_completo="Funcionario Bloqueio Escala",
            sector=sector,
            work_schedule=work_schedule,
        )
        self.client.post(
            reverse("timesheet_page"),
            data={"competence_month": "2026-04", "action": "close_month"},
            follow=True,
        )

        response = self.client.post(
            reverse("work_schedules_page"),
            data={
                "form_type": "work_schedule_edit",
                "work_schedule_id": str(work_schedule.id),
                "nome": "Escala Tentativa",
                "calendar_id": str(calendar.id),
                "horas_segunda": "7.5",
                "horas_terca": "7.5",
                "horas_quarta": "7.5",
                "horas_quinta": "7.5",
                "horas_sexta": "7.5",
                "horas_sabado": "0",
                "horas_domingo": "0",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        work_schedule.refresh_from_db()
        self.assertEqual(work_schedule.nome, "Escala Bloqueada")
        self.assertContains(
            response,
            "Nao e permitido alterar esta escala, pois ela ja foi usada em mes fechado",
        )

    def test_duplicate_work_schedule_via_page(self):
        calendar = WorkCalendar.objects.create(nome="Calendario ADM")
        WorkSchedule.objects.create(
            nome="Escala Comercial",
            calendar=calendar,
            horas_segunda="8.00",
            horas_terca="8.00",
            horas_quarta="8.00",
            horas_quinta="8.00",
            horas_sexta="8.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )
        response = self.client.post(
            reverse("work_schedules_page"),
            data={
                "form_type": "work_schedule",
                "nome": "escala comercial",
                "calendar_id": str(calendar.id),
                "horas_segunda": "8",
                "horas_terca": "8",
                "horas_quarta": "8",
                "horas_quinta": "8",
                "horas_sexta": "8",
                "horas_sabado": "0",
                "horas_domingo": "0",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkSchedule.objects.count(), 1)
        self.assertContains(response, "Ja existe uma escala com esse nome.")

    def test_create_work_schedule_requires_calendar(self):
        response = self.client.post(
            reverse("work_schedules_page"),
            data={
                "form_type": "work_schedule",
                "nome": "Escala sem calendario",
                "horas_segunda": "8",
                "horas_terca": "8",
                "horas_quarta": "8",
                "horas_quinta": "8",
                "horas_sexta": "8",
                "horas_sabado": "0",
                "horas_domingo": "0",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkSchedule.objects.count(), 0)
        self.assertContains(response, "Selecione um calendario valido.")

    def test_create_special_period_via_work_schedules_page(self):
        calendar = WorkCalendar.objects.create(nome="Calendario Operacao")
        start_date = timezone.localdate() + timedelta(days=2)
        end_date = start_date + timedelta(days=2)
        response = self.client.post(
            reverse("work_schedules_page"),
            data={
                "form_type": "special_period",
                "calendar_id": str(calendar.id),
                "period_type": WorkCalendarPeriod.TYPE_HOLIDAY,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "description": "Natal",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkCalendarPeriod.objects.count(), 1)
        period = WorkCalendarPeriod.objects.first()
        self.assertEqual(period.calendar, calendar)
        self.assertEqual(period.start_date, start_date)
        self.assertEqual(period.end_date, end_date)
        self.assertContains(response, "Periodo especial cadastrado com sucesso.")

    def test_create_special_period_is_blocked_when_calendar_has_closed_snapshot(self):
        sector = Sector.objects.create(nome="Setor Calendario Bloq")
        calendar = WorkCalendar.objects.create(nome="Calendario Fechado")
        work_schedule = WorkSchedule.objects.create(
            nome="Escala Calendario Fechado",
            calendar=calendar,
            horas_segunda="8.00",
            horas_terca="8.00",
            horas_quarta="8.00",
            horas_quinta="8.00",
            horas_sexta="8.00",
            horas_sabado="0.00",
            horas_domingo="0.00",
        )
        Employee.objects.create(
            matricula="BLK-CAL-01",
            nome_completo="Funcionario Bloqueio Calendario",
            sector=sector,
            work_schedule=work_schedule,
        )
        self.client.post(
            reverse("timesheet_page"),
            data={"competence_month": "2026-04", "action": "close_month"},
            follow=True,
        )

        start_date = timezone.localdate() + timedelta(days=2)
        end_date = start_date + timedelta(days=2)
        response = self.client.post(
            reverse("work_schedules_page"),
            data={
                "form_type": "special_period",
                "calendar_id": str(calendar.id),
                "period_type": WorkCalendarPeriod.TYPE_HOLIDAY,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "description": "Tentativa Bloqueada",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkCalendarPeriod.objects.filter(description="Tentativa Bloqueada").count(), 0)
        self.assertContains(
            response,
            "Nao e permitido alterar este calendario, pois ele ja foi usado em mes fechado",
        )

    def test_create_special_period_rejects_end_date_before_start_date(self):
        calendar = WorkCalendar.objects.create(nome="Calendario Ponte")
        start_date = timezone.localdate() + timedelta(days=10)
        response = self.client.post(
            reverse("work_schedules_page"),
            data={
                "form_type": "special_period",
                "calendar_id": str(calendar.id),
                "period_type": WorkCalendarPeriod.TYPE_BRIDGE,
                "start_date": start_date.isoformat(),
                "end_date": (start_date - timedelta(days=1)).isoformat(),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkCalendarPeriod.objects.count(), 0)
        self.assertContains(response, "A data de fim deve ser maior ou igual a data de inicio.")

    def test_create_special_period_rejects_past_dates(self):
        calendar = WorkCalendar.objects.create(nome="Calendario Expirado")
        start_date = timezone.localdate() - timedelta(days=5)
        end_date = timezone.localdate() - timedelta(days=1)
        response = self.client.post(
            reverse("work_schedules_page"),
            data={
                "form_type": "special_period",
                "calendar_id": str(calendar.id),
                "period_type": WorkCalendarPeriod.TYPE_HOLIDAY,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkCalendarPeriod.objects.count(), 0)
        self.assertContains(response, "Nao e permitido incluir excecoes com datas que ja passaram.")

    def test_work_schedules_page_filters_periods_by_selected_calendar(self):
        calendar_a = WorkCalendar.objects.create(nome="Calendario A")
        calendar_b = WorkCalendar.objects.create(nome="Calendario B")
        today = timezone.localdate()
        WorkCalendarPeriod.objects.create(
            calendar=calendar_a,
            period_type=WorkCalendarPeriod.TYPE_HOLIDAY,
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=1),
            description="Periodo A",
        )
        WorkCalendarPeriod.objects.create(
            calendar=calendar_b,
            period_type=WorkCalendarPeriod.TYPE_HOLIDAY,
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=2),
            description="Periodo B",
        )

        response_without_filter = self.client.get(reverse("work_schedules_page"))
        self.assertEqual(response_without_filter.status_code, 200)
        self.assertContains(
            response_without_filter,
            "Selecione um calendario para visualizar as excecoes.",
        )
        self.assertNotContains(response_without_filter, "Periodo A")
        self.assertNotContains(response_without_filter, "Periodo B")

        response_with_filter = self.client.get(
            reverse("work_schedules_page"),
            data={"calendar_id": str(calendar_a.id)},
        )
        self.assertEqual(response_with_filter.status_code, 200)
        self.assertContains(response_with_filter, "Periodo A")
        self.assertNotContains(response_with_filter, "Periodo B")


class SectorModelTests(TestCase):
    def test_create_sector(self):
        Sector.objects.create(nome="Financeiro")
        self.assertEqual(Sector.objects.count(), 1)




