"""Genera la imagen del código QR de los socios que aún no la tienen.

Sirve después de cargar datos de ejemplo por SQL (que no incluye las imágenes):
    python manage.py generar_qr_faltantes
"""
from django.core.management.base import BaseCommand

from panel.models import Socio


class Command(BaseCommand):
    help = "Crea la imagen del QR de los socios que no la tienen."

    def handle(self, *args, **opciones):
        creados = 0
        for socio in Socio.objects.filter(imagen_qr=''):
            socio.generar_qr()
            socio.save(update_fields=['imagen_qr'])
            creados += 1
        self.stdout.write(self.style.SUCCESS(f"QR generados: {creados}"))
