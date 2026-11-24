import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Gasto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('concepto', models.CharField(max_length=150, verbose_name='Concepto / Descripción')),
                ('categoria', models.CharField(choices=[('ARRIENDO', 'Arriendo e Inmueble'), ('SERVICIOS', 'Servicios Básicos (Luz, Agua, Internet)'), ('SUELDOS', 'Sueldos y Honorarios'), ('EQUIPAMIENTO', 'Máquinas y Mantenimiento'), ('INSUMOS', 'Insumos y Limpieza'), ('OTROS', 'Otros Gastos')], default='OTROS', max_length=20, verbose_name='Categoría')),
                ('monto', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)], verbose_name='Monto (CLP)')),
                ('fecha', models.DateField(default=django.utils.timezone.localdate, verbose_name='Fecha del gasto')),
                ('fecha_registro', models.DateTimeField(auto_now_add=True)),
                ('registrado_por', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='Registrado por')),
            ],
            options={
                'verbose_name': 'Gasto',
                'verbose_name_plural': 'Gastos',
                'ordering': ['-fecha', '-fecha_registro'],
            },
        ),
    ]
