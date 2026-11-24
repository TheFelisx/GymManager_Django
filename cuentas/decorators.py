from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied

def rol_requerido(roles_permitidos):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('cuentas:login')

            if request.user.debe_cambiar_clave:
                messages.warning(request, "Por seguridad, debes cambiar tu contraseña antes de continuar.")
                return redirect('cuentas:cambiar_clave')

            if request.user.is_superuser or request.user.rol in roles_permitidos:
                return view_func(request, *args, **kwargs)

            raise PermissionDenied("No tienes permisos para acceder a esta sección.")
        return _wrapped_view
    return decorator
