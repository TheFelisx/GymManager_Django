import datetime
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cuentas.models import Usuario
from panel.models import Pago, Plan, Socio
from totem.views import evaluar_acceso

from . import services as srv
from .models import Clase, Inscripcion, ReservaSala, Sala, Sesion, Tarifa, Visitante, combinar
from .services import ReglaError

CLAVE = "Gym12345!"


def usuario(username, rol):
    return Usuario.objects.create_user(username=username, password=CLAVE, rol=rol, debe_cambiar_clave=False,
                                       first_name=username, email=f"{username}@x.cl")


def socio(rut, plan=None, **plan_kw):
    u = Usuario.objects.create_user(username=rut, password=CLAVE, rol='SOCIO', debe_cambiar_clave=False,
                                    first_name="S" + rut, email=f"{rut}@x.cl")
    s = Socio.objects.create(usuario=u, rut=rut, fecha_nacimiento=datetime.date(1990, 1, 1), telefono="+56911112222")
    if plan:
        Pago.objects.create(socio=s, plan=plan, monto_pagado=plan.precio)
    return s


def sesion_futura(clase, dias=1, hora=None):
    fecha = timezone.localdate() + timedelta(days=dias)
    hora = hora or clase.hora_inicio
    return Sesion.objects.create(clase=clase, fecha=fecha, hora_inicio=hora, hora_fin=clase.hora_fin)


class Base(TestCase):
    def setUp(self):
        Tarifa.obtener()
        self.plan = Plan.objects.create(nombre="Full", precio=30000, duracion_dias=30)
        self.sala = Sala.objects.create(nombre="Funcional", capacidad=4, precio_hora=10000, precio_hora_punta=20000)
        self.instructor = usuario("inst", 'INSTRUCTOR')
        self.clase = Clase.objects.create(nombre="Yoga", sala=self.sala, instructor=self.instructor, cupo=10,
                                          dias_semana="0,1,2,3,4,5,6", hora_inicio=datetime.time(12, 0))


class CuposYListaDeEsperaTests(Base):
    def test_el_cupo_se_limita_a_la_capacidad_de_la_sala(self):
        self.assertEqual(self.clase.cupo_efectivo, 4)

    def test_cupo_reservado_a_externos_y_lista_de_espera(self):
        s = sesion_futura(self.clase)           # cupo 4, 20% externos => 1 reservado
        self.assertEqual(s.externos_reservados, 1)
        socios = [socio(f"1000000{i}", self.plan) for i in range(5)]
        estados = []
        for so in socios[:4]:
            estados.append(srv.inscribir_socio(so, s).estado)
        # Solo 3 socios caben: el cuarto queda esperando por el cupo reservado a externos
        self.assertEqual(estados.count('CONFIRMADA'), 3)
        self.assertEqual(estados[3], 'EN_ESPERA')

    def test_al_cancelar_se_promueve_al_primero_de_la_espera(self):
        s = sesion_futura(self.clase, dias=3)
        socios = [socio(f"2000000{i}", self.plan) for i in range(4)]
        insc = [srv.inscribir_socio(x, s) for x in socios]
        self.assertEqual(insc[3].estado, 'EN_ESPERA')
        srv.cancelar_inscripcion(insc[0])
        insc[3].refresh_from_db()
        self.assertEqual(insc[3].estado, 'CONFIRMADA')

    def test_no_se_inscribe_dos_veces(self):
        s = sesion_futura(self.clase)
        so = socio("30000001", self.plan)
        srv.inscribir_socio(so, s)
        with self.assertRaises(ReglaError):
            srv.inscribir_socio(so, s)


class ReglasDeSociosTests(Base):
    def test_sin_membresia_no_reserva(self):
        s = sesion_futura(self.clase)
        with self.assertRaises(ReglaError):
            srv.inscribir_socio(socio("40000001"), s)

    def test_plan_sin_clases_y_con_tope_semanal(self):
        s = sesion_futura(self.clase)
        sin_clases = Plan.objects.create(nombre="Sala", precio=1000, duracion_dias=30, clases_por_semana=0)
        with self.assertRaises(ReglaError):
            srv.inscribir_socio(socio("40000002", sin_clases), s)
        una = Plan.objects.create(nombre="Una", precio=1000, duracion_dias=30, clases_por_semana=1)
        so = socio("40000003", una)
        srv.inscribir_socio(so, s)
        otra_clase = Clase.objects.create(nombre="Box", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6",
                                          hora_inicio=datetime.time(15, 0))
        with self.assertRaises(ReglaError):
            srv.inscribir_socio(so, sesion_futura(otra_clase))

    def test_choque_de_horarios(self):
        so = socio("40000004", self.plan)
        srv.inscribir_socio(so, sesion_futura(self.clase))
        otra = Clase.objects.create(nombre="Box", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6",
                                    hora_inicio=datetime.time(12, 30))
        with self.assertRaises(ReglaError):
            srv.inscribir_socio(so, sesion_futura(otra))

    def test_maximo_tres_reservas_activas(self):
        so = socio("40000005", self.plan)
        for i, h in enumerate((8, 10, 14)):
            c = Clase.objects.create(nombre=f"C{i}", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=datetime.time(h, 0))
            srv.inscribir_socio(so, sesion_futura(c))
        c4 = Clase.objects.create(nombre="C4", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=datetime.time(17, 0))
        with self.assertRaises(ReglaError):
            srv.inscribir_socio(so, sesion_futura(c4))

    def test_cancelar_solo_hasta_dos_horas_antes(self):
        hoy = timezone.localdate()
        ahora = timezone.localtime()
        inicio = (ahora + timedelta(minutes=90)).time().replace(second=0, microsecond=0)
        if (ahora + timedelta(minutes=90)).date() != hoy:
            self.skipTest("Muy cerca de medianoche")
        c = Clase.objects.create(nombre="Hoy", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=inicio)
        s = Sesion.objects.create(clase=c, fecha=hoy, hora_inicio=inicio, hora_fin=c.hora_fin)
        insc = Inscripcion.objects.create(sesion=s, socio=socio("40000006", self.plan))
        with self.assertRaises(ReglaError):
            srv.cancelar_inscripcion(insc)

    def test_tres_faltas_bloquean_las_reservas(self):
        so = socio("40000007", self.plan)
        for i in range(3):
            c = Clase.objects.create(nombre=f"F{i}", sala=self.sala, cupo=4, dias_semana="0", hora_inicio=datetime.time(9 + i, 0))
            ses = Sesion.objects.create(clase=c, fecha=timezone.localdate() - timedelta(days=i + 1),
                                        hora_inicio=c.hora_inicio, hora_fin=c.hora_fin)
            Inscripcion.objects.create(sesion=ses, socio=so, estado='NO_ASISTIO')
        with self.assertRaises(ReglaError):
            srv.inscribir_socio(so, sesion_futura(self.clase))

    def test_cerrar_sesion_marca_no_asistio(self):
        ayer = timezone.localdate() - timedelta(days=1)
        s = Sesion.objects.create(clase=self.clase, fecha=ayer, hora_inicio=self.clase.hora_inicio, hora_fin=self.clase.hora_fin)
        a, b = socio("40000008", self.plan), socio("40000009", self.plan)
        ia = Inscripcion.objects.create(sesion=s, socio=a)
        ib = Inscripcion.objects.create(sesion=s, socio=b)
        srv.marcar_asistencia(ia, self.instructor, True)
        srv.cerrar_sesion(s, self.instructor)
        ia.refresh_from_db(); ib.refresh_from_db()
        self.assertEqual(ia.estado, 'ASISTIO')
        self.assertEqual(ib.estado, 'NO_ASISTIO')

    def test_no_se_cierra_ni_se_marca_antes_de_la_clase(self):
        s = sesion_futura(self.clase, dias=2)
        insc = srv.inscribir_socio(socio("40000011", self.plan), s)
        with self.assertRaises(ReglaError):
            srv.cerrar_sesion(s, self.instructor)
        with self.assertRaises(ReglaError):
            srv.marcar_asistencia(insc, self.instructor, True)

    def test_clases_olvidadas_se_cierran_solas(self):
        antes = timezone.localdate() - timedelta(days=3)
        s = Sesion.objects.create(clase=self.clase, fecha=antes, hora_inicio=self.clase.hora_inicio, hora_fin=self.clase.hora_fin)
        insc = Inscripcion.objects.create(sesion=s, socio=socio("40000012", self.plan))
        self.assertEqual(srv.cerrar_vencidas(), 1)
        insc.refresh_from_db(); s.refresh_from_db()
        self.assertEqual(insc.estado, 'NO_ASISTIO')
        self.assertTrue(s.cerrada)

    def test_suspender_y_reactivar_una_clase(self):
        s = sesion_futura(self.clase, dias=3)
        insc = srv.inscribir_socio(socio("40000013", self.plan), s)
        srv.suspender_clase(self.clase)
        insc.refresh_from_db(); s.refresh_from_db()
        self.assertEqual(insc.estado, 'CANCELADA')
        self.assertTrue(s.cancelada)
        srv.reactivar_clase(self.clase)
        s.refresh_from_db()
        self.assertFalse(s.cancelada)

    def test_cancelar_una_sesion_cancela_las_inscripciones(self):
        s = sesion_futura(self.clase)
        insc = srv.inscribir_socio(socio("40000010", self.plan), s)
        srv.cancelar_sesion(s, "Instructor enfermo")
        insc.refresh_from_db(); s.refresh_from_db()
        self.assertEqual(insc.estado, 'CANCELADA')
        self.assertTrue(s.cancelada)


def visitante(rut="50000001", edad=30, email="v@x.cl"):
    nac = timezone.localdate().replace(year=timezone.localdate().year - edad)
    return Visitante.objects.create(nombre="Vera", rut=rut, email=email, telefono="+56911112222",
                                    fecha_nacimiento=nac, acepto_terminos=True)


class VisitantesTests(Base):
    def test_primera_clase_gratis_y_luego_pagada(self):
        v = visitante()
        i1 = srv.inscribir_visitante(v, sesion_futura(self.clase, 1))
        self.assertTrue(i1.es_prueba)
        self.assertEqual(i1.monto, 0)
        otra = Clase.objects.create(nombre="Otra", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=datetime.time(18, 0))
        i2 = srv.inscribir_visitante(v, sesion_futura(otra, 2))
        self.assertFalse(i2.es_prueba)
        self.assertEqual(i2.monto, Tarifa.obtener().precio_clase_suelta)

    def test_menores_de_14_no_y_menores_de_18_necesitan_apoderado(self):
        with self.assertRaises(ReglaError):
            srv.inscribir_visitante(visitante("50000002", edad=12), sesion_futura(self.clase))
        with self.assertRaises(ReglaError):
            srv.inscribir_visitante(visitante("50000003", edad=16), sesion_futura(self.clase))

    def test_codigo_de_visita_exige_pago_y_horario(self):
        v = visitante("50000004")
        otra = Clase.objects.create(nombre="Pago", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=datetime.time(18, 0))
        srv.inscribir_visitante(v, sesion_futura(self.clase, 1))        # su prueba gratis
        insc = srv.inscribir_visitante(v, sesion_futura(otra, 2))        # pagada
        guardia = usuario("guardia", 'GUARDIA')
        r = srv.evaluar_codigo_visita(str(insc.codigo), guardia)
        self.assertFalse(r['permitido'])                                 # pago pendiente
        srv.registrar_pago_inscripcion(insc, 'EFECTIVO', guardia)
        r = srv.evaluar_codigo_visita(str(insc.codigo), guardia)
        self.assertFalse(r['permitido'])                                 # fuera de horario (es en 2 días)

    def test_pago_se_registra_una_sola_vez(self):
        v = visitante("50000005")
        srv.inscribir_visitante(v, sesion_futura(self.clase, 1))
        otra = Clase.objects.create(nombre="Pago2", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=datetime.time(18, 0))
        insc = srv.inscribir_visitante(v, sesion_futura(otra, 2))
        srv.registrar_pago_inscripcion(insc, 'EFECTIVO', usuario("rec", 'RECEPCIONISTA'))
        with self.assertRaises(ReglaError):
            srv.registrar_pago_inscripcion(insc, 'EFECTIVO', usuario("rec2", 'RECEPCIONISTA'))


class SalasTests(Base):
    def test_precio_con_hora_punta(self):
        fecha = timezone.localdate() + timedelta(days=5)
        # 17:30-19:00: 30 min normales ($5.000) + 60 min punta ($20.000)
        self.assertEqual(srv.calcular_precio_sala(self.sala, fecha, datetime.time(17, 30), datetime.time(19, 0)), 25000)

    def test_no_se_pisa_una_sala_ni_una_clase(self):
        fecha = timezone.localdate() + timedelta(days=5)
        Sesion.objects.create(clase=self.clase, fecha=fecha, hora_inicio=datetime.time(12, 0), hora_fin=self.clase.hora_fin)
        with self.assertRaises(ReglaError):
            srv.crear_reserva_sala(self.sala, fecha, datetime.time(12, 30), datetime.time(13, 30), "x")
        # Con 15 minutos de limpieza: la clase termina 13:00, no se puede empezar a las 13:10
        with self.assertRaises(ReglaError):
            srv.crear_reserva_sala(self.sala, fecha, datetime.time(13, 10), datetime.time(14, 10), "x")
        r = srv.crear_reserva_sala(self.sala, fecha, datetime.time(13, 15), datetime.time(14, 15), "ok")
        self.assertEqual(r.estado, 'APROBADA')
        with self.assertRaises(ReglaError):
            srv.crear_reserva_sala(self.sala, fecha, datetime.time(14, 0), datetime.time(15, 0), "otra")

    def test_visitante_arriendo_reglas(self):
        fecha = timezone.localdate() + timedelta(days=5)
        v = visitante("60000001")
        with self.assertRaises(ReglaError):      # menos de 1 hora
            srv.crear_reserva_sala(self.sala, fecha, datetime.time(10, 0), datetime.time(10, 30), "x", visitante=v)
        with self.assertRaises(ReglaError):      # más de 4 horas
            srv.crear_reserva_sala(self.sala, fecha, datetime.time(10, 0), datetime.time(15, 0), "x", visitante=v)
        r = srv.crear_reserva_sala(self.sala, fecha, datetime.time(10, 0), datetime.time(12, 0), "cumple", 3, visitante=v)
        self.assertEqual(r.estado, 'SOLICITADA')
        srv.aprobar_reserva(r, usuario("adm", 'ADMIN'))
        r.refresh_from_db()
        self.assertEqual(r.estado, 'APROBADA')

    def test_arriendo_requiere_48_horas_y_adulto(self):
        manana = timezone.localdate() + timedelta(days=1)
        with self.assertRaises(ReglaError):
            srv.crear_reserva_sala(self.sala, manana, datetime.time(10, 0), datetime.time(12, 0), "x", visitante=visitante("60000002"))
        lejos = timezone.localdate() + timedelta(days=6)
        with self.assertRaises(ReglaError):
            srv.crear_reserva_sala(self.sala, lejos, datetime.time(10, 0), datetime.time(12, 0), "x", visitante=visitante("60000003", edad=17))

    def test_sala_bloqueada_por_feriado(self):
        from .models import BloqueoFecha
        fecha = timezone.localdate() + timedelta(days=5)
        BloqueoFecha.objects.create(fecha_desde=fecha, fecha_hasta=fecha, motivo="Feriado")
        with self.assertRaises(ReglaError):
            srv.crear_reserva_sala(self.sala, fecha, datetime.time(10, 0), datetime.time(12, 0), "x")
        self.assertEqual(srv.generar_sesiones(dias=10, clases=[self.clase]) >= 0, True)
        self.assertFalse(Sesion.objects.filter(clase=self.clase, fecha=fecha).exists())


class PermisosReservasTests(Base):
    def test_rutas_por_rol(self):
        recep, admin = usuario("rec", 'RECEPCIONISTA'), usuario("adm", 'ADMIN')
        so = socio("70000001", self.plan)
        def ir(u, nombre):
            self.client.force_login(u)
            return self.client.get(reverse(nombre)).status_code
        self.assertEqual(ir(recep, 'reservas:ocupacion'), 200)
        self.assertEqual(ir(recep, 'reservas:crear_clase'), 403)
        self.assertEqual(ir(admin, 'reservas:crear_clase'), 200)
        self.assertEqual(ir(so.usuario, 'reservas:mis_clases'), 200)
        self.assertEqual(ir(so.usuario, 'reservas:ocupacion'), 403)
        self.assertEqual(ir(self.instructor, 'reservas:agenda'), 200)
        self.assertEqual(ir(self.instructor, 'reservas:ocupacion'), 403)
        self.assertEqual(ir(admin, 'reservas:solicitudes_cambio'), 200)
        self.assertEqual(ir(recep, 'reservas:solicitudes_cambio'), 403)

    def test_instructor_solo_ve_su_clase_y_en_ventana(self):
        otro = usuario("inst2", 'INSTRUCTOR')
        s = sesion_futura(self.clase, dias=1)
        self.client.force_login(otro)
        self.assertEqual(self.client.get(reverse('reservas:sesion_instructor', args=[s.pk])).status_code, 403)
        # Es su clase, pero falta más de 24 horas: no ve la lista
        lejos = sesion_futura(self.clase, dias=5)
        self.assertFalse(srv.instructor_puede_ver(self.instructor, lejos))

    def test_horario_publico_y_flujo_de_correo(self):
        self.assertEqual(self.client.get(reverse('reservas:horario')).status_code, 200)
        r = self.client.get(reverse('reservas:visitante_arrendar'))
        self.assertEqual(r.status_code, 302)       # exige correo verificado

    def test_totem_marca_asistencia_de_la_clase_en_curso(self):
        ahora = timezone.localtime()
        if (ahora + timedelta(minutes=10)).date() != ahora.date():
            self.skipTest("Muy cerca de medianoche")
        inicio = (ahora + timedelta(minutes=10)).time().replace(second=0, microsecond=0)
        c = Clase.objects.create(nombre="Ahora", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=inicio)
        s = Sesion.objects.create(clase=c, fecha=ahora.date(), hora_inicio=inicio, hora_fin=c.hora_fin)
        so = socio("70000002", self.plan)
        insc = Inscripcion.objects.create(sesion=s, socio=so)
        r = evaluar_acceso(so.rut, usuario("g", 'GUARDIA'))
        self.assertTrue(r['permitido'])
        insc.refresh_from_db()
        self.assertEqual(insc.estado, 'ASISTIO')


class ValidacionesTests(Base):
    def test_el_cobro_es_siempre_el_precio_completo(self):
        v = visitante("80000001")
        prueba = srv.inscribir_visitante(v, sesion_futura(self.clase, 1))      # primera clase: gratis
        with self.assertRaises(ReglaError):                                     # a la clase de prueba no se le puede cobrar
            srv.registrar_pago_inscripcion(prueba, 'EFECTIVO', usuario("rx", 'RECEPCIONISTA'))
        otra = Clase.objects.create(nombre="Pago3", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=datetime.time(18, 0))
        insc = srv.inscribir_visitante(v, sesion_futura(otra, 2))
        srv.registrar_pago_inscripcion(insc, 'DEBITO', usuario("ry", 'RECEPCIONISTA'))
        insc.refresh_from_db()
        self.assertEqual(insc.monto_pagado, Tarifa.obtener().precio_clase_suelta)   # el monto no se elige
        with self.assertRaises(ReglaError):
            srv.registrar_pago_inscripcion(insc, 'DEBITO', usuario("rz", 'RECEPCIONISTA'))
        with self.assertRaises(ReglaError):                                     # método inválido
            srv.registrar_pago_inscripcion(insc, 'BITCOIN', usuario("rw", 'RECEPCIONISTA'))

    def test_arriendo_se_cobra_completo(self):
        fecha = timezone.localdate() + timedelta(days=5)
        r = srv.crear_reserva_sala(self.sala, fecha, datetime.time(15, 0), datetime.time(17, 0), "x", visitante=visitante("80000007"))
        srv.aprobar_reserva(r, usuario("adm9", 'ADMIN'))
        r.refresh_from_db()
        srv.registrar_pago_reserva(r, 'TRANSFERENCIA', usuario("rq", 'RECEPCIONISTA'))
        r.refresh_from_db()
        self.assertEqual(r.monto_pagado, r.precio)

    def test_formulario_de_cobro_no_tiene_monto(self):
        from .forms import PagoVisitaForm
        self.assertEqual(list(PagoVisitaForm().fields), ['metodo'])

    def test_qr_de_visitante_solo_durante_la_clase(self):
        ahora = timezone.localtime()
        if not (datetime.time(1, 40) < ahora.time() < datetime.time(22, 30)):
            self.skipTest("Muy cerca de medianoche")
        guardia = usuario("gq", 'GUARDIA')
        v = visitante("80000008")
        # clase que empieza en 5 minutos: el código funciona (y permite reingresar)
        ini = (ahora + timedelta(minutes=5)).time().replace(second=0, microsecond=0)
        c = Clase.objects.create(nombre="Ahora2", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=ini)
        s = Sesion.objects.create(clase=c, fecha=ahora.date(), hora_inicio=ini, hora_fin=c.hora_fin)
        insc = Inscripcion.objects.create(sesion=s, visitante=v, es_prueba=True)
        r1 = srv.evaluar_codigo_visita(str(insc.codigo), guardia)
        self.assertTrue(r1['permitido'])
        self.assertIn('no se cobra', r1['motivo'])
        self.assertTrue(srv.evaluar_codigo_visita(str(insc.codigo), guardia)['permitido'])   # reingreso
        # clase que terminó hace rato: el código se desactiva
        ini2 = (ahora - timedelta(hours=1, minutes=30)).time().replace(second=0, microsecond=0)
        c2 = Clase.objects.create(nombre="Pasada", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=ini2, duracion_min=30)
        s2 = Sesion.objects.create(clase=c2, fecha=ahora.date(), hora_inicio=ini2, hora_fin=c2.hora_fin)
        v2 = visitante("80000009")
        insc2 = Inscripcion.objects.create(sesion=s2, visitante=v2, es_prueba=True)
        r2 = srv.evaluar_codigo_visita(str(insc2.codigo), guardia)
        self.assertFalse(r2['permitido'])
        self.assertIn('vencido', r2['motivo'].lower())
        self.assertEqual(srv.estado_codigo(insc2)[0], 'vencido')
        self.assertEqual(srv.estado_codigo(insc)[0], 'vigente')

    def test_qr_data_uri(self):
        self.assertTrue(srv.qr_data_uri("hola").startswith("data:image/png;base64,"))

    def test_visitante_maximo_de_reservas_activas(self):
        v = visitante("80000002")
        for i, h in enumerate((8, 10, 14)):
            c = Clase.objects.create(nombre=f"V{i}", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=datetime.time(h, 0))
            srv.inscribir_visitante(v, sesion_futura(c))
        c4 = Clase.objects.create(nombre="V4", sala=self.sala, cupo=4, dias_semana="0,1,2,3,4,5,6", hora_inicio=datetime.time(17, 0))
        with self.assertRaises(ReglaError):
            srv.inscribir_visitante(v, sesion_futura(c4))

    def test_reserva_de_sala_choca_con_clase_aun_sin_sesion(self):
        # La clase Yoga (12:00) existe todos los días pero aún no tiene sesión creada en esa fecha lejana.
        lejos = timezone.localdate() + timedelta(days=60)
        with self.assertRaises(ReglaError):
            srv.crear_reserva_sala(self.sala, lejos, datetime.time(12, 0), datetime.time(13, 0), "x")

    def test_formulario_de_clase_rechaza_datos_invalidos(self):
        from .forms import ClaseForm
        datos = {'nombre': 'Nueva', 'nivel': 'TODOS', 'duracion_min': 60, 'sala': self.sala.pk, 'cupo': 3,
                 'hora_inicio': '12:00', 'dias': ['0'], 'activa': 'on'}
        self.assertIn('hora_inicio', ClaseForm(datos).errors)                 # la sala ya está ocupada por Yoga
        self.assertIn('cupo', ClaseForm({**datos, 'cupo': 99, 'hora_inicio': '16:00'}).errors)   # supera la capacidad
        self.assertIn('duracion_min', ClaseForm({**datos, 'duracion_min': 0, 'hora_inicio': '16:00'}).errors)
        self.assertIn('duracion_min', ClaseForm({**datos, 'duracion_min': 90, 'hora_inicio': '23:00'}).errors)  # cruza medianoche
        self.assertIn('cupo', ClaseForm({**datos, 'cupo': 0, 'hora_inicio': '16:00'}).errors)
        self.assertEqual(ClaseForm({**datos, 'hora_inicio': '16:00'}).errors, {})

    def test_formulario_de_sala_y_tarifa(self):
        from .forms import SalaForm, TarifaForm
        base = {'nombre': 'Otra', 'capacidad': 10, 'precio_hora': 1000, 'activa': 'on'}
        self.assertIn('capacidad', SalaForm({**base, 'capacidad': 0}).errors)
        self.assertIn('precio_hora', SalaForm({**base, 'precio_hora': 0}).errors)      # toda sala debe tener su precio por hora
        self.assertIn('precio_hora', SalaForm({k: v for k, v in base.items() if k != 'precio_hora'}).errors)
        self.assertIn('precio_hora', SalaForm({**base, 'precio_hora': -5}).errors)
        self.assertIn('precio_hora_punta', SalaForm({**base, 'precio_hora_punta': 500}).errors)
        t = {'precio_clase_suelta': 5000, 'porcentaje_externos': 20, 'punta_inicio': '18:00', 'punta_fin': '21:00'}
        self.assertIn('precio_clase_suelta', TarifaForm({**t, 'precio_clase_suelta': -1}).errors)
        self.assertIn('porcentaje_externos', TarifaForm({**t, 'porcentaje_externos': 150}).errors)

    def test_no_se_desactiva_una_sala_con_clases(self):
        from .forms import SalaForm
        f = SalaForm({'nombre': self.sala.nombre, 'capacidad': 4, 'precio_hora': 10000, 'precio_hora_punta': 20000}, instance=self.sala)
        self.assertIn('activa', f.errors)

    def test_visitante_no_puede_cambiar_el_correo_de_otro_rut(self):
        from .forms import VisitanteForm
        visitante("80000006", email="real@x.cl")
        datos = {'nombre': 'X', 'rut': '80000006', 'email': 'otro@x.cl', 'telefono': '+56911112222',
                 'fecha_nacimiento': '1990-01-01', 'acepto_terminos': 'on'}
        self.assertIn('email', VisitanteForm(datos).errors)
        self.assertNotIn('email', VisitanteForm(datos, staff=True).errors)

    def test_bloqueo_de_fechas_invalidas(self):
        from .forms import BloqueoForm
        ayer = (timezone.localdate() - timedelta(days=2)).isoformat()
        self.assertIn('fecha_hasta', BloqueoForm({'fecha_desde': ayer, 'fecha_hasta': ayer, 'motivo': 'x'}).errors)


class PantallasYSalasTests(Base):
    def setUp(self):
        super().setUp()
        self.admin = usuario("adm_p", 'ADMIN')
        self.recep = usuario("rec_p", 'RECEPCIONISTA')

    def test_el_cierre_de_caja_ya_no_existe(self):
        from django.urls import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse('panel:cierre_turno')

    def test_cobranza_limita_las_filas_por_pantalla(self):
        for i in range(25):
            so = socio(f"9000{i:04d}")
            Pago.objects.create(socio=so, plan=self.plan, monto_pagado=self.plan.precio,
                                fecha_inicio=timezone.localdate() - timedelta(days=60))
        self.client.force_login(self.recep)
        r = self.client.get(reverse('panel:cobranza'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['pag_atrasados'].paginator.num_pages, 3)
        self.assertEqual(len(r.context['pag_atrasados']), 10)
        r3 = self.client.get(reverse('panel:cobranza') + '?p_atrasados=3')
        self.assertEqual(len(r3.context['pag_atrasados']), 5)

    def test_otras_tablas_tambien_se_paginan(self):
        for i in range(20):
            socio(f"9100{i:04d}", self.plan)
        self.client.force_login(self.recep)
        r = self.client.get(reverse('panel:lista_socios'))
        self.assertEqual(len(r.context['pagina']), 15)
        self.assertEqual(r.context['pagina'].paginator.num_pages, 2)

    def test_editar_clase_muestra_los_dias_como_casillas(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('reservas:editar_clase', args=[self.clase.pk]))
        html = r.content.decode()
        self.assertIn('form-check-inline', html)
        self.assertEqual(html.count('name="dias"'), 7)
        self.assertGreaterEqual(html.count('checked'), 7)  # los 7 días de la clase vienen marcados

    def test_clases_permiten_ver_y_agregar_gente(self):
        s = sesion_futura(self.clase, dias=1)
        self.client.force_login(self.recep)
        r = self.client.get(reverse('reservas:lista_clases'))
        html = r.content.decode()
        self.assertIn('Ver gente', html)
        self.assertIn('Agregar gente', html)
        self.assertIn(reverse('reservas:sesion_detalle', args=[s.pk]), html)
        self.assertEqual(self.client.get(reverse('reservas:clase_sesiones', args=[self.clase.pk])).status_code, 200)

    def test_reservar_sala_cobra_por_hora(self):
        self.client.force_login(self.recep)
        fecha = (timezone.localdate() + timedelta(days=5)).isoformat()
        r = self.client.post(reverse('reservas:reservar_sala'), {
            'sala': self.sala.pk, 'fecha': fecha, 'hora_inicio': '15:00', 'hora_fin': '17:00', 'personas': 2,
            'motivo': 'Entrenamiento personal', 'cobrar_ahora': 'on', 'metodo': 'EFECTIVO'})
        self.assertEqual(r.status_code, 302)
        res = ReservaSala.objects.get()
        self.assertEqual(res.precio, 20000)                       # 2 horas × $10.000
        self.assertEqual(res.monto_pagado, 20000)                 # se cobró el precio completo
        self.client.force_login(self.admin)
        fin = self.client.get(reverse('finanzas:inicio'))
        self.assertGreaterEqual(fin.context['total_ingresos'], 20000)

    def test_cobrar_ahora_exige_metodo(self):
        from .forms import ReservaSalaStaffForm
        fecha = (timezone.localdate() + timedelta(days=5)).isoformat()
        f = ReservaSalaStaffForm({'sala': self.sala.pk, 'fecha': fecha, 'hora_inicio': '15:00', 'hora_fin': '16:00',
                                  'personas': 1, 'motivo': 'x', 'cobrar_ahora': 'on'})
        self.assertIn('metodo', f.errors)

    def test_formulario_de_reserva_muestra_precio_por_hora(self):
        self.client.force_login(self.recep)
        html = self.client.get(reverse('reservas:reservar_sala')).content.decode()
        self.assertIn('por hora', html)
        self.assertIn('id="estimado"', html)
