from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import redirect, render

from panel.models import Plan
from .forms import ContactoForm
from .models import Entrenador, PreguntaFrecuente

MAX_MENSAJES_POR_IP = 3
VENTANA_MENSAJES = 10 * 60


def inicio_publico(request):
    return render(request, 'publica/inicio.html', {
        'planes': Plan.objects.filter(activo=True).order_by('precio'),
        'entrenadores': Entrenador.objects.filter(activo=True),
        'preguntas': PreguntaFrecuente.objects.filter(activa=True),
        'form_contacto': ContactoForm(),
    })


def enviar_contacto(request):
    """Recibe el formulario de contacto de la página pública."""
    if request.method != 'POST':
        return redirect('publica:inicio')

    form = ContactoForm(request.POST)
    clave = f"contacto-{request.META.get('REMOTE_ADDR', 'x')}"
    if cache.get(clave, 0) >= MAX_MENSAJES_POR_IP:
        messages.error(request, "Enviaste varios mensajes seguidos. Inténtalo de nuevo en unos minutos.")
        return redirect('publica:inicio')

    if form.is_valid():
        mensaje = form.save()
        cache.add(clave, 0, VENTANA_MENSAJES)
        try:
            cache.incr(clave)
        except ValueError:
            cache.set(clave, 1, VENTANA_MENSAJES)
        try:
            send_mail(
                subject=f"Nuevo mensaje de contacto de {mensaje.nombre}",
                message=f"De: {mensaje.nombre} <{mensaje.email}>\nTeléfono: {mensaje.telefono or '-'}\n\n{mensaje.mensaje}",
                from_email=None,
                recipient_list=[settings.GYM_INFO['email']],
            )
        except Exception:
            pass   # el mensaje igual queda guardado y se ve en el admin
        messages.success(request, "¡Gracias! Recibimos tu mensaje y te responderemos pronto.")
    else:
        messages.error(request, "No pudimos enviar el mensaje: revisa los datos e inténtalo de nuevo.")
    return redirect('/#contacto')
