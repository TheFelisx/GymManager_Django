from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from .forms import LoginForm
from .validators import limpiar_rut
from .utils import registrar_auditoria

def redireccionar_segun_rol(usuario):
    if usuario.is_superuser or usuario.rol in ('MASTER', 'ADMIN', 'RECEPCIONISTA'):
        return redirect('panel:inicio')
    if usuario.rol == 'GUARDIA':
        return redirect('totem:inicio')
    if usuario.rol == 'INSTRUCTOR':
        return redirect('reservas:agenda')
    return redirect('panel:zona_socio')


def _ip_cliente(request):
    return request.META.get('REMOTE_ADDR', 'desconocida')


def _claves_intentos(request, usuario_input):
    nombre = limpiar_rut(usuario_input) or usuario_input.lower()
    return f"login-user-{nombre}", f"login-ip-{_ip_cliente(request)}"


def _login_bloqueado(request, usuario_input):
    return any(cache.get(c, 0) >= settings.LOGIN_MAX_INTENTOS for c in _claves_intentos(request, usuario_input))


def _anotar_intento_fallido(request, usuario_input):
    for clave in _claves_intentos(request, usuario_input):
        cache.add(clave, 0, settings.LOGIN_BLOQUEO_SEGUNDOS)
        try:
            cache.incr(clave)
        except ValueError:
            cache.set(clave, 1, settings.LOGIN_BLOQUEO_SEGUNDOS)


def _limpiar_intentos(request, usuario_input):
    for clave in _claves_intentos(request, usuario_input):
        cache.delete(clave)

def vista_login(request):
    if request.user.is_authenticated:
        return redireccionar_segun_rol(request.user)

    form = LoginForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        usuario_input = form.cleaned_data['username'].strip()
        clave = form.cleaned_data['password']

        # Límite de intentos: tras varios fallos se bloquea un rato (por usuario e IP).
        if _login_bloqueado(request, usuario_input):
            messages.error(request, "Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo.")
            return render(request, 'cuentas/login.html', {'form': form})

        user = authenticate(request, username=usuario_input, password=clave)
        if user is None:
            user = authenticate(request, username=limpiar_rut(usuario_input), password=clave)

        if user is not None:
            _limpiar_intentos(request, usuario_input)
            if not user.is_active:
                messages.error(request, "Tu cuenta está desactivada. Contacta al administrador.")
                return render(request, 'cuentas/login.html', {'form': form})

            login(request, user)
            if user.rol == 'GUARDIA':
                request.session.set_expiry(60 * 60 * 12)   # sesión de un turno
            registrar_auditoria(user, "INICIO_SESION", f"Ingreso exitoso ({user.get_rol_display()})")

            if user.debe_cambiar_clave:
                return redirect('cuentas:cambiar_clave')

            return redireccionar_segun_rol(user)
        else:
            _anotar_intento_fallido(request, usuario_input)
            messages.error(request, "Usuario/RUT o contraseña incorrectos.")

    return render(request, 'cuentas/login.html', {'form': form})

@login_required
def vista_logout(request):
    registrar_auditoria(request.user, "CIERRE_SESION", "Cierre de sesión voluntario")
    logout(request)
    messages.info(request, "Has cerrado sesión correctamente.")
    return redirect('publica:inicio')

@login_required
def vista_cambiar_clave(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            user.debe_cambiar_clave = False
            user.save(update_fields=['debe_cambiar_clave'])
            update_session_auth_hash(request, user)
            registrar_auditoria(user, "CAMBIO_CLAVE", "El usuario actualizó su contraseña")
            messages.success(request, "Contraseña actualizada correctamente.")
            return redireccionar_segun_rol(user)
    else:
        form = PasswordChangeForm(request.user)

    return render(request, 'cuentas/cambiar_clave.html', {'form': form})
