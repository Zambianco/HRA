from django.db import migrations


def import_legacy_empregados(apps, schema_editor):
    connection = schema_editor.connection
    existing_tables = connection.introspection.table_names()
    if "empregados" not in existing_tables:
        return

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT OR IGNORE INTO employees_employee (matricula, nome_completo, criado_em)
            SELECT matricula, nome_completo, criado_em
            FROM empregados
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            import_legacy_empregados,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
