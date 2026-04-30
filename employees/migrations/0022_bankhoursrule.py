from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0021_cargo_employee_cargo"),
    ]

    operations = [
        migrations.CreateModel(
            name="BankHoursRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("start_month", models.DateField(db_index=True)),
                ("end_month", models.DateField(db_index=True)),
                ("target_column", models.CharField(choices=[("B", "B - Hora banco"), ("C", "C - Horas com acrescimo"), ("F", "F - Saldo do mes")], max_length=1)),
                ("formula", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ("-start_month", "target_column", "-id"),
            },
        ),
        migrations.AddConstraint(
            model_name="bankhoursrule",
            constraint=models.CheckConstraint(
                condition=models.Q(("end_month__gte", models.F("start_month"))),
                name="bank_hours_rule_end_month_gte_start_month",
            ),
        ),
    ]
