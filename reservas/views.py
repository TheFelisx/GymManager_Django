import json
import random
import uuid
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from urllib.parse import quote
from django.utils import timezone
from django.views.decorators.http import require_POST

from cuentas.decorators import rol_requerido
from cuentas.models import Usuario
from cuentas.utils import registrar_auditoria
from cuentas.validators import limpiar_rut
from panel.forms import MotivoForm
from panel.paginacion import paginar
from panel.models import Socio
from . import services as srv
from .forms import (
    BloqueoForm, CambioForm, ClaseForm, ConsultaVisitanteForm, PagoVisitaForm, ReservaSalaForm, ReservaSalaStaffForm,
    ResolverCambioForm, SalaForm, SesionInstructorForm, SolicitarCodigoForm, TarifaForm,
    VerificarCodigoForm, VisitanteForm,
)
from .models import (
    BloqueoFecha, Clase, Inscripcion, ReservaSala, Sala, Sesion, SolicitudCambio, Tarifa, Visitante,
)
from .services import ReglaError

PERSONAL = ['MASTER', 'ADMIN', 'RECEPCIONISTA']
ADMINISTRACION = ['MASTER', 'ADMIN']


def _es_admin(user):
    return user.es_master or user.es_admin


def _fecha(valor, defecto):
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        return defecto


def _agrupar_por_dia(sesiones):
    """[(fecha, [sesiones])] en orden."""
    dias = {}
    for s in sesiones:
        dias.setdefault(s.fecha, []).append(s)
    return sorted(dias.items())


def _precios_json():
    """Precios por hora de las salas (y la hora punta) para calcular el total en pantalla antes de reservar."""
    tarifa = Tarifa.obtener()
    return json.dumps({
        'salas': {str(s.pk): {'nombre': s.nombre, 'normal': s.precio_hora,
                              'punta': s.precio_hora_punta if s.precio_hora_punta is not None else s.precio_hora}
                  for s in Sala.objects.filter(activa=True)},
        'punta': [tarifa.punta_inicio.strftime('%H:%M'), tarifa.punta_fin.strftime('%H:%M')],
    })


def _ip(request):
    return request.META.get('REMOTE_ADDR', 'x')


# =====================================================================
# PÚBLICO: horario y salas
# =====================================================================
def horario_publico(request):
    srv.asegurar_sesiones()
    hoy = timezone.localdate()
    sesiones = srv.sesiones_con_cupos(hoy, hoy + timedelta(days=6)).filter(estado=Sesion.Estado.NORMAL, clase__sala__activa=True)
    ahora = timezone.localtime()
    sesiones = [s for s in sesiones if s.fin_dt >= ahora]
    return render(request, 'reservas/horario_publico.html', {
        'dias': _agrupar_por_dia(sesiones),
        'salas': Sala.objects.filter(activa=True),
        'tarifa': Tarifa.obtener(),
    })


# =====================================================================
# VISITANTES (sin cuenta, con correo verificado)
# =====================================================================
def _email_verificado(request):
    return request.session.get('vis_email')


def _exigir_verificacion(request):
    if not _email_verificado(request):
        messages.info(request, "Primero verifica tu correo electrónico.")
        return redirect(f"{reverse('reservas:visitante_acceso')}?next={quote(request.get_full_path())}")
    return None


def visitante_acceso(request):
    """Paso 1: el visitante escribe su correo y recibe un código de 6 dígitos."""
    siguiente = request.GET.get('next') or request.POST.get('next') or ''
    form = SolicitarCodigoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        clave_ip = f"vis-codigos-{_ip(request)}"
        if cache.get(clave_ip, 0) >= 5:
            messages.error(request, "Pediste varios códigos seguidos. Espera unos minutos.")
        else:
            cache.add(clave_ip, 0, 600)
            try:
                cache.incr(clave_ip)
            except ValueError:
                cache.set(clave_ip, 1, 600)
            email = form.cleaned_data['email'].lower()
            codigo = f"{random.SystemRandom().randrange(0, 1000000):06d}"
            cache.set(f"vis-verif-{email}", codigo, 15 * 60)
            cache.delete(f"vis-intentos-{email}")
            srv.notificar(email, "Tu código de verificación",
                          f"Tu código para reservar en {settings.GYM_INFO['nombre']} es {codigo}. Vence en 15 minutos.")
            request.session['vis_pendiente'] = email
            messages.success(request, f"Te enviamos un código a {email}.")
            return redirect(f"{reverse('reservas:visitante_verificar')}?next={quote(siguiente)}")
    return render(request, 'reservas/visitante_acceso.html', {'form': form, 'next': siguiente})


def visitante_verificar(request):
    email = request.session.get('vis_pendiente')
    if not email:
        return redirect('reservas:visitante_acceso')
    siguiente = request.GET.get('next') or request.POST.get('next') or reverse('reservas:horario')
    form = VerificarCodigoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        clave_intentos = f"vis-intentos-{email}"
        if cache.get(clave_intentos, 0) >= 5:
            messages.error(request, "Demasiados intentos. Pide un código nuevo.")
        elif cache.get(f"vis-verif-{email}") == form.cleaned_data['codigo']:
            request.session['vis_email'] = email
            request.session.pop('vis_pendiente', None)
            cache.delete(f"vis-verif-{email}")
            messages.success(request, "Correo verificado. Ya puedes reservar.")
            return redirect(siguiente if siguiente.startswith('/') and not siguiente.startswith('//') else reverse('reservas:horario'))
        else:
            cache.add(clave_intentos, 0, 900)
            try:
                cache.incr(clave_intentos)
            except ValueError:
                cache.set(clave_intentos, 1, 900)
            messages.error(request, "Código incorrecto o vencido.")
    return render(request, 'reservas/visitante_verificar.html', {'form': form, 'email': email, 'next': siguiente})


def _datos_qr(obj):
    """QR del visitante: solo se muestra mientras el código está activo o por activarse."""
    clave, texto = srv.estado_codigo(obj)
    return {
        'estado_codigo': clave, 'estado_texto': texto,
        'qr': srv.qr_data_uri(obj.codigo) if clave in ('vigente', 'antes', 'pendiente_pago') else '',
    }


def _enviar_comprobante(visitante, asunto, texto):
    srv.notificar(visitante.email, asunto, texto)


def visitante_reservar_clase(request, pk):
    redireccion = _exigir_verificacion(request)
    if redireccion:
        return redireccion
    sesion = get_object_or_404(Sesion.objects.select_related('clase__sala'), pk=pk)
    verificado = _email_verificado(request)
    form = VisitanteForm(request.POST or None, initial={'email': verificado})
    if request.method == 'POST' and form.is_valid():
        if form.cleaned_data['email'].lower() != verificado:
            form.add_error('email', "Usa el mismo correo que verificaste.")
        else:
            try:
                visitante = form.guardar(email_verificado=True)
                insc = srv.inscribir_visitante(visitante, sesion)
            except ReglaError as e:
                messages.error(request, str(e))
            else:
                _enviar_comprobante(
                    visitante, f"Reserva en {sesion.clase.nombre}",
                    f"Tu reserva quedó confirmada: {sesion.clase.nombre}, {sesion.fecha:%d/%m/%Y} a las {sesion.hora_inicio:%H:%M}.\n"
                    f"{'Es tu clase de prueba gratis.' if insc.es_prueba else f'Debes pagar ${insc.monto} en recepción antes de la clase (se libera si no se paga en 24 horas).'}\n"
                    f"Tu código: {insc.codigo}")
                return render(request, 'reservas/visitante_exito.html', {
                    'tipo': 'clase', 'inscripcion': insc, 'visitante': visitante, 'codigo': insc.codigo,
                    **_datos_qr(insc),
                })
    return render(request, 'reservas/visitante_form.html', {
        'form': form, 'titulo': f"Reservar {sesion.clase.nombre}",
        'subtitulo': f"{sesion.fecha:%d/%m/%Y} · {sesion.hora_inicio:%H:%M}–{sesion.hora_fin:%H:%M} · {sesion.clase.sala.nombre}",
        'tarifa': Tarifa.obtener(), 'es_clase': True,
    })


def visitante_arrendar(request):
    redireccion = _exigir_verificacion(request)
    if redireccion:
        return redireccion
    verificado = _email_verificado(request)
    form_sala = ReservaSalaForm(request.POST or None, prefix='sala')
    form_vis = VisitanteForm(request.POST or None, prefix='vis', initial={'email': verificado})
    if request.method == 'POST' and form_sala.is_valid() and form_vis.is_valid():
        if form_vis.cleaned_data['email'].lower() != verificado:
            form_vis.add_error('email', "Usa el mismo correo que verificaste.")
        else:
            d = form_sala.cleaned_data
            try:
                visitante = form_vis.guardar(email_verificado=True)
                reserva = srv.crear_reserva_sala(d['sala'], d['fecha'], d['hora_inicio'], d['hora_fin'],
                                                 d['motivo'], d['personas'], visitante=visitante)
            except ReglaError as e:
                messages.error(request, str(e))
            else:
                _enviar_comprobante(
                    visitante, "Recibimos tu solicitud de sala",
                    f"Solicitaste {reserva.sala.nombre} el {reserva.fecha:%d/%m/%Y} de {reserva.hora_inicio:%H:%M} a "
                    f"{reserva.hora_fin:%H:%M}. Precio: ${reserva.precio}. El personal la revisará y te avisaremos. "
                    f"Tu código: {reserva.codigo}")
                return render(request, 'reservas/visitante_exito.html', {
                    'tipo': 'sala', 'reserva': reserva, 'visitante': visitante, 'codigo': reserva.codigo,
                    **_datos_qr(reserva),
                })
    return render(request, 'reservas/arriendo_form.html', {
        'form_sala': form_sala, 'form_vis': form_vis, 'salas': Sala.objects.filter(activa=True),
        'precios': _precios_json(), 'prefijo_campos': 'sala-',
    })


def visitante_consulta(request):
    form = ConsultaVisitanteForm(request.POST or None)
    insc = reserva = None
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        try:
            codigo = uuid.UUID(form.cleaned_data['codigo'].strip())
        except ValueError:
            codigo = None
        if codigo:
            insc = Inscripcion.objects.select_related('sesion__clase__sala', 'visitante').filter(
                codigo=codigo, visitante__email__iexact=email).first()
            if not insc:
                reserva = ReservaSala.objects.select_related('sala', 'visitante').filter(
                    codigo=codigo, visitante__email__iexact=email).first()
        if not (insc or reserva):
            messages.error(request, "No encontramos una reserva con esos datos.")
        elif request.POST.get('accion') == 'cancelar':
            try:
                if insc:
                    srv.cancelar_inscripcion_visitante(insc)
                else:
                    srv.cancelar_reserva_sala(reserva)
                messages.success(request, "Tu reserva fue cancelada.")
            except ReglaError as e:
                messages.error(request, str(e))
            if insc:
                insc.refresh_from_db()
            else:
                reserva.refresh_from_db()
    objeto = insc or reserva
    return render(request, 'reservas/visitante_consulta.html', {
        'form': form, 'inscripcion': insc, 'reserva': reserva, **(_datos_qr(objeto) if objeto else {}),
    })


# =====================================================================
# SOCIO
# =====================================================================
@rol_requerido(['SOCIO'])
def mis_clases(request):
    srv.asegurar_sesiones()
    socio = get_object_or_404(Socio, usuario=request.user)
    hoy = timezone.localdate()
    sesiones = srv.sesiones_con_cupos(hoy, hoy + timedelta(days=srv.ANTELACION_DIAS)).filter(
        estado=Sesion.Estado.NORMAL, clase__sala__activa=True)
    ahora = timezone.localtime()
    sesiones = [s for s in sesiones if s.inicio_dt > ahora]
    mias = {i.sesion_id: i for i in Inscripcion.objects.filter(
        socio=socio, estado__in=srv.ACTIVAS + (Inscripcion.Estado.ASISTIO,), sesion__fecha__gte=hoy)}
    for s in sesiones:
        s.mi_inscripcion = mias.get(s.pk)
        mi = s.mi_inscripcion
        s.puede_cancelar = bool(mi) and (mi.estado == Inscripcion.Estado.EN_ESPERA
                                         or ahora <= s.inicio_dt - timedelta(hours=srv.CANCELAR_HORAS))
    historial = Inscripcion.objects.filter(socio=socio).exclude(estado__in=srv.ACTIVAS).select_related(
        'sesion__clase').order_by('-sesion__fecha', '-sesion__hora_inicio')[:15]
    proximas = [i for i in Inscripcion.objects.filter(socio=socio, estado__in=srv.ACTIVAS, sesion__fecha__gte=hoy,
                                                      sesion__estado=Sesion.Estado.NORMAL).select_related('sesion__clase__sala')]
    return render(request, 'reservas/mis_clases.html', {
        'dias': _agrupar_por_dia(sesiones), 'proximas': proximas, 'historial': historial,
        'bloqueado_hasta': srv.faltas_de_socio(socio),
        'max_reservas': srv.MAX_RESERVAS_ACTIVAS,
    })


@require_POST
@rol_requerido(['SOCIO'])
def socio_inscribirse(request, pk):
    socio = get_object_or_404(Socio, usuario=request.user)
    sesion = get_object_or_404(Sesion, pk=pk)
    try:
        insc = srv.inscribir_socio(socio, sesion, por=request.user)
    except ReglaError as e:
        messages.error(request, str(e))
    else:
        if insc.estado == Inscripcion.Estado.EN_ESPERA:
            messages.warning(request, "La clase está llena: quedaste en la lista de espera. Te avisaremos si se libera un cupo.")
        else:
            messages.success(request, "¡Listo! Tu cupo quedó confirmado.")
    return redirect('reservas:mis_clases')


@require_POST
@rol_requerido(['SOCIO'])
def socio_cancelar(request, pk):
    insc = get_object_or_404(Inscripcion, pk=pk, socio__usuario=request.user)
    try:
        srv.cancelar_inscripcion(insc)
        messages.success(request, "Tu reserva fue cancelada.")
    except ReglaError as e:
        messages.error(request, str(e))
    return redirect('reservas:mis_clases')


# =====================================================================
# RECEPCIÓN / ADMINISTRACIÓN
# =====================================================================
@rol_requerido(PERSONAL)
def ocupacion(request):
    srv.asegurar_sesiones()
    dia = _fecha(request.GET.get('fecha'), timezone.localdate())
    sesiones = srv.sesiones_con_cupos(dia, dia, solo_activas=False)
    reservas = ReservaSala.objects.select_related('sala', 'visitante').filter(
        fecha=dia, estado__in=(ReservaSala.Estado.APROBADA, ReservaSala.Estado.SOLICITADA))
    return render(request, 'reservas/ocupacion.html', {
        'dia': dia, 'anterior': dia - timedelta(days=1), 'siguiente': dia + timedelta(days=1),
        'pag_sesiones': paginar(request, sesiones, 12, 'p_clases'),
        'pag_reservas': paginar(request, reservas.order_by('hora_inicio', 'id'), 8, 'p_salas'),
        'pendientes': ReservaSala.objects.filter(estado=ReservaSala.Estado.SOLICITADA).count(),
        'puede_admin': _es_admin(request.user),
    })


@rol_requerido(PERSONAL)
def sesion_detalle(request, pk):
    sesion = get_object_or_404(Sesion.objects.select_related('clase__sala', 'clase__instructor', 'instructor'), pk=pk)
    inscripciones = sesion.inscripciones.select_related('socio__usuario', 'visitante').order_by('estado', 'en_espera_desde', 'id')
    return render(request, 'reservas/sesion_detalle.html', {
        'sesion': sesion, 'pagina': paginar(request, inscripciones, 15), 'puede_admin': _es_admin(request.user),
        'form_pago': PagoVisitaForm(), 'form_suplente': SesionInstructorForm(initial={'instructor': sesion.instructor}),
        'form_cancelar': MotivoForm(),
    })


@require_POST
@rol_requerido(PERSONAL)
def staff_inscribir_socio(request, pk):
    sesion = get_object_or_404(Sesion, pk=pk)
    rut = limpiar_rut(request.POST.get('rut', ''))
    socio = Socio.objects.select_related('usuario').filter(rut=rut).first()
    if not socio:
        messages.error(request, "No existe un socio con ese RUT.")
    else:
        try:
            insc = srv.inscribir_socio(socio, sesion, por=request.user, desde_recepcion=True)
            registrar_auditoria(request.user, "INSCRIBIR_CLASE", f"{socio.rut_formateado} en {sesion} ({insc.get_estado_display()})")
            if insc.estado == Inscripcion.Estado.EN_ESPERA:
                messages.warning(request, f"{socio.usuario.get_full_name()} quedó en lista de espera (clase llena).")
            else:
                messages.success(request, f"{socio.usuario.get_full_name()} quedó inscrito.")
        except ReglaError as e:
            messages.error(request, str(e))
    return redirect('reservas:sesion_detalle', pk=pk)


@require_POST
@rol_requerido(PERSONAL)
def staff_cancelar_inscripcion(request, pk):
    insc = get_object_or_404(Inscripcion.objects.select_related('sesion'), pk=pk)
    try:
        if insc.visitante_id:
            srv.cancelar_inscripcion_visitante(insc, desde_recepcion=True)
        else:
            srv.cancelar_inscripcion(insc, desde_recepcion=True)
        registrar_auditoria(request.user, "CANCELAR_INSCRIPCION", f"{insc.persona_nombre} en {insc.sesion}")
        messages.success(request, "Inscripción cancelada.")
    except ReglaError as e:
        messages.error(request, str(e))
    return redirect('reservas:sesion_detalle', pk=insc.sesion_id)


@rol_requerido(PERSONAL)
def staff_inscribir_visitante(request, pk):
    """«Inscribir y cobrar»: quien llega sin reserva. Se confirma solo con el pago registrado."""
    sesion = get_object_or_404(Sesion.objects.select_related('clase__sala'), pk=pk)
    form = VisitanteForm(request.POST or None, staff=True)
    form_pago = PagoVisitaForm(request.POST or None, prefix='pago')
    tarifa = Tarifa.obtener()
    if request.method == 'POST' and form.is_valid():
        try:
            visitante = form.guardar(email_verificado=False)
            es_prueba = srv.usa_prueba_gratis(visitante)
            if not es_prueba and not form_pago.is_valid():
                raise ReglaError("Elige el método de pago: la inscripción se confirma con el cobro.")
            from django.db import transaction
            with transaction.atomic():
                insc = srv.inscribir_visitante(visitante, sesion, por=request.user, desde_recepcion=True)
                if insc.monto > 0:
                    srv.registrar_pago_inscripcion(insc, form_pago.cleaned_data['metodo'], request.user)
        except ReglaError as e:
            messages.error(request, str(e))
        else:
            registrar_auditoria(request.user, "INSCRIBIR_VISITANTE", f"{visitante.rut_formateado} en {sesion} (${insc.monto_pagado})")
            messages.success(request, "Visitante inscrito. " + (
                "Es su PRIMERA CLASE DE PRUEBA: no se le cobra." if insc.es_prueba else f"Se cobró ${insc.monto_pagado:,}".replace(",", ".") + "."))
            return redirect('reservas:qr_visita', tipo='clase', pk=insc.pk)
    return render(request, 'reservas/staff_visitante_form.html', {
        'sesion': sesion, 'form': form, 'form_pago': form_pago, 'tarifa': tarifa,
    })


@require_POST
@rol_requerido(PERSONAL)
def staff_cobrar_inscripcion(request, pk):
    insc = get_object_or_404(Inscripcion, pk=pk, visitante__isnull=False)
    form = PagoVisitaForm(request.POST)
    if form.is_valid():
        try:
            srv.registrar_pago_inscripcion(insc, form.cleaned_data['metodo'], request.user)
            registrar_auditoria(request.user, "COBRAR_VISITA", f"${insc.monto} a {insc.persona_nombre} ({insc.sesion})")
            messages.success(request, f"Pago registrado: ${insc.monto:,}".replace(",", "."))
        except ReglaError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Elige un método de pago.")
    return redirect('reservas:sesion_detalle', pk=insc.sesion_id)


@rol_requerido(PERSONAL)
def qr_visita(request, tipo, pk):
    """QR del visitante para que recepción se lo muestre o imprima. Se desactiva al terminar la clase o la reserva."""
    if tipo == 'clase':
        obj = get_object_or_404(Inscripcion.objects.select_related('sesion__clase__sala', 'visitante'), pk=pk, visitante__isnull=False)
    elif tipo == 'sala':
        obj = get_object_or_404(ReservaSala.objects.select_related('sala', 'visitante'), pk=pk, visitante__isnull=False)
    else:
        raise Http404
    return render(request, 'reservas/qr_visita.html', {'obj': obj, 'tipo': tipo, 'visitante': obj.visitante, **_datos_qr(obj)})


@rol_requerido(PERSONAL)
def visitante_estado(request):
    """Responde si el RUT ya usó su clase de prueba (para avisar a recepción que no se cobra)."""
    rut = limpiar_rut(request.GET.get('rut', ''))
    tarifa = Tarifa.obtener()
    if len(rut) < 8:
        return JsonResponse({'valido': False})
    existente = Visitante.objects.filter(rut=rut).first()
    prueba = srv.usa_prueba_gratis(existente) if existente else tarifa.prueba_gratis
    return JsonResponse({'valido': True, 'existe': bool(existente), 'nombre': existente.nombre if existente else '',
                         'prueba': prueba, 'precio': tarifa.precio_clase_suelta})


@rol_requerido(PERSONAL)
def salas_reservas(request):
    """Reservas de sala (internas y solicitudes de visitantes)."""
    hoy = timezone.localdate()
    reservas = ReservaSala.objects.select_related('sala', 'visitante').filter(fecha__gte=hoy).order_by('fecha', 'hora_inicio', 'id')
    pendientes = reservas.filter(estado=ReservaSala.Estado.SOLICITADA)
    return render(request, 'reservas/salas_reservas.html', {
        'pagina': paginar(request, reservas, 12), 'pag_pendientes': paginar(request, pendientes, 6, 'p_pend'),
        'puede_admin': _es_admin(request.user),
        'form_pago': PagoVisitaForm(),
    })


@rol_requerido(PERSONAL)
def reservar_sala_staff(request):
    form = ReservaSalaStaffForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            with transaction.atomic():
                r = srv.crear_reserva_sala(d['sala'], d['fecha'], d['hora_inicio'], d['hora_fin'], d['motivo'],
                                           d['personas'], creada_por=request.user)
                if d['cobrar_ahora']:
                    srv.registrar_pago_reserva(r, d['metodo'], request.user)
        except ReglaError as e:
            messages.error(request, str(e))
        else:
            horas = (r.fin_dt - r.inicio_dt).total_seconds() / 3600
            registrar_auditoria(request.user, "RESERVAR_SALA", f"{r} (${r.precio})")
            messages.success(request, f"Sala reservada: {r}. Precio por {horas:g} hora(s): ${r.precio:,}".replace(",", ".")
                             + (" · cobrado." if d['cobrar_ahora'] else ". Queda pendiente de cobro en «Reservas de sala»."))
            return redirect('reservas:salas_reservas')
    return render(request, 'reservas/reservar_sala.html', {
        'form': form, 'salas': Sala.objects.filter(activa=True), 'precios': _precios_json(), 'prefijo_campos': '',
    })


@require_POST
@rol_requerido(ADMINISTRACION)
def aprobar_reserva(request, pk):
    reserva = get_object_or_404(ReservaSala, pk=pk)
    try:
        srv.aprobar_reserva(reserva, request.user)
        registrar_auditoria(request.user, "APROBAR_SALA", f"{reserva}")
        messages.success(request, "Solicitud aprobada. Se avisó al visitante por correo.")
    except ReglaError as e:
        messages.error(request, str(e))
    return redirect('reservas:salas_reservas')


@require_POST
@rol_requerido(ADMINISTRACION)
def rechazar_reserva(request, pk):
    reserva = get_object_or_404(ReservaSala, pk=pk)
    try:
        srv.rechazar_reserva(reserva, request.user, request.POST.get('nota', ''))
        registrar_auditoria(request.user, "RECHAZAR_SALA", f"{reserva}")
        messages.success(request, "Solicitud rechazada.")
    except ReglaError as e:
        messages.error(request, str(e))
    return redirect('reservas:salas_reservas')


@require_POST
@rol_requerido(PERSONAL)
def cancelar_reserva(request, pk):
    reserva = get_object_or_404(ReservaSala, pk=pk)
    try:
        srv.cancelar_reserva_sala(reserva, desde_personal=True)
        registrar_auditoria(request.user, "CANCELAR_SALA", f"{reserva}")
        messages.success(request, "Reserva cancelada.")
    except ReglaError as e:
        messages.error(request, str(e))
    return redirect('reservas:salas_reservas')


@require_POST
@rol_requerido(PERSONAL)
def cobrar_reserva(request, pk):
    reserva = get_object_or_404(ReservaSala, pk=pk)
    form = PagoVisitaForm(request.POST)
    if form.is_valid():
        try:
            srv.registrar_pago_reserva(reserva, form.cleaned_data['metodo'], request.user)
            registrar_auditoria(request.user, "COBRAR_SALA", f"${reserva.precio} por {reserva}")
            messages.success(request, f"Pago registrado: ${reserva.precio:,}".replace(",", "."))
        except ReglaError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Elige un método de pago.")
    return redirect('reservas:salas_reservas')


# =====================================================================
# INSTRUCTOR
# =====================================================================
@rol_requerido(['INSTRUCTOR'])
def agenda(request):
    srv.asegurar_sesiones()
    hoy = timezone.localdate()
    sesiones = srv.sesiones_con_cupos(hoy - timedelta(days=1), hoy + timedelta(days=7), solo_activas=False).filter(
        Q(instructor=request.user) | Q(instructor__isnull=True, clase__instructor=request.user))
    for s in sesiones:
        s.puede_ver = srv.instructor_puede_ver(request.user, s)
    return render(request, 'reservas/agenda.html', {
        'dias': _agrupar_por_dia(sesiones),
        'pendientes': SolicitudCambio.objects.filter(solicitante=request.user, estado=SolicitudCambio.Estado.PENDIENTE).count(),
    })


@rol_requerido(['INSTRUCTOR'])
def sesion_instructor(request, pk):
    sesion = get_object_or_404(Sesion.objects.select_related('clase__sala', 'clase__instructor', 'instructor'), pk=pk)
    if sesion.instructor_efectivo is None or sesion.instructor_efectivo.pk != request.user.pk:
        raise PermissionDenied("Esta clase no es tuya.")
    puede_ver = srv.instructor_puede_ver(request.user, sesion)
    # El instructor ve inscritos con foto, pero no pagos ni datos de contacto.
    inscritos = sesion.inscripciones.filter(estado__in=srv.OCUPAN).select_related('socio__usuario', 'visitante') if puede_ver else []
    return render(request, 'reservas/sesion_instructor.html', {
        'sesion': sesion, 'inscritos': inscritos, 'puede_ver': puede_ver,
        'form_cambio': CambioForm(),
        'solicitudes': sesion.solicitudes.filter(solicitante=request.user),
    })


@require_POST
@rol_requerido(['INSTRUCTOR'])
def instructor_marcar(request, pk):
    insc = get_object_or_404(Inscripcion.objects.select_related('sesion__clase'), pk=pk)
    if not srv.instructor_puede_ver(request.user, insc.sesion):
        raise PermissionDenied("No puedes pasar lista de esta clase.")
    if insc.sesion.cerrada:
        messages.error(request, "La clase ya está cerrada.")
    else:
        try:
            srv.marcar_asistencia(insc, request.user, asistio=request.POST.get('asistio') == '1')
        except ReglaError as e:
            messages.error(request, str(e))
    return redirect('reservas:sesion_instructor', pk=insc.sesion_id)


@require_POST
@rol_requerido(['INSTRUCTOR'])
def instructor_cerrar(request, pk):
    sesion = get_object_or_404(Sesion, pk=pk)
    if not srv.instructor_puede_ver(request.user, sesion):
        raise PermissionDenied("No puedes cerrar esta clase.")
    try:
        srv.cerrar_sesion(sesion, request.user)
        messages.success(request, "Clase cerrada. Quienes no tenían asistencia quedaron como «no asistió».")
    except ReglaError as e:
        messages.error(request, str(e))
    return redirect('reservas:sesion_instructor', pk=pk)


@require_POST
@rol_requerido(['INSTRUCTOR'])
def instructor_pedir_cambio(request, pk):
    sesion = get_object_or_404(Sesion, pk=pk)
    if sesion.instructor_efectivo is None or sesion.instructor_efectivo.pk != request.user.pk:
        raise PermissionDenied("Esta clase no es tuya.")
    form = CambioForm(request.POST)
    if form.is_valid():
        try:
            srv.pedir_cambio(sesion, request.user, form.cleaned_data['tipo'], form.cleaned_data['motivo'])
            messages.success(request, "Solicitud enviada a administración.")
        except ReglaError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Indica el motivo (mínimo 5 caracteres).")
    return redirect('reservas:sesion_instructor', pk=pk)


# =====================================================================
# ADMINISTRACIÓN: salas, clases, sesiones, bloqueos, tarifas, cambios, informes
# =====================================================================
@rol_requerido(PERSONAL)
def lista_salas(request):
    return render(request, 'reservas/salas_lista.html', {
        'pagina': paginar(request, Sala.objects.all().order_by('nombre', 'id'), 9), 'puede_admin': _es_admin(request.user),
    })


def _form_generico(request, form, titulo, destino, texto='', multipart=False, extra=None):
    contexto = {'form': form, 'titulo': titulo, 'volver': destino, 'texto': texto, 'multipart': multipart}
    if extra:
        contexto.update(extra)
    return render(request, 'reservas/form_generico.html', contexto)


@rol_requerido(ADMINISTRACION)
def crear_sala(request):
    form = SalaForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        sala = form.save()
        registrar_auditoria(request.user, "CREAR_SALA", sala.nombre)
        messages.success(request, f"Sala '{sala.nombre}' creada.")
        return redirect('reservas:lista_salas')
    return _form_generico(request, form, 'Nueva sala', 'reservas:lista_salas', multipart=True)


@rol_requerido(ADMINISTRACION)
def editar_sala(request, pk):
    sala = get_object_or_404(Sala, pk=pk)
    form = SalaForm(request.POST or None, request.FILES or None, instance=sala)
    if request.method == 'POST' and form.is_valid():
        form.save()
        registrar_auditoria(request.user, "EDITAR_SALA", sala.nombre)
        messages.success(request, "Sala actualizada.")
        return redirect('reservas:lista_salas')
    return _form_generico(request, form, f'Editar {sala.nombre}', 'reservas:lista_salas', multipart=True)


@rol_requerido(PERSONAL)
def lista_clases(request):
    pagina = paginar(request, Clase.objects.select_related('sala', 'instructor').order_by('nombre', 'hora_inicio', 'id'), 10)
    # Próxima sesión de cada clase: para ver o agregar gente directamente desde la lista.
    hoy, ahora = timezone.localdate(), timezone.localtime()
    proximas = {}
    for s in srv.sesiones_con_cupos(hoy, hoy + timedelta(days=45), solo_activas=False).filter(
            clase_id__in=[c.pk for c in pagina], estado=Sesion.Estado.NORMAL, cerrada=False):
        if s.clase_id not in proximas and s.fin_dt >= ahora:
            proximas[s.clase_id] = s
    for c in pagina:
        c.proxima = proximas.get(c.pk)
    return render(request, 'reservas/clases_lista.html', {'pagina': pagina, 'puede_admin': _es_admin(request.user)})


@rol_requerido(PERSONAL)
def clase_sesiones(request, pk):
    """Próximas sesiones de una clase, con acceso a ver la gente inscrita y a agregar más."""
    clase = get_object_or_404(Clase.objects.select_related('sala', 'instructor'), pk=pk)
    hoy, ahora = timezone.localdate(), timezone.localtime()
    sesiones = [s for s in srv.sesiones_con_cupos(hoy, hoy + timedelta(days=45), solo_activas=False).filter(clase=clase)
                if s.fin_dt >= ahora]
    return render(request, 'reservas/clase_sesiones.html', {
        'clase': clase, 'pagina': paginar(request, sesiones, 10), 'puede_admin': _es_admin(request.user),
    })


@rol_requerido(ADMINISTRACION)
def crear_clase(request):
    form = ClaseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        clase = form.save()
        srv.generar_sesiones(clases=[clase])
        registrar_auditoria(request.user, "CREAR_CLASE", clase.nombre)
        messages.success(request, f"Clase '{clase.nombre}' creada. Se generaron sus sesiones de las próximas 4 semanas.")
        return redirect('reservas:lista_clases')
    return _form_generico(request, form, 'Nueva clase', 'reservas:lista_clases',
                          texto='Se crean solas las sesiones de las próximas 4 semanas (salvo en fechas bloqueadas).')


@rol_requerido(ADMINISTRACION)
def editar_clase(request, pk):
    clase = get_object_or_404(Clase, pk=pk)
    form = ClaseForm(request.POST or None, instance=clase)
    if request.method == 'POST' and form.is_valid():
        clase = form.save()
        srv.resincronizar_clase(clase)
        registrar_auditoria(request.user, "EDITAR_CLASE", clase.nombre)
        messages.success(request, "Clase actualizada. Las sesiones futuras sin inscritos se rehicieron; las que tienen inscritos se conservan.")
        return redirect('reservas:lista_clases')
    return _form_generico(request, form, f'Editar {clase.nombre}', 'reservas:lista_clases')


@require_POST
@rol_requerido(ADMINISTRACION)
def alternar_clase(request, pk):
    clase = get_object_or_404(Clase, pk=pk)
    clase.activa = not clase.activa
    clase.save(update_fields=['activa'])
    if clase.activa:
        srv.reactivar_clase(clase)
        extra = ""
    else:
        n = srv.suspender_clase(clase)
        extra = f" Se cancelaron {n} sesión(es) futuras y se avisó a los inscritos." if n else ""
    registrar_auditoria(request.user, "ALTERNAR_CLASE", f"{clase.nombre} {'activada' if clase.activa else 'desactivada'}")
    messages.success(request, f"Clase {'activada' if clase.activa else 'desactivada'}.{extra}")
    return redirect('reservas:lista_clases')


@rol_requerido(ADMINISTRACION)
def cancelar_sesion(request, pk):
    sesion = get_object_or_404(Sesion.objects.select_related('clase'), pk=pk)
    form = MotivoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            srv.cancelar_sesion(sesion, form.cleaned_data['motivo'])
            registrar_auditoria(request.user, "CANCELAR_SESION", f"{sesion}: {form.cleaned_data['motivo']}")
            messages.success(request, "Sesión cancelada. Se avisó a los inscritos.")
            return redirect('reservas:sesion_detalle', pk=pk)
        except ReglaError as e:
            messages.error(request, str(e))
    return _form_generico(request, form, f'Cancelar {sesion}', 'reservas:ocupacion',
                          texto='Solo se cancela esta sesión: las demás de la clase no cambian.')


@require_POST
@rol_requerido(ADMINISTRACION)
def sesion_suplente(request, pk):
    sesion = get_object_or_404(Sesion, pk=pk)
    form = SesionInstructorForm(request.POST)
    if form.is_valid():
        sesion.instructor = form.cleaned_data['instructor']
        sesion.save(update_fields=['instructor'])
        registrar_auditoria(request.user, "SUPLENTE", f"{sesion}: {sesion.instructor or 'el de la clase'}")
        messages.success(request, "Instructor de la sesión actualizado.")
    return redirect('reservas:sesion_detalle', pk=pk)


@rol_requerido(ADMINISTRACION)
def lista_bloqueos(request):
    bloqueos = BloqueoFecha.objects.select_related('sala').filter(fecha_hasta__gte=timezone.localdate()).order_by('fecha_desde', 'id')
    return render(request, 'reservas/bloqueos_lista.html', {'pagina': paginar(request, bloqueos, 12)})


@rol_requerido(ADMINISTRACION)
def crear_bloqueo(request):
    form = BloqueoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        b = form.save()
        # Las sesiones de esos días se cancelan (y se avisa a los inscritos).
        sesiones = Sesion.objects.filter(fecha__gte=max(b.fecha_desde, timezone.localdate()), fecha__lte=b.fecha_hasta,
                                         estado=Sesion.Estado.NORMAL, cerrada=False)
        if b.sala_id:
            sesiones = sesiones.filter(clase__sala=b.sala)
        canceladas = 0
        for s in sesiones:
            try:
                srv.cancelar_sesion(s, f"Cierre: {b.motivo}")
                canceladas += 1
            except ReglaError:
                pass
        reservas = ReservaSala.objects.filter(
            fecha__gte=b.fecha_desde, fecha__lte=b.fecha_hasta,
            estado__in=(ReservaSala.Estado.SOLICITADA, ReservaSala.Estado.APROBADA))
        if b.sala_id:
            reservas = reservas.filter(sala=b.sala)
        n_reservas = reservas.count()
        registrar_auditoria(request.user, "BLOQUEO", f"{b} ({canceladas} sesiones canceladas)")
        messages.success(request, f"Bloqueo creado. Se cancelaron {canceladas} sesión(es) y se avisó a los inscritos.")
        if n_reservas:
            messages.warning(request, f"Hay {n_reservas} reserva(s) de sala en esas fechas: revísalas en «Reservas de sala» y cancélalas si corresponde.")
        return redirect('reservas:lista_bloqueos')
    return _form_generico(request, form, 'Bloquear fechas (feriados o cierres)', 'reservas:lista_bloqueos',
                          texto='En estas fechas no se crean sesiones ni se reservan salas.')


@require_POST
@rol_requerido(ADMINISTRACION)
def eliminar_bloqueo(request, pk):
    b = get_object_or_404(BloqueoFecha, pk=pk)
    # Las sesiones que se cancelaron por este cierre vuelven a quedar normales.
    Sesion.objects.filter(
        fecha__gte=b.fecha_desde, fecha__lte=b.fecha_hasta, estado=Sesion.Estado.CANCELADA,
        motivo_cancelacion=f"Cierre: {b.motivo}"[:200],
    ).update(estado=Sesion.Estado.NORMAL, motivo_cancelacion="")
    b.delete()
    srv.generar_sesiones()   # crea las sesiones que faltaban en esas fechas
    messages.success(request, "Bloqueo eliminado.")
    return redirect('reservas:lista_bloqueos')


@rol_requerido(ADMINISTRACION)
def editar_tarifas(request):
    form = TarifaForm(request.POST or None, instance=Tarifa.obtener())
    if request.method == 'POST' and form.is_valid():
        form.save()
        registrar_auditoria(request.user, "EDITAR_TARIFAS", "Tarifas de visitantes actualizadas")
        messages.success(request, "Tarifas actualizadas. Los precios por hora de cada sala se editan en la sala.")
        return redirect('reservas:lista_salas')
    return _form_generico(request, form, 'Tarifas y reglas de visitantes', 'reservas:lista_salas')


@rol_requerido(ADMINISTRACION)
def solicitudes_cambio(request):
    pendientes = SolicitudCambio.objects.filter(estado=SolicitudCambio.Estado.PENDIENTE).select_related(
        'sesion__clase', 'solicitante')
    resueltas = SolicitudCambio.objects.exclude(estado=SolicitudCambio.Estado.PENDIENTE).select_related(
        'sesion__clase', 'solicitante')[:15]
    return render(request, 'reservas/solicitudes_cambio.html', {
        'pagina': paginar(request, pendientes.order_by('creada', 'id'), 8), 'resueltas': resueltas, 'form': ResolverCambioForm(),
    })


@require_POST
@rol_requerido(ADMINISTRACION)
def resolver_cambio(request, pk):
    solicitud = get_object_or_404(SolicitudCambio, pk=pk)
    form = ResolverCambioForm(request.POST)
    if form.is_valid():
        try:
            srv.resolver_cambio(solicitud, request.user, request.POST.get('decision') == 'aprobar',
                                form.cleaned_data['suplente'], form.cleaned_data['nota'])
            registrar_auditoria(request.user, "RESOLVER_CAMBIO", f"{solicitud} → {solicitud.get_estado_display()}")
            messages.success(request, f"Solicitud {solicitud.get_estado_display().lower()}.")
        except ReglaError as e:
            messages.error(request, str(e))
    return redirect('reservas:solicitudes_cambio')


@rol_requerido(ADMINISTRACION)
def informe(request):
    hoy = timezone.localdate()
    desde = _fecha(request.GET.get('desde'), hoy - timedelta(days=30))
    hasta = _fecha(request.GET.get('hasta'), hoy)
    sesiones = Sesion.objects.filter(fecha__gte=desde, fecha__lte=hasta, estado=Sesion.Estado.NORMAL)
    por_clase = sesiones.values('clase__nombre').annotate(
        n_sesiones=Count('id', distinct=True),
        asistieron=Count('inscripciones', filter=Q(inscripciones__estado=Inscripcion.Estado.ASISTIO)),
        faltaron=Count('inscripciones', filter=Q(inscripciones__estado=Inscripcion.Estado.NO_ASISTIO)),
        inscritos=Count('inscripciones', filter=Q(inscripciones__estado__in=srv.OCUPAN)),
    ).order_by('-inscritos')
    filas = []
    for f in por_clase:
        marcados = f['asistieron'] + f['faltaron']
        f['asistencia_pct'] = round(100 * f['asistieron'] / marcados) if marcados else None
        filas.append(f)
    faltones = Inscripcion.objects.filter(
        estado=Inscripcion.Estado.NO_ASISTIO, socio__isnull=False, sesion__fecha__gte=desde, sesion__fecha__lte=hasta,
    ).values('socio__usuario__first_name', 'socio__usuario__last_name', 'socio__rut').annotate(n=Count('id')).order_by('-n')[:10]
    canceladas = Sesion.objects.filter(fecha__gte=desde, fecha__lte=hasta, estado=Sesion.Estado.CANCELADA).count()
    return render(request, 'reservas/informe.html', {
        'desde': desde, 'hasta': hasta, 'pagina': paginar(request, filas, 12), 'faltones': faltones, 'canceladas': canceladas,
        'total_sesiones': sesiones.count(),
    })
