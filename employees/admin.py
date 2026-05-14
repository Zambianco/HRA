from django.contrib import admin

from .models import (
    Employee,
    Sector,
    TimesheetImportReport,
    TimesheetImportReportRow,
    WorkSchedule,
)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "matricula",
        "nome_completo",
        "sector",
        "work_schedule",
        "deactivated_at",
        "created_at",
    )
    search_fields = ("matricula", "nome_completo", "sector__nome", "work_schedule__nome")
    list_filter = ("deactivated_at", "sector", "work_schedule")


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ("id", "nome", "deactivated_at", "created_at")
    search_fields = ("nome",)
    list_filter = ("deactivated_at",)


@admin.register(WorkSchedule)
class WorkScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "nome",
        "horas_segunda",
        "horas_terca",
        "horas_quarta",
        "horas_quinta",
        "horas_sexta",
        "horas_sabado",
        "horas_domingo",
        "created_at",
    )
    search_fields = ("nome",)


class TimesheetImportReportRowInline(admin.TabularInline):
    model = TimesheetImportReportRow
    extra = 0
    readonly_fields = (
        "row_type",
        "registration",
        "employee_name",
        "regular_minutes",
        "overtime_60_minutes",
        "overtime_100_minutes",
        "absence_unexcused_minutes",
        "absence_excused_minutes",
        "absence_bank_minutes",
        "issues",
    )
    can_delete = False


@admin.register(TimesheetImportReport)
class TimesheetImportReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "competence_month",
        "source_file_name",
        "status",
        "applied_entries_count",
        "created_at",
        "approved_at",
        "rejected_at",
    )
    list_filter = ("status", "competence_month")
    search_fields = ("source_file_name",)
    inlines = (TimesheetImportReportRowInline,)
