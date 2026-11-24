import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cuentas.models import Usuario
from cuentas.utils import puede_gestionar
from cuentas.validators import validar_rut
from totem.views import evaluar_acceso

from .models import Pago, Plan, Socio

CLAVE = "Gym12345!"


def crear_usuario(username, rol):
    return Usuario.objects.create_user(username=username, password=CLAVE, rol=rol, debe_cambiar_clave=False)


def crear_socio(rut="111111111"):
    u = Usuario.objects.create_user(username=rut, password=CLAVE, rol='SOCIO', debe_cambiar_clave=False,
                                    first_name="Ana", last_name="Test")
    return Socio.objects.create(usuario=u, rut=rut, fecha_nacimiento=datetime.date(1990, 1, 1), telefono="+56911112222")


class RutTests(TestCase):
    def test_rut_valido_e_invalido(self):
        self.assertTrue(validar_rut("11.111.111-1"))
        self.assertFalse(validar_rut("11.111.111-2"))


class PagosTests(TestCase):
    def setUp(self):
        self.plan = Plan.objects.create(nombre="Full", precio=30000, duracion_dias=30)
        self.socio = crear_socio()

    def test_renovacion_parte_desde_el_mayor_entre_vencimiento_y_hoy(self):
        hoy = timezone.localdate()
        self.assertEqual(self.socio.fecha_inicio_renovacion(), hoy)   # sin pagos: hoy
        p1 = Pago.objects.create(socio=self.socio, plan=self.plan, monto_pagado=30000, fecha_inicio=hoy)
        self.assertEqual(self.socio.fecha_inicio_renovacion(), p1.fecha_vencimiento)   # vigente: su vencimiento

    def test_pago_anulado_no_da_vigencia(self):
        pago = Pago.objects.create(socio=self.socio, plan=self.plan, monto_pagado=30000)
        self.assertTrue(self.socio.esta_vigente)
        pago.anular("Error de digitación", crear_usuario("adm", 'ADMIN'))
        self.assertFalse(self.socio.esta_vigente)

    def test_baja_y_reactivacion_afectan_la_cuenta(self):
        self.socio.dar_de_baja("No renovó")
        self.socio.usuario.refresh_from_db()
        self.assertFalse(self.socio.usuario.is_active)
        self.socio.reactivar()
        self.socio.usuario.refresh_from_db()
        self.assertTrue(self.socio.usuario.is_active)

    def test_regenerar_qr_cambia_el_token(self):
        antes = self.socio.token_qr
        self.socio.regenerar_qr()
        self.assertNotEqual(antes, self.socio.token_qr)


class HorarioYAccesoTests(TestCase):
    def setUp(self):
        self.guardia = crear_usuario("guardia", 'GUARDIA')
        self.socio = crear_socio()

    def test_acceso_permitido_y_denegado_por_horario(self):
        plan = Plan.objects.create(nombre="Todo", precio=1000, duracion_dias=30)
        Pago.objects.create(socio=self.socio, plan=plan, monto_pagado=1000)
        self.assertTrue(evaluar_acceso(self.socio.rut, self.guardia)['permitido'])
        # Un plan sin el día de hoy deniega
        hoy = timezone.localtime().weekday()
        plan.dias_permitidos = ",".join(str(d) for d in range(7) if d != hoy)
        plan.save()
        self.assertFalse(evaluar_acceso(self.socio.rut, self.guardia)['permitido'])

    def test_sin_membresia_y_codigo_desconocido(self):
        self.assertFalse(evaluar_acceso(self.socio.rut, self.guardia)['permitido'])
        self.assertFalse(evaluar_acceso("99999999-9", self.guardia)['permitido'])

    def test_qr_regenerado_invalida_el_anterior(self):
        plan = Plan.objects.create(nombre="Todo", precio=1000, duracion_dias=30)
        Pago.objects.create(socio=self.socio, plan=plan, monto_pagado=1000)
        viejo = str(self.socio.token_qr)
        self.socio.regenerar_qr()
        self.assertFalse(evaluar_acceso(viejo, self.guardia)['permitido'])
        self.assertTrue(evaluar_acceso(str(self.socio.token_qr), self.guardia)['permitido'])


class PermisosPorRolTests(TestCase):
    def setUp(self):
        self.master = crear_usuario("master", 'MASTER')
        self.admin = crear_usuario("admin", 'ADMIN')
        self.recep = crear_usuario("recep", 'RECEPCIONISTA')
        self.guardia = crear_usuario("guardia", 'GUARDIA')
        self.socio = crear_socio()

    def ir(self, usuario, nombre, **kw):
        self.client.force_login(usuario)
        return self.client.get(reverse(nombre, kwargs=kw or None))

    def test_finanzas_solo_master_y_admin(self):
        self.assertEqual(self.ir(self.admin, 'finanzas:inicio').status_code, 200)
        self.assertEqual(self.ir(self.recep, 'finanzas:inicio').status_code, 403)
        self.assertEqual(self.ir(self.guardia, 'finanzas:inicio').status_code, 403)

    def test_panel_no_es_para_guardia_ni_socio(self):
        self.assertEqual(self.ir(self.recep, 'panel:lista_socios').status_code, 200)
        self.assertEqual(self.ir(self.guardia, 'panel:lista_socios').status_code, 403)
        self.assertEqual(self.ir(self.socio.usuario, 'panel:lista_socios').status_code, 403)

    def test_recepcion_no_anula_pagos_ni_ve_usuarios(self):
        self.assertEqual(self.ir(self.recep, 'panel:lista_usuarios').status_code, 403)
        plan = Plan.objects.create(nombre="Full", precio=1000, duracion_dias=30)
        pago = Pago.objects.create(socio=self.socio, plan=plan, monto_pagado=1000)
        self.assertEqual(self.ir(self.recep, 'panel:anular_pago', pk=pago.pk).status_code, 403)
        self.assertEqual(self.ir(self.admin, 'panel:anular_pago', pk=pago.pk).status_code, 200)

    def test_socio_solo_ve_su_zona(self):
        self.assertEqual(self.ir(self.socio.usuario, 'panel:zona_socio').status_code, 200)
        self.assertEqual(self.ir(self.recep, 'panel:zona_socio').status_code, 403)

    def test_guardia_valida_en_el_totem(self):
        self.client.force_login(self.guardia)
        r = self.client.post(reverse('totem:validar'), {'codigo': '99999999-9'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['permitido'])

    def test_reglas_de_gestion_entre_roles(self):
        self.assertTrue(puede_gestionar(self.master, self.admin))
        self.assertFalse(puede_gestionar(self.admin, self.master))
        self.assertFalse(puede_gestionar(self.admin, self.admin))
        self.assertTrue(puede_gestionar(self.admin, self.recep))
        self.assertTrue(puede_gestionar(self.recep, self.socio.usuario))
        self.assertFalse(puede_gestionar(self.recep, self.guardia))

    def test_no_se_desactiva_a_si_mismo_ni_al_ultimo_master(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('panel:alternar_usuario', kwargs={'pk': self.admin.pk}))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.client.force_login(self.master)
        self.client.post(reverse('panel:alternar_usuario', kwargs={'pk': self.master.pk}))
        self.master.refresh_from_db()
        self.assertTrue(self.master.is_active)

    def test_admin_no_puede_crear_administradores(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse('panel:crear_usuario_personal'), {
            'username': 'otro.admin', 'first_name': 'X', 'last_name': 'Y', 'email': 'x@y.cl',
            'rol': 'ADMIN', 'password': 'ClaveLarga123', 'password_confirm': 'ClaveLarga123',
        })
        self.assertEqual(r.status_code, 200)   # vuelve al formulario con error
        self.assertFalse(Usuario.objects.filter(username='otro.admin').exists())
