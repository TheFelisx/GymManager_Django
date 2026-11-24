from django.db import models
from cuentas.models import Usuario
from panel.models import Socio

class RegistroAcceso(models.Model):
    class Metodo(models.TextChoices):
        QR = 'QR', 'Código QR'
        RUT = 'RUT', 'RUT Manual'

    socio = models.ForeignKey(
        Socio,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accesos',
        verbose_name='Socio'
    )
    identificador_ingresado = models.CharField(
        max_length=100,
        verbose_name='RUT o Token leído'
    )
    metodo = models.CharField(
        max_length=10,
        choices=Metodo.choices,
        default=Metodo.RUT
    )
    permitido = models.BooleanField(default=False, verbose_name='Acceso permitido')
    motivo = models.CharField(max_length=200, verbose_name='Resultado / Motivo')
    fecha_hora = models.DateTimeField(auto_now_add=True, verbose_name='Fecha y hora')
    validado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='Guardia / Personal'
    )

    class Meta:
        verbose_name = 'Registro de acceso'
        verbose_name_plural = 'Registros de acceso'
        ordering = ['-fecha_hora']

    def __str__(self):
        estado = "PERMITIDO" if self.permitido else "DENEGADO"
        return f"[{self.fecha_hora:%d/%m %H:%M}] {estado} - {self.identificador_ingresado}"
