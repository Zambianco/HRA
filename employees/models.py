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

    matricula = models.CharField(max_length=50, unique=True)
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

    def __str__(self) -> str:
        return f"{self.matricula} - {self.nome_completo}"


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
        (EVENT_TYPE_ABSENCE, "Ausencia"),
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


class WorkSchedule(models.Model):
    nome = models.CharField(max_length=120, unique=True)
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


class Sector(models.Model):
    nome = models.CharField(max_length=120)
    deactivated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "setores"
        ordering = ("nome",)
        constraints = [
            models.UniqueConstraint(
                fields=("nome",),
                condition=models.Q(deactivated_at__isnull=True),
                name="uniq_setor_nome_ativo_nao_desativado",
            )
        ]

    def __str__(self) -> str:
        return self.nome
