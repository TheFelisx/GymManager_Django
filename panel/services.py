"""Consultas reutilizables del panel (socios con estado, resúmenes, cobranza)."""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db.models import Count, Exists, Max, OuterRef, Q, Sum
from django.utils import timezone

from .models import Pago, Socio


def rango_dia(dia):
    """Devuelve (inicio, fin) de un día como datetimes con zona horaria.

    Se usan rangos en vez de __date porque en MySQL ese lookup devuelve vacío
    si no están cargadas las tablas de zona horaria.
    """
    tz = timezone.get_current_timezone()
    inicio = timezone.make_aware(datetime.combine(dia, time.min), tz)
    return inicio, inicio + timedelta(days=1)


def rango_fechas(desde, hasta):
    """(inicio, fin) aware que cubre desde `desde` hasta `hasta` inclusive."""
    inicio, _ = rango_dia(desde)
    _, fin = rango_dia(hasta)
    return inicio, fin


def socios_con_estado():
    """Socios con `vigente` (tiene un pago que cubre hoy) y `ultimo_venc`."""
    hoy = timezone.localdate()
    cubre_hoy = Pago.objects.filter(
        socio=OuterRef('pk'), anulado=False,
        fecha_inicio__lte=hoy, fecha_vencimiento__gte=hoy,
    )
    return Socio.objects.select_related('usuario').annotate(
        vigente=Exists(cubre_hoy),
        ultimo_venc=Max('pagos__fecha_vencimiento', filter=Q(pagos__anulado=False)),
    )


def filtrar_por_estado(socios, estado):
    """Estados: activo (vigente), vencido (cuenta activa sin plan vigente), baja."""
    if estado == 'activo':
        return socios.filter(usuario__is_active=True, vigente=True)
    if estado == 'vencido':
        return socios.filter(usuario__is_active=True, vigente=False)
    if estado == 'baja':
        return socios.filter(usuario__is_active=False)
    return socios


def pagos_validos():
    """Pagos que cuentan para ingresos (los anulados no)."""
    return Pago.objects.filter(anulado=False)


def resumen_por_metodo(pagos):
    """Totales por método de pago: lista de dicts con etiqueta, cantidad y total."""
    etiquetas = dict(Pago.MetodoPago.choices)
    filas = pagos.values('metodo_pago').annotate(total=Sum('monto_pagado'), n=Count('id')).order_by('-total')
    return [
        {'metodo': etiquetas.get(f['metodo_pago'], f['metodo_pago']), 'total': f['total'] or 0, 'n': f['n']}
        for f in filas
    ]


def cobranza():
    """Quién vence esta semana y quién está atrasado (solo cuentas activas)."""
    hoy = timezone.localdate()
    limite = hoy + timedelta(days=settings.DIAS_AVISO_VENCIMIENTO)
    base = socios_con_estado().filter(usuario__is_active=True, ultimo_venc__isnull=False)
    por_vencer = base.filter(ultimo_venc__gte=hoy, ultimo_venc__lte=limite).order_by('ultimo_venc')
    atrasados = base.filter(ultimo_venc__lt=hoy).order_by('ultimo_venc')
    sin_pagos = Socio.objects.select_related('usuario').filter(usuario__is_active=True, pagos__isnull=True)
    return por_vencer, atrasados, sin_pagos
