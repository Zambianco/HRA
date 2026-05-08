from django.db import models


class Employee(models.Model):
    TYPE_DIRETO = "direto"
    TYPE_INDIRETO = "indireto"
    TYPE_CHOICES = (
        (TYPE_DIRETO, "Direto"),
        (TYPE_INDIRETO, "Indireto"),
    )

    REGIME_COMPENSACAO_NAO_PARTICIPANTE = "nao_participante"
    REGIME_COMPENSACAO_PARTICIPANTE = "participante"
    REGIME_COMPENSACAO_JORNADA_CHOICES = (
        (REGIME_COMPENSACAO_NAO_PARTICIPANTE, "Nao participante"),
        (REGIME_COMPENSACAO_PARTICIPANTE, "Participante"),
    )

    matricula = models.CharField(max_length=50, null=True, blank=True)
    nome_completo = models.CharField(max_length=150)
    tipo = models.CharField(
        max_length=9,
        choices=TYPE_CHOICES,
        default=TYPE_DIRETO,
    )
    regime_compensacao_jornada = models.CharField(
        max_length=20,
        choices=REGIME_COMPENSACAO_JORNADA_CHOICES,
        default=REGIME_COMPENSACAO_NAO_PARTICIPANTE,
    )
    cargo = models.ForeignKey(
        "Cargo",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )
    sector = models.ForeignKey(
        "Sector",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )
    work_schedule = models.ForeignKey(
        "WorkSchedule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )
    deactivated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("nome_completo",)
        constraints = [
            models.UniqueConstraint(
                fields=("matricula",),
                condition=models.Q(matricula__isnull=False),
                name="uniq_employee_matricula_not_null",
            )
        ]

    def __str__(self) -> str:
        return f"{self.matricula or '-'} - {self.nome_completo}"


class EmployeeEvent(models.Model):
    EVENT_TYPE_HIRING = "hiring"
    EVENT_TYPE_ALLOCATION_CHANGE = "allocation_change"
    EVENT_TYPE_ABSENCE = "absence"
    EVENT_TYPE_MEDICAL_CERTIFICATE = "medical_certificate"
    EVENT_TYPE_BANK_HOURS_ADOPTION = "bank_hours_adoption"
    EVENT_TYPE_BANK_HOURS_WITHDRAWAL = "bank_hours_withdrawal"
    EVENT_TYPE_BANK_HOURS_MOVEMENT = "bank_hours_movement"
    EVENT_TYPE_DAY_OFF = "day_off"
    EVENT_TYPE_VACATION = "vacation"
    EVENT_TYPE_TERMINATION = "termination"

    EVENT_TYPE_CHOICES = (
        (EVENT_TYPE_HIRING, "Admissao"),
        (EVENT_TYPE_ALLOCATION_CHANGE, "Alteracao de setor/escala"),
        (EVENT_TYPE_ABSENCE, "Afastamento"),
        (EVENT_TYPE_MEDICAL_CERTIFICATE, "Atestado"),
        (EVENT_TYPE_BANK_HOURS_ADOPTION, "Adesao ao banco de horas"),
        (EVENT_TYPE_BANK_HOURS_WITHDRAWAL, "Saida do banco de horas"),
        (EVENT_TYPE_BANK_HOURS_MOVEMENT, "Movimento de banco de horas"),
        (EVENT_TYPE_DAY_OFF, "Folga"),
        (EVENT_TYPE_VACATION, "Ferias"),
        (EVENT_TYPE_TERMINATION, "Demissao"),
    )

    employee = models.ForeignKey(
        "Employee",
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(
        max_length=40,
        choices=EVENT_TYPE_CHOICES,
        default=EVENT_TYPE_ALLOCATION_CHANGE,
    )
    effective_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    bank_hours_amount = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)
    previous_sector = models.ForeignKey(
        "Sector",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events_as_previous_sector",
    )
    new_sector = models.ForeignKey(
        "Sector",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events_as_new_sector",
    )
    previous_work_schedule = models.ForeignKey(
        "WorkSchedule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events_as_previous_work_schedule",
    )
    new_work_schedule = models.ForeignKey(
        "WorkSchedule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events_as_new_work_schedule",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-effective_date", "-created_at", "-id")

    def __str__(self) -> str:
        return f"{self.employee_id} - {self.event_type} - {self.effective_date}"


class EmployeeTimeEntry(models.Model):
    employee = models.ForeignKey(
        "Employee",
        on_delete=models.CASCADE,
        related_name="time_entries",
    )
    competence_month = models.DateField(db_index=True)
    regular_minutes = models.IntegerField(default=0)
    overtime_60_minutes = models.IntegerField(default=0)
    overtime_100_minutes = models.IntegerField(default=0)
    absence_unexcused_minutes = models.IntegerField(default=0)
    absence_excused_minutes = models.IntegerField(default=0)
    absence_bank_minutes = models.IntegerField(default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-competence_month", "employee__nome_completo", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("employee", "competence_month"),
                name="uniq_time_entry_employee_competence_month",
            )
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} - {self.competence_month}"


class BankHoursRule(models.Model):
    COLUMN_B = "B"
    COLUMN_C = "C"
    COLUMN_F = "F"
    TARGET_COLUMN_CHOICES = (
        (COLUMN_B, "B - Hora banco"),
        (COLUMN_C, "C - Horas com acrescimo"),
        (COLUMN_F, "F - Saldo do mes"),
    )

    start_month = models.DateField(db_index=True)
    end_month = models.DateField(db_index=True)
    target_column = models.CharField(max_length=1, choices=TARGET_COLUMN_CHOICES)
    formula = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-start_month", "target_column", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_month__gte=models.F("start_month")),
                name="bank_hours_rule_end_month_gte_start_month",
            )
        ]

    def __str__(self) -> str:
        return (
            f"{self.target_column}: {self.formula} "
            f"({self.start_month} a {self.end_month})"
        )


class TimesheetMonthClosure(models.Model):
    competence_month = models.DateField(unique=True, db_index=True)
    closed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-competence_month", "-closed_at", "-id")

    def __str__(self) -> str:
        return f"{self.competence_month} - encerrado"


class BankHoursSemesterClosure(models.Model):
    SEMESTER_1 = 1
    SEMESTER_2 = 2
    SEMESTER_CHOICES = (
        (SEMESTER_1, "1o semestre"),
        (SEMESTER_2, "2o semestre"),
    )

    year = models.IntegerField(db_index=True)
    semester = models.IntegerField(choices=SEMESTER_CHOICES, db_index=True)
    adjustment_month = models.DateField(db_index=True)
    closed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reversed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ("-closed_at", "-id")

    def __str__(self) -> str:
        return f"{self.year}/S{self.semester} - fechado"


class BankHoursSemesterClosureAdjustment(models.Model):
    closure = models.ForeignKey(
        "BankHoursSemesterClosure",
        on_delete=models.CASCADE,
        related_name="adjustments",
    )
    employee = models.ForeignKey(
        "Employee",
        on_delete=models.CASCADE,
        related_name="bank_hours_semester_adjustments",
    )
    balance_minutes = models.IntegerField()
    closing_event = models.ForeignKey(
        "EmployeeEvent",
        on_delete=models.PROTECT,
        related_name="bank_hours_closing_adjustments",
    )
    reversal_event = models.ForeignKey(
        "EmployeeEvent",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bank_hours_reversal_adjustments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("closure_id", "employee__nome_completo", "id")


class TimesheetMonthClosureWorkScheduleSnapshot(models.Model):
    closure = models.ForeignKey(
        "TimesheetMonthClosure",
        on_delete=models.CASCADE,
        related_name="work_schedule_snapshots",
    )
    source_work_schedule_id = models.IntegerField(db_index=True)
    work_schedule_name = models.CharField(max_length=120)
    source_calendar_id = models.IntegerField(null=True, blank=True, db_index=True)
    calendar_name = models.CharField(max_length=120, blank=True)
    horas_segunda = models.DecimalField(max_digits=4, decimal_places=2)
    horas_terca = models.DecimalField(max_digits=4, decimal_places=2)
    horas_quarta = models.DecimalField(max_digits=4, decimal_places=2)
    horas_quinta = models.DecimalField(max_digits=4, decimal_places=2)
    horas_sexta = models.DecimalField(max_digits=4, decimal_places=2)
    horas_sabado = models.DecimalField(max_digits=4, decimal_places=2)
    horas_domingo = models.DecimalField(max_digits=4, decimal_places=2)

    class Meta:
        ordering = ("closure__competence_month", "work_schedule_name", "id")


class TimesheetMonthClosureCalendarPeriodSnapshot(models.Model):
    closure = models.ForeignKey(
        "TimesheetMonthClosure",
        on_delete=models.CASCADE,
        related_name="calendar_period_snapshots",
    )
    source_calendar_id = models.IntegerField(db_index=True)
    calendar_name = models.CharField(max_length=120)
    period_type = models.CharField(max_length=20)
    start_date = models.DateField()
    end_date = models.DateField()
    description = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ("closure__competence_month", "start_date", "id")


class TimesheetMonthClosureEmployeeEventSnapshot(models.Model):
    closure = models.ForeignKey(
        "TimesheetMonthClosure",
        on_delete=models.CASCADE,
        related_name="employee_event_snapshots",
    )
    source_employee_event_id = models.IntegerField(db_index=True)
    source_employee_id = models.IntegerField(db_index=True)
    employee_registration = models.CharField(max_length=50)
    employee_name = models.CharField(max_length=150)
    event_type = models.CharField(max_length=40)
    effective_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = (
            "closure__competence_month",
            "employee_name",
            "effective_date",
            "source_employee_event_id",
        )



class WorkCalendar(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("nome",)

    def __str__(self) -> str:
        return self.nome


class WorkSchedule(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    calendar = models.ForeignKey(
        "WorkCalendar",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_schedules",
    )
    horas_segunda = models.DecimalField(max_digits=4, decimal_places=2)
    horas_terca = models.DecimalField(max_digits=4, decimal_places=2)
    horas_quarta = models.DecimalField(max_digits=4, decimal_places=2)
    horas_quinta = models.DecimalField(max_digits=4, decimal_places=2)
    horas_sexta = models.DecimalField(max_digits=4, decimal_places=2)
    horas_sabado = models.DecimalField(max_digits=4, decimal_places=2)
    horas_domingo = models.DecimalField(max_digits=4, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("nome",)

    def __str__(self) -> str:
        return self.nome


class WorkCalendarPeriod(models.Model):
    TYPE_HOLIDAY = "holiday"
    TYPE_BRIDGE = "bridge"
    TYPE_COLLECTIVE_VACATION = "collective_vacation"
    TYPE_CHOICES = (
        (TYPE_HOLIDAY, "Feriado"),
        (TYPE_BRIDGE, "Ponte"),
        (TYPE_COLLECTIVE_VACATION, "Ferias coletivas"),
    )

    calendar = models.ForeignKey(
        "WorkCalendar",
        on_delete=models.CASCADE,
        related_name="periods",
    )
    period_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)
    description = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-start_date", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="work_calendar_period_end_after_start",
            )
        ]

    def __str__(self) -> str:
        return f"{self.calendar} - {self.get_period_type_display()} - {self.start_date} a {self.end_date}"


class Sector(models.Model):
    department = models.ForeignKey(
        "Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sectors",
    )
    nome = models.CharField(max_length=120)
    deactivated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "setores"
        ordering = ("nome",)
        constraints = [
            models.UniqueConstraint(
                fields=("department", "nome"),
                condition=models.Q(deactivated_at__isnull=True),
                name="uniq_setor_departamento_nome_ativo_nao_desativado",
            )
        ]

    @property
    def full_name(self) -> str:
        if self.department_id:
            return f"{self.department.full_name} / {self.nome}"
        return self.nome

    def __str__(self) -> str:
        return self.full_name


class Area(models.Model):
    nome = models.CharField(max_length=120)
    deactivated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "areas"
        ordering = ("nome",)
        constraints = [
            models.UniqueConstraint(
                fields=("nome",),
                condition=models.Q(deactivated_at__isnull=True),
                name="uniq_area_nome_ativo_nao_desativado",
            )
        ]

    def __str__(self) -> str:
        return self.nome


class Department(models.Model):
    area = models.ForeignKey(
        "Area",
        on_delete=models.PROTECT,
        related_name="departments",
    )
    nome = models.CharField(max_length=120)
    deactivated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "departamentos"
        ordering = ("nome",)
        constraints = [
            models.UniqueConstraint(
                fields=("area", "nome"),
                condition=models.Q(deactivated_at__isnull=True),
                name="uniq_departamento_area_nome_ativo_nao_desativado",
            )
        ]

    @property
    def full_name(self) -> str:
        return f"{self.area.nome} / {self.nome}"

    def __str__(self) -> str:
        return self.full_name


class Cargo(models.Model):
    nome = models.CharField(max_length=120)
    deactivated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cargos"
        ordering = ("nome",)
        constraints = [
            models.UniqueConstraint(
                fields=("nome",),
                condition=models.Q(deactivated_at__isnull=True),
                name="uniq_cargo_nome_ativo_nao_desativado",
            )
        ]

    def __str__(self) -> str:
        return self.nome

