"""Carga datos de ejemplo: un usuario por rol, planes, un socio, entrenadores y preguntas.

Uso:  python manage.py cargar_datos_ejemplo
Clave de todos los usuarios de ejemplo: Gym12345!  (solo para pruebas)
"""
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from cuentas.models import Usuario
from panel.models import Pago, Plan, Socio
from publica.models import Entrenador, PreguntaFrecuente
from reservas.models import Clase, Sala, Tarifa
from reservas.services import generar_sesiones

CLAVE = "Gym12345!"


class Command(BaseCommand):
    help = "Crea datos de ejemplo (un usuario por rol, planes, socio, entrenadores y FAQ)."

    @transaction.atomic
    def handle(self, *args, **opciones):
        for username, rol, nombre in [
            ("master.demo", Usuario.Rol.MASTER, "Mario"),
            ("admin.demo", Usuario.Rol.ADMIN, "Adriana"),
            ("recepcion.demo", Usuario.Rol.RECEPCIONISTA, "Rocío"),
            ("guardia.demo", Usuario.Rol.GUARDIA, "Gonzalo"),
            ("instructor.demo", Usuario.Rol.INSTRUCTOR, "Ignacio"),
        ]:
            u, creado = Usuario.objects.get_or_create(
                username=username,
                defaults={'rol': rol, 'first_name': nombre, 'last_name': 'Demo',
                          'email': f'{username}@example.com', 'debe_cambiar_clave': False},
            )
            if creado:
                u.set_password(CLAVE)
                u.save()

        plan_full, _ = Plan.objects.get_or_create(nombre="Plan Full", defaults={'precio': 30000, 'duracion_dias': 30})
        Plan.objects.get_or_create(nombre="Plan Mañana", defaults={
            'precio': 20000, 'duracion_dias': 30,
            'hora_inicio': datetime.time(6, 0), 'hora_fin': datetime.time(14, 0),
        })

        if not Socio.objects.filter(rut="111111111").exists():
            usuario = Usuario.objects.create_user(
                username="111111111", password=CLAVE, rol=Usuario.Rol.SOCIO,
                first_name="Sofía", last_name="Demo", email="socio.demo@example.com",
                debe_cambiar_clave=False,
            )
            socio = Socio.objects.create(
                usuario=usuario, rut="111111111",
                fecha_nacimiento=datetime.date(1995, 5, 20), telefono="+56911112222",
            )
            Pago.objects.create(socio=socio, plan=plan_full, monto_pagado=plan_full.precio,
                                metodo_pago=Pago.MetodoPago.EFECTIVO)

        if not Entrenador.objects.exists():
            Entrenador.objects.bulk_create([
                Entrenador(nombre="Camila Rojas", especialidad="Funcional y movilidad", orden=1),
                Entrenador(nombre="Diego Pérez", especialidad="Musculación", orden=2),
                Entrenador(nombre="Valentina Soto", especialidad="Cardio y spinning", orden=3),
            ])
        if not PreguntaFrecuente.objects.exists():
            PreguntaFrecuente.objects.bulk_create([
                PreguntaFrecuente(pregunta="¿Cómo me inscribo?", respuesta="Pasa por recepción con tu RUT. Te creamos la cuenta y tu credencial QR.", orden=1),
                PreguntaFrecuente(pregunta="¿Cómo entro al gimnasio?", respuesta="Muestras tu QR (o dices tu RUT) al guardia. Se valida tu plan y tu horario.", orden=2),
                PreguntaFrecuente(pregunta="¿Puedo cambiar de plan?", respuesta="Sí, en recepción al renovar tu membresía.", orden=3),
            ])
        Tarifa.obtener()
        if not Sala.objects.exists():
            sala = Sala.objects.create(nombre="Sala Funcional", capacidad=20, precio_hora=15000, precio_hora_punta=20000,
                                       descripcion="Sala amplia con espejos y piso deportivo.")
            Sala.objects.create(nombre="Sala Spinning", capacidad=12, precio_hora=12000)
            instructor = Usuario.objects.get(username="instructor.demo")
            Clase.objects.create(nombre="Funcional", descripcion="Entrenamiento de cuerpo completo.", sala=sala,
                                 instructor=instructor, cupo=15, dias_semana="0,2,4", hora_inicio=datetime.time(19, 0))
            Clase.objects.create(nombre="Yoga", descripcion="Movilidad y respiración.", sala=sala,
                                 instructor=instructor, cupo=10, dias_semana="1,3", hora_inicio=datetime.time(8, 0))
        generar_sesiones()
        self.stdout.write(self.style.SUCCESS(f"Datos de ejemplo listos. Usuarios: master.demo, admin.demo, recepcion.demo, guardia.demo, instructor.demo y el RUT 11111111-1 (clave {CLAVE})."))
