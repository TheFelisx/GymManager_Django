import csv
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from cuentas.decorators import rol_requerido
from cuentas.forms import CrearUsuarioForm, EditarUsuarioForm
from cuentas.models import Usuario
from cuentas.utils import cerrar_sesiones, puede_gestionar, registrar_auditoria, restablecer_clave
from totem.models import RegistroAcceso
from reservas.models import Inscripcion, ReservaSala, Sesion, SolicitudCambio

from .paginacion import paginar
from .forms import EditarSocioForm, EnrolarSocioForm, MiPerfilForm, MotivoForm, PagoForm, PlanForm
from .models import Pago, Plan, Socio
from .services import (
    cobranza, filtrar_por_estado, pagos_validos, rango_dia, rango_fechas,
    resumen_por_metodo, socios_con_estado,
)

PERSONAL = ['MASTER', 'ADMIN', 'RECEPCIONISTA']
ADMINISTRACION = ['MASTER', 'ADMIN']


def _fecha(valor, defecto):
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        return defecto


def _exigir_gestion(actor, objetivo):
    if not puede_gestionar(actor, objetivo):
        raise PermissionDenied("No tienes permisos para gestionar a este usuario.")


# =====================================================================
# 1. DASHBOARD
# =====================================================================
@rol_requerido(PERSONAL)
def inicio_panel(request):
    hoy = timezone.localdate()
    inicio_dia, fin_dia = rango_dia(hoy)
    pagos_hoy_qs = pagos_validos().filter(fecha_pago__gte=inicio_dia, fecha_pago__lt=fin_dia)
    por_vencer, atrasados, _ = cobranza()
    socios = socios_con_estado()

    ver_dinero = request.user.es_master or request.user.es_admin
    context = {
        'total_socios': Socio.objects.count(),
        'socios_vigentes': socios.filter(usuario__is_active=True, vigente=True).count(),
        'planes_activos': Plan.objects.filter(activo=True).count(),
        'pagos_hoy': pagos_hoy_qs.count(),
        'ingresos_hoy': pagos_hoy_qs.aggregate(t=Sum('monto_pagado'))['t'] or 0,
        'accesos_hoy': RegistroAcceso.objects.filter(fecha_hora__gte=inicio_dia, fecha_hora__lt=fin_dia, permitido=True).count(),
        'denegados_hoy': RegistroAcceso.objects.filter(fecha_hora__gte=inicio_dia, fecha_hora__lt=fin_dia, permitido=False).count(),
        'n_por_vencer': por_vencer.count(),
        'n_atrasados': atrasados.count(),
        'por_vencer': por_vencer[:6],
        'ultimos_pagos': Pago.objects.select_related('socio__usuario', 'plan').order_by('-fecha_pago')[:5],
        'ver_dinero': ver_dinero,
        'dias_aviso': settings.DIAS_AVISO_VENCIMIENTO,
        'clases_hoy': Sesion.objects.filter(fecha=hoy, estado=Sesion.Estado.NORMAL).count(),
        'salas_pendientes': ReservaSala.objects.filter(estado=ReservaSala.Estado.SOLICITADA).count(),
        'cambios_pendientes': SolicitudCambio.objects.filter(estado=SolicitudCambio.Estado.PENDIENTE).count() if ver_dinero else 0,
    }
    return render(request, 'panel/inicio.html', context)


# =====================================================================
# 2. ZONA PRIVADA DEL SOCIO
# =====================================================================
@rol_requerido(['SOCIO'])
def zona_socio(request):
    socio = get_object_or_404(Socio, usuario=request.user)
    pago_vigente = socio.ultimo_pago_vigente
    dias = socio.dias_para_vencer
    context = {
        'socio': socio,
        'pago_vigente': pago_vigente,
        'historial_pagos': socio.pagos.select_related('plan').all()[:12],
        'dias_para_vencer': dias,
        'vence_pronto': pago_vigente is not None and dias is not None and dias <= settings.DIAS_AVISO_VENCIMIENTO,
        'vencimiento': socio.vencimiento_actual,
        'plan': pago_vigente.plan if pago_vigente else None,
        'proxima_clase': Inscripcion.objects.filter(
            socio=socio, estado=Inscripcion.Estado.CONFIRMADA, sesion__fecha__gte=timezone.localdate(),
            sesion__estado=Sesion.Estado.NORMAL).select_related('sesion__clase__sala').order_by('sesion__fecha', 'sesion__hora_inicio').first(),
    }
    return render(request, 'panel/zona_socio.html', context)


@rol_requerido(['SOCIO'])
def mi_perfil(request):
    socio = get_object_or_404(Socio, usuario=request.user)
    form = MiPerfilForm(request.POST or None, instance=socio)
    if request.method == 'POST' and form.is_valid():
        form.save()
        registrar_auditoria(request.user, "ACTUALIZAR_PERFIL", "El socio actualizó su teléfono y correo")
        messages.success(request, "Tus datos se actualizaron.")
        return redirect('panel:mi_perfil')
    return render(request, 'panel/mi_perfil.html', {'form': form, 'socio': socio})


# =====================================================================
# 3. PLANES
# =====================================================================
@rol_requerido(PERSONAL)
def lista_planes(request):
    hoy = timezone.localdate()
    planes = Plan.objects.annotate(
        socios_vigentes=Count(
            'pagos__socio', distinct=True,
            filter=Q(pagos__anulado=False, pagos__fecha_inicio__lte=hoy, pagos__fecha_vencimiento__gte=hoy),
        ),
        ingresos=Sum('pagos__monto_pagado', filter=Q(pagos__anulado=False)),
    ).order_by('-activo', 'nombre', 'id')
    puede_editar = request.user.es_master or request.user.es_admin
    return render(request, 'panel/planes_lista.html', {'pagina': paginar(request, planes, 15), 'puede_editar': puede_editar})


@rol_requerido(ADMINISTRACION)
def crear_plan(request):
    form = PlanForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        plan = form.save()
        registrar_auditoria(request.user, "CREAR_PLAN", f"Plan creado: {plan.nombre} (${plan.precio})")
        messages.success(request, f"Plan '{plan.nombre}' creado correctamente.")
        return redirect('panel:lista_planes')
    return render(request, 'panel/plan_form.html', {'form': form, 'titulo': 'Nuevo Plan'})


@rol_requerido(ADMINISTRACION)
def editar_plan(request, pk):
    plan = get_object_or_404(Plan, pk=pk)
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == 'POST' and form.is_valid():
        plan = form.save()
        registrar_auditoria(request.user, "EDITAR_PLAN", f"Plan actualizado: {plan.nombre}")
        messages.success(request, f"Plan '{plan.nombre}' actualizado.")
        return redirect('panel:lista_planes')
    return render(request, 'panel/plan_form.html', {'form': form, 'titulo': f'Editar {plan.nombre}'})


@require_POST
@rol_requerido(ADMINISTRACION)
def alternar_plan(request, pk):
    """Los planes nunca se borran: solo se activan o desactivan."""
    plan = get_object_or_404(Plan, pk=pk)
    plan.activo = not plan.activo
    plan.save(update_fields=['activo'])
    estado = "activado" if plan.activo else "desactivado"
    registrar_auditoria(request.user, "ALTERNAR_PLAN", f"Plan {plan.nombre} {estado}")
    messages.success(request, f"Plan '{plan.nombre}' {estado}.")
    return redirect('panel:lista_planes')


# =====================================================================
# 4. SOCIOS
# =====================================================================
@rol_requerido(PERSONAL)
def lista_socios(request):
    busqueda = request.GET.get('q', '').strip()
    estado = request.GET.get('estado', '').strip()
    socios = socios_con_estado()
    if busqueda:
        socios = socios.filter(
            Q(rut__icontains=busqueda.replace('.', '').replace('-', '')) |
            Q(usuario__first_name__icontains=busqueda) |
            Q(usuario__last_name__icontains=busqueda)
        )
    socios = filtrar_por_estado(socios, estado).order_by('usuario__first_name', 'usuario__last_name', 'id')
    return render(request, 'panel/socios_lista.html', {
        'pagina': paginar(request, socios, 15), 'busqueda': busqueda, 'estado': estado,
    })


@rol_requerido(PERSONAL)
def detalle_socio(request, pk):
    socio = get_object_or_404(socios_con_estado(), pk=pk)
    return render(request, 'panel/socio_detalle.html', {
        'socio': socio,
        'pagos': socio.pagos.select_related('plan', 'registrado_por').all()[:15],
        'accesos': socio.accesos.all()[:10],
        'puede_admin': request.user.es_master or request.user.es_admin,
    })


@rol_requerido(PERSONAL)
def enrolar_socio(request):
    form = EnrolarSocioForm(request.POST or None, request.FILES or None, actor=request.user)
    if request.method == 'POST' and form.is_valid():
        socio, clave_temporal = form.save(creador=request.user)
        registrar_auditoria(request.user, "ENROLAR_SOCIO", f"Socio registrado: {socio.rut_formateado}")
        if form.pago:
            registrar_auditoria(
                request.user, "REGISTRAR_PAGO",
                f"Primer pago #{form.pago.id} de ${form.pago.monto_pagado} para {socio.rut_formateado} ({form.pago.plan.nombre})"
            )
        extra = f" Primer pago registrado: vigente hasta el {form.pago.fecha_vencimiento:%d/%m/%Y}." if form.pago else ""
        messages.success(
            request,
            f"Socio {socio.usuario.get_full_name()} enrolado. Usuario: {socio.rut} | "
            f"Clave temporal: {clave_temporal} (anótala: no se vuelve a mostrar).{extra}"
        )
        return redirect('panel:detalle_socio', pk=socio.pk)
    return render(request, 'panel/socio_form.html', {'form': form, 'titulo': 'Enrolar nuevo socio', 'es_nuevo': True})


@rol_requerido(PERSONAL)
def editar_socio(request, pk):
    socio = get_object_or_404(Socio.objects.select_related('usuario'), pk=pk)
    form = EditarSocioForm(request.POST or None, request.FILES or None, instance=socio, actor=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        registrar_auditoria(request.user, "EDITAR_SOCIO", f"Datos del socio {socio.rut_formateado} actualizados")
        messages.success(request, "Datos del socio actualizados.")
        return redirect('panel:detalle_socio', pk=socio.pk)
    return render(request, 'panel/socio_form.html', {
        'form': form, 'titulo': f'Editar a {socio.usuario.get_full_name()}', 'es_nuevo': False, 'socio': socio,
    })


@rol_requerido(PERSONAL)
def baja_socio(request, pk):
    socio = get_object_or_404(Socio.objects.select_related('usuario'), pk=pk)
    _exigir_gestion(request.user, socio.usuario)
    if socio.de_baja:
        messages.info(request, "Este socio ya está dado de baja.")
        return redirect('panel:detalle_socio', pk=pk)
    form = MotivoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        socio.dar_de_baja(form.cleaned_data['motivo'])
        cerrar_sesiones(socio.usuario)
        registrar_auditoria(request.user, "BAJA_SOCIO", f"Baja de {socio.rut_formateado}: {socio.motivo_baja}")
        messages.success(request, "El socio fue dado de baja y su cuenta quedó desactivada.")
        return redirect('panel:detalle_socio', pk=pk)
    return render(request, 'panel/motivo_form.html', {
        'form': form, 'titulo': f'Dar de baja a {socio.usuario.get_full_name()}',
        'texto': "La cuenta del socio se desactivará y no podrá ingresar. Puedes reactivarlo cuando quieras.",
        'boton': 'Confirmar baja', 'volver': 'panel:detalle_socio', 'volver_pk': pk,
    })


@require_POST
@rol_requerido(PERSONAL)
def reactivar_socio(request, pk):
    socio = get_object_or_404(Socio.objects.select_related('usuario'), pk=pk)
    _exigir_gestion(request.user, socio.usuario)
    socio.reactivar()
    registrar_auditoria(request.user, "REACTIVAR_SOCIO", f"Socio {socio.rut_formateado} reactivado")
    messages.success(request, "Socio reactivado: su cuenta volvió a estar activa.")
    return redirect('panel:detalle_socio', pk=pk)


@require_POST
@rol_requerido(PERSONAL)
def regenerar_qr(request, pk):
    socio = get_object_or_404(Socio.objects.select_related('usuario'), pk=pk)
    socio.regenerar_qr()
    registrar_auditoria(request.user, "REGENERAR_QR", f"QR regenerado para {socio.rut_formateado}")
    messages.success(request, "Se generó un QR nuevo. El código anterior ya no sirve.")
    return redirect('panel:detalle_socio', pk=pk)


@require_POST
@rol_requerido(PERSONAL)
def restablecer_clave_socio(request, pk):
    socio = get_object_or_404(Socio.objects.select_related('usuario'), pk=pk)
    _exigir_gestion(request.user, socio.usuario)
    clave = restablecer_clave(socio.usuario, request.user)
    messages.success(
        request,
        f"Clave restablecida. Clave temporal: {clave} (anótala: no se vuelve a mostrar). "
        "Sus sesiones abiertas se cerraron y deberá cambiarla al entrar."
    )
    return redirect('panel:detalle_socio', pk=pk)


# =====================================================================
# 5. PAGOS
# =====================================================================
def _pagos_filtrados(request):
    hoy = timezone.localdate()
    desde = _fecha(request.GET.get('desde'), hoy.replace(day=1))
    hasta = _fecha(request.GET.get('hasta'), hoy)
    inicio, fin = rango_fechas(desde, hasta)
    pagos = Pago.objects.select_related('socio__usuario', 'plan', 'registrado_por').filter(
        fecha_pago__gte=inicio, fecha_pago__lt=fin
    )
    metodo = request.GET.get('metodo', '')
    plan = request.GET.get('plan', '')
    q = request.GET.get('q', '').strip()
    if metodo:
        pagos = pagos.filter(metodo_pago=metodo)
    if plan.isdigit():
        pagos = pagos.filter(plan_id=int(plan))
    if q:
        pagos = pagos.filter(
            Q(socio__rut__icontains=q.replace('.', '').replace('-', '')) |
            Q(socio__usuario__first_name__icontains=q) |
            Q(socio__usuario__last_name__icontains=q)
        )
    filtros = {'desde': desde, 'hasta': hasta, 'metodo': metodo, 'plan': plan, 'q': q}
    return pagos, filtros


@rol_requerido(PERSONAL)
def lista_pagos(request):
    pagos, filtros = _pagos_filtrados(request)
    validos = pagos.filter(anulado=False)
    return render(request, 'panel/pagos_lista.html', {
        'pagina': paginar(request, pagos.order_by('-fecha_pago', '-id'), 15),
        'filtros': filtros,
        'planes': Plan.objects.all(),
        'metodos': Pago.MetodoPago.choices,
        'total_periodo': validos.aggregate(t=Sum('monto_pagado'))['t'] or 0,
        'puede_admin': request.user.es_master or request.user.es_admin,
    })


@rol_requerido(ADMINISTRACION)
def exportar_pagos(request):
    """Descarga el historial filtrado en CSV (se abre directo en Excel)."""
    pagos, _ = _pagos_filtrados(request)
    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = 'attachment; filename="pagos_gymmanager.csv"'
    respuesta.write('\ufeff')  # BOM para que Excel respete las tildes
    escritor = csv.writer(respuesta, delimiter=';')
    escritor.writerow(['Fecha', 'RUT', 'Socio', 'Plan', 'Método', 'Descuento', 'Monto', 'Inicio', 'Vencimiento', 'Estado', 'Registrado por'])
    for p in pagos:
        escritor.writerow([
            timezone.localtime(p.fecha_pago).strftime('%d/%m/%Y %H:%M'), p.socio.rut_formateado,
            p.socio.usuario.get_full_name(), p.plan.nombre, p.get_metodo_pago_display(), p.descuento,
            p.monto_pagado, p.fecha_inicio.strftime('%d/%m/%Y'), p.fecha_vencimiento.strftime('%d/%m/%Y'),
            'Anulado' if p.anulado else 'Válido', p.registrado_por.username if p.registrado_por else '',
        ])
    return respuesta


@rol_requerido(PERSONAL)
def registrar_pago(request):
    inicial = {}
    if request.GET.get('socio', '').isdigit():
        inicial['socio'] = int(request.GET['socio'])
    form = PagoForm(request.POST or None, initial=inicial, actor=request.user)
    if request.method == 'POST' and form.is_valid():
        pago = form.save()
        registrar_auditoria(
            request.user, "REGISTRAR_PAGO",
            f"Pago #{pago.id} de ${pago.monto_pagado} para socio {pago.socio.rut_formateado} ({pago.plan.nombre})"
            + (f" con descuento ${pago.descuento}" if pago.descuento else "")
        )
        messages.success(request, f"Pago registrado. Plan vigente hasta el {pago.fecha_vencimiento:%d/%m/%Y}.")
        return redirect('panel:lista_pagos')
    return render(request, 'panel/pago_form.html', {'form': form})


@rol_requerido(ADMINISTRACION)
def anular_pago(request, pk):
    pago = get_object_or_404(Pago.objects.select_related('socio__usuario', 'plan'), pk=pk)
    if pago.anulado:
        messages.info(request, "Este pago ya estaba anulado.")
        return redirect('panel:lista_pagos')
    form = MotivoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        pago.anular(form.cleaned_data['motivo'], request.user)
        registrar_auditoria(request.user, "ANULAR_PAGO", f"Pago #{pago.id} anulado: {pago.motivo_anulacion}")
        messages.success(request, f"Pago #{pago.id} anulado. Ya no cuenta como ingreso ni da vigencia.")
        return redirect('panel:lista_pagos')
    return render(request, 'panel/motivo_form.html', {
        'form': form, 'titulo': f'Anular pago #{pago.id}',
        'texto': f"{pago.socio.usuario.get_full_name()} · {pago.plan.nombre} · ${pago.monto_pagado}. "
                 "Los pagos no se editan: se anulan con motivo y queda el registro.",
        'boton': 'Anular pago', 'volver': 'panel:lista_pagos', 'peligro': True,
    })


# =====================================================================
# 6. COBRANZA (qué vence y quién está atrasado)
# =====================================================================
@rol_requerido(PERSONAL)
def lista_cobranza(request):
    por_vencer, atrasados, sin_pagos = cobranza()
    return render(request, 'panel/cobranza.html', {
        'pag_vencer': paginar(request, por_vencer.order_by('ultimo_venc', 'id'), 10, 'p_vencer'),
        'pag_atrasados': paginar(request, atrasados.order_by('ultimo_venc', 'id'), 10, 'p_atrasados'),
        'pag_sin_pagos': paginar(request, sin_pagos.order_by('usuario__first_name', 'id'), 10, 'p_sin'),
        'dias_aviso': settings.DIAS_AVISO_VENCIMIENTO,
    })


@require_POST
@rol_requerido(PERSONAL)
def enviar_recordatorio(request, pk):
    socio = get_object_or_404(Socio.objects.select_related('usuario'), pk=pk)
    if not socio.usuario.email:
        messages.warning(request, "El socio no tiene correo registrado.")
        return redirect('panel:cobranza')
    venc = socio.vencimiento_actual
    if venc and venc >= timezone.localdate():
        estado = f"vence el {venc:%d/%m/%Y}"
    elif venc:
        estado = f"venció el {venc:%d/%m/%Y}"
    else:
        estado = "aún no tiene un plan pagado"
    info = settings.GYM_INFO
    try:
        send_mail(
            subject=f"{info['nombre']}: tu membresía",
            message=(
                f"Hola {socio.usuario.first_name},\n\n"
                f"Tu membresía {estado}. Puedes renovarla en recepción con tu RUT.\n\n"
                f"{info['nombre']} · {info['telefono']}"
            ),
            from_email=None,
            recipient_list=[socio.usuario.email],
        )
    except Exception:
        messages.error(request, "No se pudo enviar el correo. Revisa la configuración de correo.")
        return redirect('panel:cobranza')
    registrar_auditoria(request.user, "RECORDATORIO", f"Recordatorio de vencimiento enviado a {socio.rut_formateado}")
    messages.success(request, f"Recordatorio enviado a {socio.usuario.email}.")
    return redirect('panel:cobranza')


# =====================================================================
# 7. PERSONAL (usuarios del sistema)
# =====================================================================
@rol_requerido(ADMINISTRACION)
def lista_usuarios(request):
    usuarios = Usuario.objects.exclude(rol=Usuario.Rol.SOCIO).order_by('rol', 'username')
    return render(request, 'panel/usuarios_lista.html', {'pagina': paginar(request, usuarios, 15)})


@rol_requerido(ADMINISTRACION)
def crear_usuario_personal(request):
    form = CrearUsuarioForm(request.POST or None, creador=request.user)
    if request.method == 'POST' and form.is_valid():
        nuevo_usuario = form.save(commit=False)
        nuevo_usuario.creado_por = request.user
        nuevo_usuario.save()
        registrar_auditoria(
            request.user, "CREAR_USUARIO",
            f"Creó usuario {nuevo_usuario.username} con rol {nuevo_usuario.get_rol_display()}"
        )
        messages.success(request, f"Usuario '{nuevo_usuario.username}' creado correctamente.")
        return redirect('panel:lista_usuarios')
    return render(request, 'panel/usuario_form.html', {'form': form, 'titulo': 'Crear usuario del personal'})


@rol_requerido(ADMINISTRACION)
def editar_usuario(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    if usuario.rol == Usuario.Rol.SOCIO:
        return redirect('panel:lista_socios')
    _exigir_gestion(request.user, usuario)
    form = EditarUsuarioForm(request.POST or None, instance=usuario)
    if request.method == 'POST' and form.is_valid():
        form.save()
        registrar_auditoria(request.user, "EDITAR_USUARIO", f"Datos de {usuario.username} actualizados")
        messages.success(request, "Usuario actualizado.")
        return redirect('panel:lista_usuarios')
    return render(request, 'panel/usuario_form.html', {
        'form': form, 'titulo': f'Editar a {usuario.username}', 'edicion': True,
    })


@require_POST
@rol_requerido(ADMINISTRACION)
def alternar_usuario(request, pk):
    """Activa o desactiva una cuenta, con las protecciones del sistema."""
    usuario = get_object_or_404(Usuario, pk=pk)
    _exigir_gestion(request.user, usuario)

    if usuario.is_active:
        if usuario.pk == request.user.pk:
            messages.error(request, "No puedes desactivar tu propia cuenta.")
            return redirect('panel:lista_usuarios')
        if usuario.es_master and not Usuario.objects.filter(is_active=True).filter(
                Q(rol=Usuario.Rol.MASTER) | Q(is_superuser=True)).exclude(pk=usuario.pk).exists():
            messages.error(request, "Siempre debe quedar al menos un master activo.")
            return redirect('panel:lista_usuarios')
        usuario.is_active = False
        usuario.save(update_fields=['is_active'])
        cerrar_sesiones(usuario)
        accion, texto = "DESACTIVAR_USUARIO", "desactivado"
        if usuario.rol == Usuario.Rol.INSTRUCTOR:
            n_clases = usuario.clases_a_cargo.filter(activa=True).count()
            if n_clases:
                messages.warning(request, f"{usuario.username} tiene {n_clases} clase(s) activa(s) a su cargo: asígnales otro instructor en «Clases».")
    else:
        usuario.is_active = True
        usuario.save(update_fields=['is_active'])
        accion, texto = "ACTIVAR_USUARIO", "activado"

    registrar_auditoria(request.user, accion, f"Usuario {usuario.username} {texto}")
    messages.success(request, f"Usuario '{usuario.username}' {texto}.")
    return redirect('panel:lista_usuarios')


@require_POST
@rol_requerido(ADMINISTRACION)
def restablecer_clave_usuario(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    _exigir_gestion(request.user, usuario)
    if usuario.pk == request.user.pk:
        messages.error(request, "Para cambiar tu propia clave usa «Cambiar contraseña».")
        return redirect('panel:lista_usuarios')
    clave = restablecer_clave(usuario, request.user)
    messages.success(
        request,
        f"Clave de '{usuario.username}' restablecida. Clave temporal: {clave} "
        "(anótala: no se vuelve a mostrar). Sus sesiones abiertas se cerraron."
    )
    return redirect('panel:lista_usuarios')
