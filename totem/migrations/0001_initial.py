import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('panel', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RegistroAcceso',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('identificador_ingresado', models.CharField(max_length=100, verbose_name='RUT o Token leído')),
                ('metodo', models.CharField(choices=[('QR', 'Código QR'), ('RUT', 'RUT Manual')], default='RUT', max_length=10)),
                ('permitido', models.BooleanField(default=False, verbose_name='Acceso permitido')),
                ('motivo', models.CharField(max_length=200, verbose_name='Resultado / Motivo')),
                ('fecha_hora', models.DateTimeField(auto_now_add=True, verbose_name='Fecha y hora')),
                ('socio', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='accesos', to='panel.socio', verbose_name='Socio')),
                ('validado_por', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='Guardia / Personal')),
            ],
            options={
                'verbose_name': 'Registro de acceso',
                'verbose_name_plural': 'Registros de acceso',
                'ordering': ['-fecha_hora'],
            },
        ),
    ]
