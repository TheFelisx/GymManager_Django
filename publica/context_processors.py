from django.conf import settings


def gimnasio(request):
    """Datos de contacto del gimnasio disponibles en todas las plantillas como `gym`."""
    return {'gym': settings.GYM_INFO}
