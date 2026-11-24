"""Crea las sesiones de las próximas semanas y hace el mantenimiento de reservas.

Úsalo a diario (por ejemplo con cron o el Programador de tareas):
    python manage.py generar_sesiones
"""
from django.core.management.base import BaseCommand

from reservas import services


class Command(BaseCommand):
    help = "Genera sesiones de clases, cancela reservas con membresía vencida, libera reservas sin pagar y cierra clases olvidadas."

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=28, help="Cuántos días hacia adelante (por defecto 28).")

    def handle(self, *args, **opciones):
        creadas = services.generar_sesiones(dias=opciones['dias'])
        canceladas = services.revisar_vencimientos()
        liberadas = services.liberar_pendientes()
        cerradas = services.cerrar_vencidas()
        self.stdout.write(self.style.SUCCESS(
            f"Sesiones creadas: {creadas} · reservas canceladas por vencimiento: {canceladas} · reservas liberadas: {liberadas} · clases cerradas solas: {cerradas}"))
