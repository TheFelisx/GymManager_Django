import uuid

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from cuentas.decorators import rol_requerido
from cuentas.validators import limpiar_rut
from panel.models import Socio
from panel.services import rango_dia
from reservas import services as reservas_srv
from .models import RegistroAcceso

ROLES_TOTEM = ['MASTER', 'ADMIN', 'RECEPCIONISTA', 'GUARDIA']


# ---------------------------------------------------------------------
# Límite de intentos: nadie puede probar códigos al azar
# ---------------------------------------------------------------------
def _clave_desconocidos(usuario):
    return f"totem-desconocidos-{usuario.pk}"


def totem_bloqueado(usuario) -> bool:
    return cache.get(_clave_desconocidos(usuario), 0) >= settings.TOTEM_MAX_DESCONOCIDOS


def _anotar_desconocido(usuario):
    clave = _clave_desconocidos(usuario)
    cache.add(clave, 0, settings.TOTEM_VENTANA_SEGUNDOS)
    try:
        cache.incr(clave)
    except ValueError:
        cache.set(clave, 1, settings.TOTEM_VENTANA_SEGUNDOS)


# ---------------------------------------------------------------------
# Evaluación del acceso
# ---------------------------------------------------------------------
def _registrar(guardia, texto, metodo, permitido, motivo, socio=None):
    RegistroAcceso.objects.create(
        socio=socio,
        identificador_ingresado=(socio.rut_formateado if socio else texto)[:100],
        metodo=metodo,
        permitido=permitido,
        motivo=motivo[:200],
        validado_por=guardia,
    )


def evaluar_acceso(codigo_o_rut: str, guardia):
    """Evalúa si un socio puede ingresar y registra el intento en la base de datos.

    Revisa: que la persona exista, que esté activa, que su membresía esté
    vigente y que el día y la hora entren en el horario de su plan.
    """
    texto = (codigo_o_rut or "").strip()[:100]
    socio = None
    metodo = RegistroAcceso.Metodo.RUT

    # 0. ¿Es el código de un visitante (clase suelta o arriendo de sala)?
    visita = reservas_srv.evaluar_codigo_visita(texto, guardia)
    if visita is not None:
        v = visita['visitante']
        _registrar(guardia, f"Visitante {v.nombre} · {visita['detalle']}", RegistroAcceso.Metodo.QR,
                   visita['permitido'], visita['motivo'])
        return {'permitido': visita['permitido'], 'motivo': visita['motivo'], 'socio': None, 'plan': None,
                'visitante': v, 'detalle': visita['detalle']}

    # 1. ¿Es un UUID (código QR)?
    try:
        token_uuid = uuid.UUID(texto)
        socio = Socio.objects.select_related('usuario').filter(token_qr=token_uuid).first()
        metodo = RegistroAcceso.Metodo.QR
    except ValueError:
        # 2. Si no, se busca como RUT
        socio = Socio.objects.select_related('usuario').filter(rut=limpiar_rut(texto)).first()

    # A: no existe
    if not socio:
        motivo = "RUT o Código QR no registrado en el sistema."
        _registrar(guardia, texto, metodo, False, motivo)
        _anotar_desconocido(guardia)
        return {'permitido': False, 'motivo': motivo, 'socio': None, 'plan': None}

    # B: cuenta desactivada (baja)
    if not socio.usuario.is_active:
        motivo = "Cuenta de socio desactivada."
        _registrar(guardia, texto, metodo, False, motivo, socio)
        return {'permitido': False, 'motivo': motivo, 'socio': socio, 'plan': None}

    # C: membresía vigente
    pago_vigente = socio.ultimo_pago_vigente
    if not pago_vigente:
        motivo = "Membresía vencida o sin plan activo."
        _registrar(guardia, texto, metodo, False, motivo, socio)
        return {'permitido': False, 'motivo': motivo, 'socio': socio, 'plan': None}

    # D: día y hora permitidos por su plan
    plan = pago_vigente.plan
    en_horario, mensaje_horario = plan.dentro_de_horario()
    if not en_horario:
        _registrar(guardia, texto, metodo, False, mensaje_horario, socio)
        return {'permitido': False, 'motivo': mensaje_horario, 'socio': socio, 'plan': plan}

    motivo = f"Acceso permitido · Plan {plan.nombre}"
    # E: ¿tiene una clase ahora? Se muestra y su asistencia se marca sola.
    clase_txt = ""
    insc = reservas_srv.sesion_en_curso_de_socio(socio)
    if insc:
        reservas_srv.marcar_asistencia_automatica(insc, guardia)
        s = insc.sesion
        clase_txt = f"Clase ahora: {s.clase.nombre} {s.hora_inicio:%H:%M} · {s.clase.sala.nombre} (asistencia marcada)"
        motivo += f" · {s.clase.nombre}"
    _registrar(guardia, texto, metodo, True, motivo, socio)
    return {
        'permitido': True, 'motivo': motivo, 'socio': socio, 'plan': plan,
        'vencimiento': pago_vigente.fecha_vencimiento, 'clase': clase_txt,
    }


def _accesos_del_turno(usuario):
    """El guardia ve solo los accesos que él validó hoy; el personal ve todos los de hoy."""
    inicio, fin = rango_dia(timezone.localdate())
    accesos = RegistroAcceso.objects.select_related('socio__usuario').filter(fecha_hora__gte=inicio, fecha_hora__lt=fin)
    if usuario.rol == 'GUARDIA':
        accesos = accesos.filter(validado_por=usuario)
    return accesos


def _a_json(resultado):
    socio = resultado['socio']
    plan = resultado.get('plan')
    venc = resultado.get('vencimiento')
    visitante = resultado.get('visitante')
    return {
        'permitido': resultado['permitido'],
        'motivo': resultado['motivo'],
        'nombre': socio.usuario.get_full_name() if socio else (visitante.nombre if visitante else ''),
        'rut': socio.rut_formateado if socio else (visitante.rut_formateado if visitante else ''),
        'clase': resultado.get('clase', '') or resultado.get('detalle', ''),
        # La foto se muestra también cuando se deniega el acceso
        'foto': socio.foto.url if (socio and socio.foto) else '',
        'plan': plan.nombre if plan else '',
        'vencimiento': venc.strftime('%d/%m/%Y') if venc else '',
        'hora': timezone.localtime().strftime('%H:%M'),
    }


# ---------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------
@rol_requerido(ROLES_TOTEM)
def inicio_totem(request):
    """Pantalla del tótem. La validación normal ocurre en segundo plano (ver `validar`);
    el POST clásico se mantiene como plan B si el navegador no ejecuta JavaScript."""
    resultado = None
    bloqueado = totem_bloqueado(request.user)

    if request.method == 'POST':
        codigo = request.POST.get('codigo', '').strip()
        if codigo and not bloqueado:
            resultado = evaluar_acceso(codigo, request.user)

    return render(request, 'totem/inicio.html', {
        'resultado': resultado,
        'ultimos_accesos': _accesos_del_turno(request.user)[:8],
        'bloqueado': bloqueado,
        'es_guardia': request.user.rol == 'GUARDIA',
    })


@require_POST
@rol_requerido(ROLES_TOTEM)
def validar(request):
    """Valida un RUT o un QR sin recargar la página y responde en JSON."""
    if totem_bloqueado(request.user):
        return JsonResponse({
            'permitido': False,
            'bloqueado': True,
            'motivo': "Demasiados intentos con códigos desconocidos. Espera unos minutos.",
        }, status=429)

    codigo = request.POST.get('codigo', '').strip()
    if not codigo:
        return JsonResponse({'permitido': False, 'motivo': "Ingresa un RUT o escanea un QR."}, status=400)

    return JsonResponse(_a_json(evaluar_acceso(codigo, request.user)))
