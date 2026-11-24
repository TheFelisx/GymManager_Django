from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from cuentas.models import Usuario


class Gasto(models.Model):
    class Categoria(models.TextChoices):
        ARRIENDO = 'ARRIENDO', 'Arriendo e Inmueble'
        SERVICIOS = 'SERVICIOS', 'Servicios Básicos (Luz, Agua, Internet)'
        SUELDOS = 'SUELDOS', 'Sueldos y Honorarios'
        EQUIPAMIENTO = 'EQUIPAMIENTO', 'Máquinas y Mantenimiento'
        INSUMOS = 'INSUMOS', 'Insumos y Limpieza'
        OTROS = 'OTROS', 'Otros Gastos'

    concepto = models.CharField(max_length=150, verbose_name="Concepto / Descripción")
    categoria = models.CharField(
        max_length=20,
        choices=Categoria.choices,
        default=Categoria.OTROS,
        verbose_name="Categoría"
    )
    monto = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Monto (CLP)"
    )
    fecha = models.DateField(default=timezone.localdate, verbose_name="Fecha del gasto")
    registrado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Registrado por"
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Gasto"
        verbose_name_plural = "Gastos"
        ordering = ['-fecha', '-fecha_registro']

    def __str__(self):
        return f"{self.concepto} - ${self.monto} ({self.fecha:%d/%m/%Y})"
