from django.contrib import admin

from .models import Employee, Sector, WorkSchedule


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
