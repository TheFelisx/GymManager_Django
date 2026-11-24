"""Reglas del módulo de clases y salas.

Todas las reglas del plan de trabajo viven aquí (no en las vistas) para que
recepción, socios, instructores, visitantes y el tótem usen exactamente las mismas.
"""
import datetime
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from panel.models import Pago, Socio
from .models import (
    BloqueoFecha, Clase, Inscripcion, ReservaSala, Sala, Sesion, SolicitudCambio, Tarifa,
    Visitante, combinar,
)

# --- Reglas (valores propuestos en el plan de trabajo) ---
ANTELACION_DIAS = 7            # se puede reservar hasta 7 días antes
CANCELAR_HORAS = 2             # se cancela hasta 2 horas antes
MAX_RESERVAS_ACTIVAS = 3       # reservas activas por socio
FALTAS_MAX = 3                 # 3 faltas ...
FALTAS_VENTANA_DIAS = 30       # ... en 30 días ...
BLOQUEO_DIAS = 7               # ... bloquean 7 días
TOLERANCIA_MINUTOS = 10        # se puede inscribir hasta 10 min después del inicio
LIMPIEZA_MINUTOS = 15          # entre usos de una sala
HORAS_LIBERAR = 24             # sin confirmar / sin pagar se libera
ARRIENDO_MIN_HORAS = 1
ARRIENDO_MAX_HORAS = 4
ARRIENDO_ANTELACION_HORAS = 48
ARRIENDO_CANCELAR_HORAS = 48
EDAD_MINIMA_VISITANTE = 14
EDAD_ARRENDATARIO = 18
VENTANA_ACCESO_MINUTOS = 15    # el acceso se habilita 15 min antes de la clase
VENTANA_LISTA_INSTRUCTOR_HORAS = 24

ACTIVAS = (Inscripcion.Estado.CONFIRMADA, Inscripcion.Estado.EN_ESPERA)
OCUPAN = (Inscripcion.Estado.CONFIRMADA, Inscripcion.Estado.ASISTIO, Inscripcion.Estado.NO_ASISTIO)


class ReglaError(Exception):
    """Un error de negocio con un mensaje que se puede mostrar a la persona."""


def _ahora():
    return timezone.localtime()


# =====================================================================
# Avisos por correo (si falla, no rompe la operación)
# =====================================================================
def notificar(email, asunto, mensaje):
    if not email:
        return
    try:
        send_mail(asunto, mensaje, None, [email])
    except Exception:
        pass


# =====================================================================
# Bloqueos y sesiones
# =====================================================================
def bloqueo_para(sala, fecha):
    return BloqueoFecha.objects.filter(fecha_desde__lte=fecha, fecha_hasta__gte=fecha).filter(
        Q(sala__isnull=True) | Q(sala=sala)
    ).first()


def generar_sesiones(dias=28, clases=None):
    """Crea las sesiones de las próximas semanas (no duplica las que ya existen)."""
    hoy = timezone.localdate()
    clases = clases if clases is not None else Clase.objects.filter(activa=True, sala__activa=True).select_related('sala')
    creadas = 0
    for clase in clases:
        existentes = set(clase.sesiones.filter(fecha__gte=hoy).values_list('fecha', flat=True))
        dias_clase = clase.lista_dias
        for delta in range(dias):
            fecha = hoy + timedelta(days=delta)
            if fecha.weekday() not in dias_clase or fecha in existentes:
                continue
            if bloqueo_para(clase.sala, fecha):
                continue   # feriado o cierre: no se crea la sesión
            if conflicto_reserva(clase.sala, fecha, clase.hora_inicio, clase.hora_fin):
                continue   # la sala ya está reservada ese día a esa hora
            Sesion.objects.create(clase=clase, fecha=fecha, hora_inicio=clase.hora_inicio, hora_fin=clase.hora_fin)
            creadas += 1
    return creadas


def resincronizar_clase(clase):
    """Tras editar una clase: rehace las sesiones futuras que aún no tienen inscritos."""
    hoy = timezone.localdate()
    # Las sesiones con inscritos se conservan tal cual (se editan una a una).
    sin_inscritos = list(
        clase.sesiones.filter(fecha__gte=hoy).annotate(n=Count('inscripciones')).filter(n=0).values_list('pk', flat=True)
    )
    Sesion.objects.filter(pk__in=sin_inscritos).delete()
    if clase.activa and clase.sala.activa:
        generar_sesiones(clases=[clase])


def asegurar_sesiones():
    """Mantenimiento liviano: como máximo una vez cada 6 horas por proceso."""
    if cache.add('reservas-mantenimiento', 1, 6 * 3600):
        generar_sesiones()
        revisar_vencimientos()
        liberar_pendientes()
        cerrar_vencidas()


# =====================================================================
# Cupos
# =====================================================================
def _bloquear_sesion(sesion):
    return Sesion.objects.select_for_update().select_related('clase__sala').get(pk=sesion.pk)


def plan_para_fecha(socio, fecha):
    pago = Pago.objects.filter(
        socio=socio, anulado=False, fecha_inicio__lte=fecha, fecha_vencimiento__gte=fecha
    ).select_related('plan').order_by('-fecha_vencimiento').first()
    return pago.plan if pago else None


def clases_en_la_semana(socio, fecha):
    lunes = fecha - timedelta(days=fecha.weekday())
    return Inscripcion.objects.filter(
        socio=socio, sesion__estado=Sesion.Estado.NORMAL,
        sesion__fecha__gte=lunes, sesion__fecha__lte=lunes + timedelta(days=6),
        estado__in=OCUPAN,
    ).count()


def bloqueo_por_faltas(inscripciones):
    """Si hay 3 faltas en 30 días, devuelve hasta qué fecha está bloqueado (o None)."""
    hoy = timezone.localdate()
    faltas = list(
        inscripciones.filter(
            estado=Inscripcion.Estado.NO_ASISTIO,
            sesion__fecha__gte=hoy - timedelta(days=FALTAS_VENTANA_DIAS),
        ).order_by('-sesion__fecha').values_list('sesion__fecha', flat=True)
    )
    if len(faltas) >= FALTAS_MAX:
        hasta = faltas[0] + timedelta(days=BLOQUEO_DIAS)
        if hasta >= hoy:
            return hasta
    return None


def faltas_de_socio(socio):
    return bloqueo_por_faltas(Inscripcion.objects.filter(socio=socio))


def faltas_de_visitante(visitante):
    return bloqueo_por_faltas(Inscripcion.objects.filter(
        Q(visitante__rut=visitante.rut) | Q(visitante__email__iexact=visitante.email)
    ))


def hay_choque(sesion, socio=None, visitante=None, excluir_id=None):
    """¿Ya tiene otra clase a la misma hora?"""
    filtro = Inscripcion.objects.filter(
        sesion__fecha=sesion.fecha, sesion__estado=Sesion.Estado.NORMAL,
        sesion__hora_inicio__lt=sesion.hora_fin, sesion__hora_fin__gt=sesion.hora_inicio,
        estado__in=ACTIVAS + (Inscripcion.Estado.ASISTIO,),
    ).exclude(sesion=sesion)
    if excluir_id:
        filtro = filtro.exclude(pk=excluir_id)
    if socio:
        filtro = filtro.filter(socio=socio)
    elif visitante:
        filtro = filtro.filter(visitante=visitante)
    return filtro.exists()


def _validar_sesion_abierta(sesion, desde_recepcion=False):
    ahora = _ahora()
    if sesion.cancelada:
        raise ReglaError("Esta clase fue cancelada.")
    if sesion.cerrada:
        raise ReglaError("Esta clase ya terminó.")
    tolerancia = timedelta(minutes=TOLERANCIA_MINUTOS) if desde_recepcion else timedelta(0)
    if ahora > sesion.inicio_dt + tolerancia:
        raise ReglaError("La clase ya comenzó." if not desde_recepcion
                         else f"Solo se puede inscribir hasta {TOLERANCIA_MINUTOS} minutos después del inicio.")
    if sesion.fecha > timezone.localdate() + timedelta(days=ANTELACION_DIAS):
        raise ReglaError(f"Solo se puede reservar hasta {ANTELACION_DIAS} días antes.")


def _validar_socio(socio, sesion, excluir_id=None):
    if not socio.usuario.is_active:
        raise ReglaError("El socio está dado de baja.")
    plan = plan_para_fecha(socio, sesion.fecha)
    if plan is None:
        raise ReglaError("La membresía no cubre la fecha de la clase. Renueva primero el plan.")
    if plan.clases_por_semana is not None:
        if plan.clases_por_semana == 0:
            raise ReglaError("Tu plan no incluye clases.")
        if clases_en_la_semana(socio, sesion.fecha) >= plan.clases_por_semana:
            raise ReglaError(f"Tu plan incluye {plan.clases_por_semana} clase(s) por semana y ya las usaste.")
    hasta = faltas_de_socio(socio)
    if hasta:
        raise ReglaError(f"Tienes {FALTAS_MAX} faltas en {FALTAS_VENTANA_DIAS} días: reservas bloqueadas hasta el {hasta:%d/%m/%Y}.")
    if hay_choque(sesion, socio=socio, excluir_id=excluir_id):
        raise ReglaError("Ya tienes otra clase a esa misma hora.")


# =====================================================================
# Inscripción de socios
# =====================================================================
@transaction.atomic
def inscribir_socio(socio, sesion, por=None, desde_recepcion=False):
    """Inscribe a un socio. Si no queda cupo, lo deja en lista de espera."""
    sesion = _bloquear_sesion(sesion)          # evita que dos personas tomen el último cupo
    _validar_sesion_abierta(sesion, desde_recepcion)
    existente = Inscripcion.objects.filter(sesion=sesion, socio=socio).first()
    if existente and existente.estado in ACTIVAS + (Inscripcion.Estado.ASISTIO,):
        raise ReglaError("Ya estás inscrito en esta clase." if existente.estado != Inscripcion.Estado.EN_ESPERA
                         else "Ya estás en la lista de espera de esta clase.")
    _validar_socio(socio, sesion, excluir_id=existente.pk if existente else None)

    hoy = timezone.localdate()
    activas = Inscripcion.objects.filter(socio=socio, estado__in=ACTIVAS, sesion__fecha__gte=hoy,
                                         sesion__estado=Sesion.Estado.NORMAL).count()
    if activas >= MAX_RESERVAS_ACTIVAS:
        raise ReglaError(f"Máximo {MAX_RESERVAS_ACTIVAS} reservas activas a la vez.")

    hay_cupo = sesion.libres_socio > 0
    estado = Inscripcion.Estado.CONFIRMADA if hay_cupo else Inscripcion.Estado.EN_ESPERA
    espera_desde = None if hay_cupo else timezone.now()
    if existente:
        existente.estado = estado
        existente.en_espera_desde = espera_desde
        existente.creada_por = por
        existente.marcada_por = None
        existente.marcada_en = None
        existente.save()
        return existente
    return Inscripcion.objects.create(sesion=sesion, socio=socio, estado=estado,
                                      en_espera_desde=espera_desde, creada_por=por)


def promover_espera(sesion):
    """Si se liberó un cupo, pasa al primero de la lista de espera y le avisa."""
    sesion = Sesion.objects.select_related('clase__sala').get(pk=sesion.pk)
    if sesion.cancelada or sesion.cerrada or _ahora() > sesion.inicio_dt:
        return []
    promovidos = []
    espera = Inscripcion.objects.filter(sesion=sesion, estado=Inscripcion.Estado.EN_ESPERA,
                                        socio__isnull=False).select_related('socio__usuario').order_by('en_espera_desde', 'id')
    for insc in espera:
        sesion.invalidar_cache()
        if sesion.libres_socio <= 0:
            break
        try:
            _validar_socio(insc.socio, sesion, excluir_id=insc.pk)
        except ReglaError:
            insc.estado = Inscripcion.Estado.CANCELADA
            insc.save(update_fields=['estado'])
            continue
        insc.estado = Inscripcion.Estado.CONFIRMADA
        insc.en_espera_desde = None
        insc.save(update_fields=['estado', 'en_espera_desde'])
        notificar(insc.socio.usuario.email, f"Tienes cupo en {sesion.clase.nombre}",
                  f"Hola {insc.socio.usuario.first_name}, se liberó un cupo y quedaste confirmado en "
                  f"{sesion.clase.nombre} el {sesion.fecha:%d/%m/%Y} a las {sesion.hora_inicio:%H:%M}.")
        promovidos.append(insc)
    return promovidos


@transaction.atomic
def cancelar_inscripcion(inscripcion, desde_recepcion=False):
    """Cancela una inscripción. El socio puede hasta 2 horas antes; recepción hasta el fin de la clase."""
    sesion = _bloquear_sesion(inscripcion.sesion)
    inscripcion = Inscripcion.objects.select_for_update().get(pk=inscripcion.pk)
    if inscripcion.estado not in ACTIVAS:
        raise ReglaError("Esta inscripción ya no está activa.")
    ahora = _ahora()
    if desde_recepcion:
        if ahora > sesion.fin_dt:
            raise ReglaError("La clase ya terminó.")
    elif inscripcion.estado == Inscripcion.Estado.CONFIRMADA and ahora > sesion.inicio_dt - timedelta(hours=CANCELAR_HORAS):
        raise ReglaError(f"Solo se puede cancelar hasta {CANCELAR_HORAS} horas antes de la clase.")
    elif ahora > sesion.inicio_dt:
        raise ReglaError("La clase ya comenzó.")
    libera_cupo = inscripcion.estado == Inscripcion.Estado.CONFIRMADA
    inscripcion.estado = Inscripcion.Estado.CANCELADA
    inscripcion.save(update_fields=['estado'])
    if libera_cupo:
        promover_espera(sesion)
    return inscripcion


def revisar_vencimientos():
    """Si la membresía vence antes de la clase reservada, cancela la reserva y avisa."""
    hoy = timezone.localdate()
    pendientes = Inscripcion.objects.filter(
        socio__isnull=False, estado__in=ACTIVAS, sesion__fecha__gte=hoy, sesion__estado=Sesion.Estado.NORMAL,
    ).select_related('socio__usuario', 'sesion__clase')
    cancelados = 0
    for insc in pendientes:
        if plan_para_fecha(insc.socio, insc.sesion.fecha) is None:
            insc.estado = Inscripcion.Estado.CANCELADA
            insc.save(update_fields=['estado'])
            notificar(insc.socio.usuario.email, "Tu reserva fue cancelada",
                      f"Tu membresía no cubre el {insc.sesion.fecha:%d/%m/%Y}, por eso se canceló tu reserva en "
                      f"{insc.sesion.clase.nombre}. Renueva tu plan para volver a reservar.")
            promover_espera(insc.sesion)
            cancelados += 1
    return cancelados


# =====================================================================
# Asistencia, cierre y cambios de sesión
# =====================================================================
@transaction.atomic
def marcar_asistencia(inscripcion, usuario, asistio=True):
    if inscripcion.estado not in (Inscripcion.Estado.CONFIRMADA, Inscripcion.Estado.ASISTIO, Inscripcion.Estado.NO_ASISTIO):
        raise ReglaError("Solo se marca la asistencia de inscripciones confirmadas.")
    if inscripcion.sesion.cancelada:
        raise ReglaError("La clase fue cancelada.")
    if _ahora() < inscripcion.sesion.inicio_dt - timedelta(minutes=VENTANA_ACCESO_MINUTOS * 2):
        raise ReglaError("Aún es muy pronto: la asistencia se marca desde 30 minutos antes de la clase.")
    inscripcion.estado = Inscripcion.Estado.ASISTIO if asistio else Inscripcion.Estado.NO_ASISTIO
    inscripcion.marcada_por = usuario
    inscripcion.marcada_en = timezone.now()
    inscripcion.save(update_fields=['estado', 'marcada_por', 'marcada_en'])
    return inscripcion


@transaction.atomic
def cerrar_sesion(sesion, usuario):
    """Quien no fue marcado pasa a «no asistió» (y cuenta para la regla de faltas)."""
    sesion = _bloquear_sesion(sesion)
    if sesion.cancelada:
        raise ReglaError("La clase fue cancelada.")
    if sesion.cerrada:
        raise ReglaError("La clase ya estaba cerrada.")
    if _ahora() < sesion.inicio_dt:
        raise ReglaError("La clase aún no comienza: no se puede cerrar todavía.")
    ahora = timezone.now()
    for insc in sesion.inscripciones.filter(estado=Inscripcion.Estado.CONFIRMADA):
        insc.estado = Inscripcion.Estado.NO_ASISTIO
        insc.marcada_por = usuario
        insc.marcada_en = ahora
        insc.save(update_fields=['estado', 'marcada_por', 'marcada_en'])
    sesion.inscripciones.filter(estado=Inscripcion.Estado.EN_ESPERA).update(estado=Inscripcion.Estado.CANCELADA)
    sesion.cerrada = True
    sesion.save(update_fields=['cerrada'])
    return sesion


def cerrar_vencidas():
    """Cierra solas las clases que terminaron hace más de 24 horas y nadie cerró.

    Así quienes no fueron marcados quedan como «no asistió» y cuentan para la regla de faltas.
    """
    limite = timezone.localdate() - timedelta(days=1)
    cerradas = 0
    for sesion in Sesion.objects.filter(cerrada=False, estado=Sesion.Estado.NORMAL, fecha__lte=limite):
        with transaction.atomic():
            sesion.inscripciones.filter(estado=Inscripcion.Estado.CONFIRMADA).update(
                estado=Inscripcion.Estado.NO_ASISTIO, marcada_en=timezone.now())
            sesion.inscripciones.filter(estado=Inscripcion.Estado.EN_ESPERA).update(estado=Inscripcion.Estado.CANCELADA)
            sesion.cerrada = True
            sesion.save(update_fields=['cerrada'])
        cerradas += 1
    return cerradas


def instructor_puede_ver(usuario, sesion):
    """El instructor ve la lista desde 24 horas antes hasta 24 horas después de la clase."""
    if sesion.instructor_efectivo is None or sesion.instructor_efectivo.pk != usuario.pk:
        return False
    ahora = _ahora()
    margen = timedelta(hours=VENTANA_LISTA_INSTRUCTOR_HORAS)
    return sesion.inicio_dt - margen <= ahora <= sesion.fin_dt + margen


@transaction.atomic
def cancelar_sesion(sesion, motivo):
    """Cancela una sola sesión (sin tocar las demás) y avisa a los inscritos."""
    sesion = _bloquear_sesion(sesion)
    if sesion.cancelada:
        raise ReglaError("La sesión ya estaba cancelada.")
    if sesion.cerrada or _ahora() > sesion.fin_dt:
        raise ReglaError("La clase ya terminó: no se puede cancelar.")
    sesion.estado = Sesion.Estado.CANCELADA
    sesion.motivo_cancelacion = motivo.strip()[:200]
    sesion.save(update_fields=['estado', 'motivo_cancelacion'])
    for insc in sesion.inscripciones.filter(estado__in=ACTIVAS).select_related('socio__usuario', 'visitante'):
        insc.estado = Inscripcion.Estado.CANCELADA
        insc.save(update_fields=['estado'])
        email = insc.socio.usuario.email if insc.socio_id else insc.visitante.email
        notificar(email, f"Se canceló {sesion.clase.nombre}",
                  f"La clase {sesion.clase.nombre} del {sesion.fecha:%d/%m/%Y} a las {sesion.hora_inicio:%H:%M} "
                  f"fue cancelada. Motivo: {sesion.motivo_cancelacion or 'sin detalle'}.")
    return sesion


def pedir_cambio(sesion, usuario, tipo, motivo):
    if sesion.cancelada or sesion.cerrada or _ahora() > sesion.fin_dt:
        raise ReglaError("Esta sesión ya no admite cambios.")
    if SolicitudCambio.objects.filter(sesion=sesion, solicitante=usuario, estado=SolicitudCambio.Estado.PENDIENTE).exists():
        raise ReglaError("Ya tienes una solicitud pendiente para esta sesión.")
    return SolicitudCambio.objects.create(sesion=sesion, solicitante=usuario, tipo=tipo, motivo=motivo.strip()[:200])


@transaction.atomic
def resolver_cambio(solicitud, admin, aprobar, suplente=None, nota=""):
    if solicitud.estado != SolicitudCambio.Estado.PENDIENTE:
        raise ReglaError("La solicitud ya fue resuelta.")
    solicitud.resuelta_por = admin
    solicitud.nota = nota.strip()[:200]
    if not aprobar:
        solicitud.estado = SolicitudCambio.Estado.RECHAZADA
    else:
        solicitud.estado = SolicitudCambio.Estado.APROBADA
        if solicitud.tipo == SolicitudCambio.Tipo.CANCELAR:
            cancelar_sesion(solicitud.sesion, solicitud.motivo or "Solicitud del instructor")
        else:
            if suplente is None:
                raise ReglaError("Elige el instructor suplente.")
            solicitud.sesion.instructor = suplente
            solicitud.sesion.save(update_fields=['instructor'])
    solicitud.save()
    return solicitud


# =====================================================================
# Visitantes: clases sueltas
# =====================================================================
def usa_prueba_gratis(visitante):
    tarifa = Tarifa.obtener()
    if not tarifa.prueba_gratis:
        return False
    if visitante.pk is None:
        return True
    return not Inscripcion.objects.filter(
        visitante__rut=visitante.rut, es_prueba=True, estado__in=OCUPAN
    ).exists()


@transaction.atomic
def inscribir_visitante(visitante, sesion, por=None, desde_recepcion=False):
    """Reserva una clase suelta (o de prueba gratis) para un visitante."""
    sesion = _bloquear_sesion(sesion)
    _validar_sesion_abierta(sesion, desde_recepcion)
    if visitante.edad < EDAD_MINIMA_VISITANTE:
        raise ReglaError(f"Los visitantes deben tener al menos {EDAD_MINIMA_VISITANTE} años.")
    if visitante.edad < 18 and not (visitante.apoderado_nombre and visitante.apoderado_rut):
        raise ReglaError("Los menores de 18 años necesitan los datos de su apoderado.")
    hasta = faltas_de_visitante(visitante)
    if hasta:
        raise ReglaError(f"Reservas bloqueadas por inasistencias hasta el {hasta:%d/%m/%Y}.")
    if Inscripcion.objects.filter(sesion=sesion, visitante=visitante, estado__in=ACTIVAS + (Inscripcion.Estado.ASISTIO,)).exists():
        raise ReglaError("Ya tienes una reserva en esta clase.")
    activas = Inscripcion.objects.filter(visitante=visitante, estado=Inscripcion.Estado.CONFIRMADA,
                                         sesion__fecha__gte=timezone.localdate(), sesion__estado=Sesion.Estado.NORMAL).count()
    if activas >= MAX_RESERVAS_ACTIVAS:
        raise ReglaError(f"Máximo {MAX_RESERVAS_ACTIVAS} reservas activas a la vez.")
    if hay_choque(sesion, visitante=visitante):
        raise ReglaError("Ya tienes otra clase a esa misma hora.")
    if sesion.libres_externo <= 0:
        raise ReglaError("La clase está llena.")

    tarifa = Tarifa.obtener()
    es_prueba = usa_prueba_gratis(visitante)
    monto = 0 if es_prueba else tarifa.precio_clase_suelta
    return Inscripcion.objects.create(
        sesion=sesion, visitante=visitante, estado=Inscripcion.Estado.CONFIRMADA,
        es_prueba=es_prueba, monto=monto, creada_por=por,
    )


@transaction.atomic
def cancelar_inscripcion_visitante(inscripcion, desde_recepcion=False):
    inscripcion = Inscripcion.objects.select_for_update().get(pk=inscripcion.pk)
    if inscripcion.estado not in ACTIVAS:
        raise ReglaError("Esta reserva ya no está activa.")
    sesion = inscripcion.sesion
    if not desde_recepcion and _ahora() > sesion.inicio_dt - timedelta(hours=CANCELAR_HORAS):
        raise ReglaError(f"Solo se puede cancelar hasta {CANCELAR_HORAS} horas antes de la clase.")
    if _ahora() > sesion.fin_dt:
        raise ReglaError("La clase ya terminó.")
    inscripcion.estado = Inscripcion.Estado.CANCELADA
    inscripcion.save(update_fields=['estado'])
    promover_espera(sesion)
    return inscripcion


def _validar_metodo(metodo):
    if metodo not in dict(Pago.MetodoPago.choices):
        raise ReglaError("Elige un método de pago válido.")


def registrar_pago_inscripcion(inscripcion, metodo, usuario):
    """Cobra el PRECIO COMPLETO de la clase. El monto no se elige: es el valor de la clase suelta."""
    _validar_metodo(metodo)
    if inscripcion.es_prueba or inscripcion.monto == 0:
        raise ReglaError("Es una clase de prueba gratis: no se le puede cobrar.")
    if inscripcion.pagada:
        raise ReglaError("Esta reserva ya está pagada.")
    if inscripcion.estado != Inscripcion.Estado.CONFIRMADA:
        raise ReglaError("Solo se cobran reservas confirmadas.")
    inscripcion.monto_pagado = inscripcion.monto
    inscripcion.metodo_pago = metodo
    inscripcion.fecha_pago = timezone.now()
    inscripcion.cobrado_por = usuario
    inscripcion.save(update_fields=['monto_pagado', 'metodo_pago', 'fecha_pago', 'cobrado_por'])
    return inscripcion


# =====================================================================
# Reserva de salas
# =====================================================================
def _solapa(a_ini, a_fin, b_ini, b_fin, margen=LIMPIEZA_MINUTOS):
    m = timedelta(minutes=margen)
    return a_ini < b_fin + m and b_ini < a_fin + m


def conflicto_reserva(sala, fecha, ini, fin, excluir_id=None):
    """Mensaje si otra reserva activa usa la sala a esa hora (con 15 min de limpieza)."""
    a_ini, a_fin = combinar(fecha, ini), combinar(fecha, fin)
    otras = ReservaSala.objects.filter(sala=sala, fecha=fecha, estado__in=(ReservaSala.Estado.SOLICITADA, ReservaSala.Estado.APROBADA))
    if excluir_id:
        otras = otras.exclude(pk=excluir_id)
    for r in otras:
        if _solapa(a_ini, a_fin, r.inicio_dt, r.fin_dt):
            return f"La sala ya está reservada de {r.hora_inicio:%H:%M} a {r.hora_fin:%H:%M}."
    return None


def conflicto_clases(sala, fecha, ini, fin, excluir_clase_id=None):
    """Mensaje si una clase (ya creada o aún sin sesión generada) usa la sala a esa hora."""
    a_ini, a_fin = combinar(fecha, ini), combinar(fecha, fin)
    for sesion in Sesion.objects.filter(clase__sala=sala, fecha=fecha, estado=Sesion.Estado.NORMAL).select_related('clase'):
        if _solapa(a_ini, a_fin, sesion.inicio_dt, sesion.fin_dt):
            return f"Choca con la clase {sesion.clase.nombre} ({sesion.hora_inicio:%H:%M}–{sesion.hora_fin:%H:%M})."
    # Clases activas cuya sesión de ese día aún no existe (por ejemplo, más allá de las 4 semanas generadas)
    for clase in Clase.objects.filter(sala=sala, activa=True):
        if clase.pk == excluir_clase_id or fecha.weekday() not in clase.lista_dias:
            continue
        if clase.sesiones.filter(fecha=fecha).exists():
            continue
        if _solapa(a_ini, a_fin, combinar(fecha, clase.hora_inicio), combinar(fecha, clase.hora_fin)):
            return f"Choca con la clase {clase.nombre} ({clase.hora_inicio:%H:%M}–{clase.hora_fin:%H:%M})."
    return None


def validar_franja_sala(sala, fecha, ini, fin, excluir_id=None):
    """La sala no puede tener dos usos a la vez (con 15 min de limpieza entre usos)."""
    if not sala.activa:
        raise ReglaError("La sala no está disponible.")
    if ini >= fin:
        raise ReglaError("La hora de término debe ser posterior a la de inicio.")
    bloqueo = bloqueo_para(sala, fecha)
    if bloqueo:
        raise ReglaError(f"La sala está bloqueada ese día: {bloqueo.motivo}.")
    mensaje = conflicto_clases(sala, fecha, ini, fin) or conflicto_reserva(sala, fecha, ini, fin, excluir_id)
    if mensaje:
        raise ReglaError(mensaje)


def calcular_precio_sala(sala, fecha, ini, fin):
    """Cobra por tramos de 30 minutos, con valor distinto en hora punta."""
    tarifa = Tarifa.obtener()
    punta = sala.precio_hora_punta if sala.precio_hora_punta is not None else sala.precio_hora
    actual = datetime.datetime.combine(fecha, ini)
    limite = datetime.datetime.combine(fecha, fin)
    total = 0.0
    while actual < limite:
        tramo_fin = min(actual + timedelta(minutes=30), limite)
        fraccion = (tramo_fin - actual).total_seconds() / 3600
        en_punta = tarifa.punta_inicio <= actual.time() < tarifa.punta_fin
        total += (punta if en_punta else sala.precio_hora) * fraccion
        actual = tramo_fin
    return int(round(total))


@transaction.atomic
def crear_reserva_sala(sala, fecha, ini, fin, motivo, personas=1, creada_por=None, visitante=None):
    """Staff: queda aprobada. Visitante: queda solicitada y la aprueba el personal."""
    sala = Sala.objects.select_for_update().get(pk=sala.pk)
    ahora = _ahora()
    if personas > sala.capacidad:
        raise ReglaError(f"La sala admite como máximo {sala.capacidad} personas.")
    if combinar(fecha, ini) < ahora:
        raise ReglaError("No se puede reservar en el pasado.")

    if visitante is not None:
        horas = (datetime.datetime.combine(fecha, fin) - datetime.datetime.combine(fecha, ini)).total_seconds() / 3600
        if not (ARRIENDO_MIN_HORAS <= horas <= ARRIENDO_MAX_HORAS):
            raise ReglaError(f"El arriendo debe durar entre {ARRIENDO_MIN_HORAS} y {ARRIENDO_MAX_HORAS} horas.")
        if combinar(fecha, ini) < ahora + timedelta(hours=ARRIENDO_ANTELACION_HORAS):
            raise ReglaError(f"El arriendo se solicita con al menos {ARRIENDO_ANTELACION_HORAS} horas de anticipación.")
        if visitante.edad < EDAD_ARRENDATARIO:
            raise ReglaError(f"El responsable del arriendo debe ser mayor de {EDAD_ARRENDATARIO} años.")
        hasta = faltas_de_visitante(visitante)
        if hasta:
            raise ReglaError(f"Reservas bloqueadas por inasistencias hasta el {hasta:%d/%m/%Y}.")

    validar_franja_sala(sala, fecha, ini, fin)
    reserva = ReservaSala.objects.create(
        sala=sala, fecha=fecha, hora_inicio=ini, hora_fin=fin, motivo=motivo.strip()[:200], personas=personas,
        estado=ReservaSala.Estado.SOLICITADA if visitante else ReservaSala.Estado.APROBADA,
        origen=ReservaSala.Origen.VISITANTE if visitante else ReservaSala.Origen.INTERNA,
        visitante=visitante, creada_por=creada_por,
        precio=calcular_precio_sala(sala, fecha, ini, fin),
        aprobada_en=None if visitante else timezone.now(),
    )
    return reserva


@transaction.atomic
def aprobar_reserva(reserva, usuario):
    reserva = ReservaSala.objects.select_for_update().select_related('sala', 'visitante').get(pk=reserva.pk)
    if reserva.estado != ReservaSala.Estado.SOLICITADA:
        raise ReglaError("Solo se aprueban solicitudes pendientes.")
    validar_franja_sala(reserva.sala, reserva.fecha, reserva.hora_inicio, reserva.hora_fin, excluir_id=reserva.pk)
    reserva.estado = ReservaSala.Estado.APROBADA
    reserva.aprobada_en = timezone.now()
    reserva.resuelta_por = usuario
    reserva.save(update_fields=['estado', 'aprobada_en', 'resuelta_por'])
    if reserva.visitante:
        notificar(reserva.visitante.email, "Tu solicitud de sala fue aprobada",
                  f"Tu reserva de {reserva.sala.nombre} el {reserva.fecha:%d/%m/%Y} de {reserva.hora_inicio:%H:%M} a "
                  f"{reserva.hora_fin:%H:%M} fue aprobada. Precio: ${reserva.precio}. Debes pagarla antes de usar la sala "
                  f"(se libera si no se paga en {HORAS_LIBERAR} horas). Tu código de acceso: {reserva.codigo}")
    return reserva


@transaction.atomic
def rechazar_reserva(reserva, usuario, nota=""):
    reserva = ReservaSala.objects.select_related('visitante', 'sala').get(pk=reserva.pk)
    if reserva.estado != ReservaSala.Estado.SOLICITADA:
        raise ReglaError("Solo se rechazan solicitudes pendientes.")
    reserva.estado = ReservaSala.Estado.RECHAZADA
    reserva.resuelta_por = usuario
    reserva.nota = nota.strip()[:200]
    reserva.save(update_fields=['estado', 'resuelta_por', 'nota'])
    if reserva.visitante:
        notificar(reserva.visitante.email, "Tu solicitud de sala no pudo aprobarse",
                  f"No pudimos aprobar tu reserva de {reserva.sala.nombre} del {reserva.fecha:%d/%m/%Y}. {reserva.nota}")
    return reserva


@transaction.atomic
def cancelar_reserva_sala(reserva, desde_personal=False):
    reserva = ReservaSala.objects.select_for_update().get(pk=reserva.pk)
    if not reserva.activa:
        raise ReglaError("Esta reserva ya no está activa.")
    if not desde_personal and _ahora() > reserva.inicio_dt - timedelta(hours=ARRIENDO_CANCELAR_HORAS):
        raise ReglaError(f"Solo se puede cancelar sin costo hasta {ARRIENDO_CANCELAR_HORAS} horas antes.")
    reserva.estado = ReservaSala.Estado.CANCELADA
    reserva.save(update_fields=['estado'])
    return reserva


def registrar_pago_reserva(reserva, metodo, usuario):
    """Cobra el PRECIO COMPLETO del arriendo. El monto no se elige: lo calcula el sistema."""
    _validar_metodo(metodo)
    if reserva.estado != ReservaSala.Estado.APROBADA:
        raise ReglaError("Solo se cobran reservas aprobadas.")
    if reserva.precio == 0:
        raise ReglaError("Esta reserva no tiene costo: no se cobra.")
    if reserva.pagada:
        raise ReglaError("La reserva ya está pagada.")
    reserva.monto_pagado = reserva.precio
    reserva.metodo_pago = metodo
    reserva.fecha_pago = timezone.now()
    reserva.cobrado_por = usuario
    reserva.save(update_fields=['monto_pagado', 'metodo_pago', 'fecha_pago', 'cobrado_por'])
    return reserva


def liberar_pendientes():
    """Lo que no se confirma o no se paga en 24 horas se libera."""
    limite = timezone.now() - timedelta(hours=HORAS_LIBERAR)
    n = 0
    for r in ReservaSala.objects.filter(origen=ReservaSala.Origen.VISITANTE, estado=ReservaSala.Estado.SOLICITADA, creada__lt=limite):
        r.estado = ReservaSala.Estado.CANCELADA
        r.nota = "Liberada: sin confirmar en 24 horas."
        r.save(update_fields=['estado', 'nota'])
        n += 1
    for r in ReservaSala.objects.filter(origen=ReservaSala.Origen.VISITANTE, estado=ReservaSala.Estado.APROBADA,
                                        aprobada_en__lt=limite, monto_pagado=0, precio__gt=0):
        r.estado = ReservaSala.Estado.CANCELADA
        r.nota = "Liberada: sin pago en 24 horas."
        r.save(update_fields=['estado', 'nota'])
        n += 1
    for i in Inscripcion.objects.filter(visitante__isnull=False, estado=Inscripcion.Estado.CONFIRMADA,
                                        creada__lt=limite, monto__gt=0, monto_pagado=0,
                                        sesion__fecha__gte=timezone.localdate()).select_related('sesion'):
        i.estado = Inscripcion.Estado.CANCELADA
        i.save(update_fields=['estado'])
        n += 1
    return n


# =====================================================================
# Tótem: clase en curso y códigos de visitantes
# =====================================================================
def sesion_en_curso_de_socio(socio):
    """La clase confirmada del socio que está por empezar o en curso (15 min antes hasta el fin)."""
    ahora = _ahora()
    hoy = timezone.localdate()
    candidatas = Inscripcion.objects.filter(
        socio=socio, estado=Inscripcion.Estado.CONFIRMADA, sesion__fecha=hoy, sesion__estado=Sesion.Estado.NORMAL,
    ).select_related('sesion__clase__sala')
    for insc in candidatas:
        s = insc.sesion
        if s.inicio_dt - timedelta(minutes=VENTANA_ACCESO_MINUTOS) <= ahora <= s.fin_dt:
            return insc
    return None


def marcar_asistencia_automatica(inscripcion, guardia):
    inscripcion.estado = Inscripcion.Estado.ASISTIO
    inscripcion.marcada_por = guardia
    inscripcion.marcada_en = timezone.now()
    inscripcion.save(update_fields=['estado', 'marcada_por', 'marcada_en'])


def estado_codigo(obj):
    """Estado del código de un visitante: (clave, texto).

    claves: vigente, pendiente_pago, antes, vencido, cancelado
    El código solo sirve desde 15 minutos antes del inicio hasta el término de la clase o la reserva.
    """
    ahora = _ahora()
    margen = timedelta(minutes=VENTANA_ACCESO_MINUTOS)
    if isinstance(obj, Inscripcion):
        if obj.estado in (Inscripcion.Estado.CANCELADA, Inscripcion.Estado.EN_ESPERA) or obj.sesion.cancelada:
            return 'cancelado', "Reserva cancelada."
        inicio, fin = obj.sesion.inicio_dt, obj.sesion.fin_dt
    else:
        if obj.estado != ReservaSala.Estado.APROBADA:
            return 'cancelado', "La reserva no está aprobada (o fue cancelada)."
        inicio, fin = obj.inicio_dt, obj.fin_dt
    if ahora > fin:
        return 'vencido', f"Código vencido: terminó el {fin:%d/%m/%Y} a las {fin:%H:%M}."
    if not obj.pagada:
        pendiente = (obj.monto - obj.monto_pagado) if isinstance(obj, Inscripcion) else (obj.precio - obj.monto_pagado)
        return 'pendiente_pago', f"Pago pendiente (${pendiente}): se cobra en recepción antes de entrar."
    if ahora < inicio - margen:
        return 'antes', f"Aún no es la hora: se activa 15 minutos antes ({inicio:%d/%m/%Y %H:%M})."
    return 'vigente', f"Código activo hasta las {fin:%H:%M}."


def qr_data_uri(texto):
    """Imagen PNG del QR como data URI, lista para poner en un <img>."""
    import base64
    from io import BytesIO
    import qrcode
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(str(texto))
    qr.make(fit=True)
    buffer = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def evaluar_codigo_visita(texto, guardia):
    """Valida el código (QR) de un visitante. Devuelve None si el texto no es de un visitante.

    La clase o el arriendo habilitan el acceso solo durante su horario; al terminar, el código se desactiva.
    """
    import uuid
    try:
        codigo = uuid.UUID((texto or '').strip())
    except ValueError:
        return None

    insc = Inscripcion.objects.select_related('visitante', 'sesion__clase__sala').filter(codigo=codigo, visitante__isnull=False).first()
    if insc:
        v, s = insc.visitante, insc.sesion
        base = {'visitante': v, 'detalle': f"Clase {s.clase.nombre}"}
        clave, texto_estado = estado_codigo(insc)
        if clave != 'vigente':
            return {**base, 'permitido': False, 'motivo': texto_estado}
        if insc.estado == Inscripcion.Estado.NO_ASISTIO:
            return {**base, 'permitido': False, 'motivo': "La clase ya fue cerrada."}
        reingreso = insc.estado == Inscripcion.Estado.ASISTIO
        if insc.estado == Inscripcion.Estado.CONFIRMADA:
            marcar_asistencia_automatica(insc, guardia)
        extra = " · PRIMERA CLASE DE PRUEBA: no se cobra" if insc.es_prueba else ""
        return {**base, 'permitido': True,
                'motivo': f"Visitante · {s.clase.nombre} {s.hora_inicio:%H:%M}{' (reingreso)' if reingreso else ''}{extra}"}

    reserva = ReservaSala.objects.select_related('visitante', 'sala').filter(codigo=codigo, visitante__isnull=False).first()
    if reserva:
        v = reserva.visitante
        base = {'visitante': v, 'detalle': f"Sala {reserva.sala.nombre}"}
        clave, texto_estado = estado_codigo(reserva)
        if clave != 'vigente':
            return {**base, 'permitido': False, 'motivo': texto_estado}
        return {**base, 'permitido': True,
                'motivo': f"Visitante · sala {reserva.sala.nombre} {reserva.hora_inicio:%H:%M}–{reserva.hora_fin:%H:%M}"}
    return None


# =====================================================================
# Consultas para pantallas
# =====================================================================
def sesiones_con_cupos(desde, hasta, solo_activas=True):
    qs = Sesion.objects.select_related('clase__sala', 'clase__instructor', 'instructor').filter(
        fecha__gte=desde, fecha__lte=hasta,
    ).annotate(
        n_socios=Count('inscripciones', filter=Q(inscripciones__estado__in=OCUPAN, inscripciones__socio__isnull=False)),
        n_externos=Count('inscripciones', filter=Q(inscripciones__estado__in=OCUPAN, inscripciones__visitante__isnull=False)),
        n_espera=Count('inscripciones', filter=Q(inscripciones__estado=Inscripcion.Estado.EN_ESPERA)),
    ).order_by('fecha', 'hora_inicio')
    if solo_activas:
        qs = qs.filter(clase__activa=True)
    return qs


# =====================================================================
# Suspender o reactivar una clase
# =====================================================================
MOTIVO_SUSPENSION = "Clase suspendida"


def suspender_clase(clase):
    """Al desactivar una clase se cancelan sus sesiones futuras y se avisa a los inscritos."""
    hoy = timezone.localdate()
    n = 0
    for sesion in clase.sesiones.filter(fecha__gte=hoy, estado=Sesion.Estado.NORMAL, cerrada=False):
        try:
            cancelar_sesion(sesion, MOTIVO_SUSPENSION)
            n += 1
        except ReglaError:
            pass   # por ejemplo, una clase de hoy que ya terminó
    return n


def reactivar_clase(clase):
    """Al reactivarla vuelven las sesiones que se cancelaron por la suspensión."""
    hoy = timezone.localdate()
    clase.sesiones.filter(fecha__gte=hoy, estado=Sesion.Estado.CANCELADA, motivo_cancelacion=MOTIVO_SUSPENSION).update(
        estado=Sesion.Estado.NORMAL, motivo_cancelacion="")
    generar_sesiones(clases=[clase])
