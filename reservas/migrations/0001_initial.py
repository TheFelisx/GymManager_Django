import datetime
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


METODOS = [('EFECTIVO', 'Efectivo'), ('DEBITO', 'Tarjeta de Débito'), ('CREDITO', 'Tarjeta de Crédito'), ('TRANSFERENCIA', 'Transferencia Bancaria')]


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('panel', '0003_plan_clases_por_semana'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Tarifa',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('precio_clase_suelta', models.PositiveIntegerField(default=5000, verbose_name='Precio de la clase suelta (CLP)')),
                ('prueba_gratis', models.BooleanField(default=True, verbose_name='Primera clase de prueba gratis (una por persona)')),
                ('porcentaje_externos', models.PositiveSmallIntegerField(default=20, verbose_name='% de cupo reservado a externos')),
                ('punta_inicio', models.TimeField(default=datetime.time(18, 0), verbose_name='Inicio de hora punta')),
                ('punta_fin', models.TimeField(default=datetime.time(21, 0), verbose_name='Fin de hora punta')),
            ],
            options={'verbose_name': 'Tarifa', 'verbose_name_plural': 'Tarifas'},
        ),
        migrations.CreateModel(
            name='Sala',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100, unique=True, verbose_name='Nombre')),
                ('capacidad', models.PositiveSmallIntegerField(verbose_name='Capacidad máxima')),
                ('descripcion', models.TextField(blank=True, verbose_name='Descripción')),
                ('foto', models.ImageField(blank=True, null=True, upload_to='salas/', verbose_name='Foto')),
                ('precio_hora', models.PositiveIntegerField(default=0, verbose_name='Arriendo por hora (CLP)')),
                ('precio_hora_punta', models.PositiveIntegerField(blank=True, help_text='Vacío = mismo valor que el normal.', null=True, verbose_name='Arriendo por hora en hora punta (CLP)')),
                ('activa', models.BooleanField(default=True, verbose_name='Sala activa')),
            ],
            options={'verbose_name': 'Sala', 'verbose_name_plural': 'Salas', 'ordering': ['nombre']},
        ),
        migrations.CreateModel(
            name='BloqueoFecha',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha_desde', models.DateField(verbose_name='Desde')),
                ('fecha_hasta', models.DateField(verbose_name='Hasta')),
                ('motivo', models.CharField(max_length=150, verbose_name='Motivo')),
                ('sala', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='bloqueos', to='reservas.sala', verbose_name='Sala (vacío = todas)')),
            ],
            options={'verbose_name': 'Bloqueo de fechas', 'verbose_name_plural': 'Bloqueos de fechas', 'ordering': ['-fecha_desde']},
        ),
        migrations.CreateModel(
            name='Clase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100, verbose_name='Nombre')),
                ('descripcion', models.TextField(blank=True, verbose_name='Descripción')),
                ('nivel', models.CharField(choices=[('TODOS', 'Todos los niveles'), ('BASICO', 'Básico'), ('INTERMEDIO', 'Intermedio'), ('AVANZADO', 'Avanzado')], default='TODOS', max_length=12, verbose_name='Nivel')),
                ('duracion_min', models.PositiveSmallIntegerField(default=60, verbose_name='Duración (minutos)')),
                ('cupo', models.PositiveSmallIntegerField(verbose_name='Cupo')),
                ('dias_semana', models.CharField(max_length=20, verbose_name='Días (0=Lun .. 6=Dom)')),
                ('hora_inicio', models.TimeField(verbose_name='Hora de inicio')),
                ('activa', models.BooleanField(default=True, verbose_name='Clase activa')),
                ('instructor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='clases_a_cargo', to=settings.AUTH_USER_MODEL, verbose_name='Instructor')),
                ('sala', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='clases', to='reservas.sala', verbose_name='Sala')),
            ],
            options={'verbose_name': 'Clase', 'verbose_name_plural': 'Clases', 'ordering': ['nombre', 'hora_inicio']},
        ),
        migrations.CreateModel(
            name='Sesion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField()),
                ('hora_inicio', models.TimeField()),
                ('hora_fin', models.TimeField()),
                ('estado', models.CharField(choices=[('NORMAL', 'Normal'), ('CANCELADA', 'Cancelada')], default='NORMAL', max_length=10)),
                ('motivo_cancelacion', models.CharField(blank=True, max_length=200)),
                ('cerrada', models.BooleanField(default=False)),
                ('clase', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='sesiones', to='reservas.clase')),
                ('instructor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sesiones_suplente', to=settings.AUTH_USER_MODEL, verbose_name='Instructor suplente')),
            ],
            options={'verbose_name': 'Sesión', 'verbose_name_plural': 'Sesiones', 'ordering': ['fecha', 'hora_inicio'], 'unique_together': {('clase', 'fecha')}},
        ),
        migrations.CreateModel(
            name='Visitante',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=120)),
                ('rut', models.CharField(max_length=12, unique=True)),
                ('email', models.EmailField(max_length=254)),
                ('email_verificado', models.BooleanField(default=False)),
                ('telefono', models.CharField(max_length=20)),
                ('fecha_nacimiento', models.DateField()),
                ('acepto_terminos', models.BooleanField(default=False)),
                ('acepto_en', models.DateTimeField(blank=True, null=True)),
                ('apoderado_nombre', models.CharField(blank=True, max_length=120)),
                ('apoderado_rut', models.CharField(blank=True, max_length=12)),
                ('creado', models.DateTimeField(auto_now_add=True)),
            ],
            options={'verbose_name': 'Visitante', 'verbose_name_plural': 'Visitantes', 'ordering': ['-creado']},
        ),
        migrations.CreateModel(
            name='Inscripcion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('estado', models.CharField(choices=[('CONFIRMADA', 'Confirmada'), ('EN_ESPERA', 'En lista de espera'), ('CANCELADA', 'Cancelada'), ('ASISTIO', 'Asistió'), ('NO_ASISTIO', 'No asistió')], default='CONFIRMADA', max_length=12)),
                ('creada', models.DateTimeField(auto_now_add=True)),
                ('en_espera_desde', models.DateTimeField(blank=True, null=True)),
                ('marcada_en', models.DateTimeField(blank=True, null=True)),
                ('codigo', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('es_prueba', models.BooleanField(default=False, verbose_name='Clase de prueba gratis')),
                ('monto', models.PositiveIntegerField(default=0)),
                ('monto_pagado', models.PositiveIntegerField(default=0)),
                ('metodo_pago', models.CharField(blank=True, choices=METODOS, max_length=15)),
                ('fecha_pago', models.DateTimeField(blank=True, null=True)),
                ('reembolsado', models.BooleanField(default=False)),
                ('cobrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('creada_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('marcada_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('sesion', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='inscripciones', to='reservas.sesion')),
                ('socio', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='inscripciones', to='panel.socio')),
                ('visitante', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='inscripciones', to='reservas.visitante')),
            ],
            options={'verbose_name': 'Inscripción', 'verbose_name_plural': 'Inscripciones', 'ordering': ['sesion__fecha', 'sesion__hora_inicio', 'id']},
        ),
        migrations.CreateModel(
            name='ReservaSala',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField()),
                ('hora_inicio', models.TimeField()),
                ('hora_fin', models.TimeField()),
                ('motivo', models.CharField(max_length=200)),
                ('personas', models.PositiveSmallIntegerField(default=1)),
                ('estado', models.CharField(choices=[('SOLICITADA', 'Solicitada'), ('APROBADA', 'Aprobada'), ('RECHAZADA', 'Rechazada'), ('CANCELADA', 'Cancelada')], default='APROBADA', max_length=12)),
                ('origen', models.CharField(choices=[('INTERNA', 'Interna (personal)'), ('VISITANTE', 'Visitante')], default='INTERNA', max_length=10)),
                ('creada', models.DateTimeField(auto_now_add=True)),
                ('aprobada_en', models.DateTimeField(blank=True, null=True)),
                ('nota', models.CharField(blank=True, max_length=200)),
                ('codigo', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('precio', models.PositiveIntegerField(default=0)),
                ('monto_pagado', models.PositiveIntegerField(default=0)),
                ('metodo_pago', models.CharField(blank=True, choices=METODOS, max_length=15)),
                ('fecha_pago', models.DateTimeField(blank=True, null=True)),
                ('reembolsado', models.BooleanField(default=False)),
                ('cobrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('creada_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('resuelta_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('sala', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='reservas', to='reservas.sala')),
                ('visitante', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reservas_sala', to='reservas.visitante')),
            ],
            options={'verbose_name': 'Reserva de sala', 'verbose_name_plural': 'Reservas de sala', 'ordering': ['fecha', 'hora_inicio']},
        ),
        migrations.CreateModel(
            name='SolicitudCambio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[('CANCELAR', 'Cancelar la sesión'), ('SUPLENCIA', 'Pedir suplente')], max_length=10)),
                ('motivo', models.CharField(max_length=200)),
                ('estado', models.CharField(choices=[('PENDIENTE', 'Pendiente'), ('APROBADA', 'Aprobada'), ('RECHAZADA', 'Rechazada')], default='PENDIENTE', max_length=10)),
                ('creada', models.DateTimeField(auto_now_add=True)),
                ('nota', models.CharField(blank=True, max_length=200)),
                ('resuelta_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('sesion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='solicitudes', to='reservas.sesion')),
                ('solicitante', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='solicitudes_cambio', to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'Solicitud de cambio', 'verbose_name_plural': 'Solicitudes de cambio', 'ordering': ['-creada']},
        ),
    ]
