import secrets

from django.contrib.sessions.models import Session
from django.utils import timezone

from .models import RegistroAuditoria


def registrar_auditoria(usuario, accion: str, detalle: str):
    actor = usuario if (usuario and usuario.is_authenticated) else None
    RegistroAuditoria.objects.create(
        usuario=actor,
        accion=accion,
        detalle=detalle
    )


def generar_clave_temporal(largo: int = 8) -> str:
    """Clave temporal aleatoria (sin caracteres que se confundan al leerlos)."""
    alfabeto = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alfabeto) for _ in range(largo))


def cerrar_sesiones(usuario) -> int:
    """Cierra todas las sesiones abiertas de un usuario. Devuelve cuántas cerró."""
    cerradas = 0
    for sesion in Session.objects.filter(expire_date__gte=timezone.now()):
        if sesion.get_decoded().get('_auth_user_id') == str(usuario.pk):
            sesion.delete()
            cerradas += 1
    return cerradas


def restablecer_clave(usuario, actor):
    """Asigna una clave temporal nueva, obliga a cambiarla y cierra sus sesiones."""
    clave = generar_clave_temporal()
    usuario.set_password(clave)
    usuario.debe_cambiar_clave = True
    usuario.save(update_fields=['password', 'debe_cambiar_clave'])
    cerrar_sesiones(usuario)
    registrar_auditoria(actor, "RESTABLECER_CLAVE", f"Clave restablecida para {usuario.username}")
    return clave


def puede_gestionar(actor, objetivo) -> bool:
    """Quién puede editar, desactivar o restablecer la clave de quién.

    - El master gestiona a todos.
    - El administrador gestiona solo recepcionistas, guardias y socios
      (no toca al master ni a otros administradores).
    - El recepcionista gestiona solo cuentas de socios.
    """
    if actor.es_master:
        return True
    if actor.es_admin:
        return objetivo.rol in ('RECEPCIONISTA', 'GUARDIA', 'INSTRUCTOR', 'SOCIO') and not objetivo.is_superuser
    if actor.rol == 'RECEPCIONISTA':
        return objetivo.rol == 'SOCIO'
    return False
