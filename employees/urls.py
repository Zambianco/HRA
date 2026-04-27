from django.urls import path
from django.views.generic import RedirectView

from .views import (
    employee_activate,
    employee_create_sector,
    employee_deactivate,
    employee_edit_page,
    employees_page,
    events_page,
    sector_activate,
    sector_deactivate,
    sector_edit_page,
    sectors_page,
    timesheet_page,
    timesheet_snapshots_audit_page,
    work_schedules_page,
)

urlpatterns = [
    path("", employees_page, name="home"),
    path("empregados/", employees_page, name="employees_page"),
    path("empregados/setores/novo/", employee_create_sector, name="employee_create_sector"),
    path("empregados/<int:employee_id>/editar/", employee_edit_page, name="employee_edit_page"),
    path("empregados/<int:employee_id>/desativar/", employee_deactivate, name="employee_deactivate"),
    path("empregados/<int:employee_id>/ativar/", employee_activate, name="employee_activate"),
    path("eventos/", events_page, name="events_page"),
    path("timesheet/", timesheet_page, name="timesheet_page"),
    path("timesheet/snapshots/", timesheet_snapshots_audit_page, name="timesheet_snapshots_audit_page"),
    path(
        "ponto/",
        RedirectView.as_view(pattern_name="timesheet_page", permanent=True, query_string=True),
    ),
    path(
        "ausencias/",
        RedirectView.as_view(pattern_name="events_page", permanent=True, query_string=True),
    ),
    path("setores/", sectors_page, name="sectors_page"),
    path("setores/<int:sector_id>/editar/", sector_edit_page, name="sector_edit_page"),
    path("setores/<int:sector_id>/desativar/", sector_deactivate, name="sector_deactivate"),
    path("setores/<int:sector_id>/ativar/", sector_activate, name="sector_activate"),
    path("escalas/", work_schedules_page, name="work_schedules_page"),
]
