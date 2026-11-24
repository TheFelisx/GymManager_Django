import os
import uuid
from io import BytesIO
from datetime import datetime, date, timedelta
from PIL import Image, ImageOps
import qrcode

from django.db import models
from django.core.files.base import ContentFile
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

from cuentas.models import Usuario
from cuentas.validators import (
    limpiar_rut,
    formatear_rut,
    validador_rut_django,
    validador_edad_minima_django,
    validador_telefono_django,
)

DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def ruta_foto_socio(instance, filename):
    return f"socios/fotos/{limpiar_rut(instance.rut)}.jpg"


def ruta_qr_socio(instance, filename):
    return f"socios/qr/{limpiar_rut(instance.rut)}.png"


class Plan(models.Model):
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre del plan")
    precio = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Precio (CLP)"
    )
    duracion_dias = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(3650)],
        verbose_name="Duración (en días)"
    )
    hora_inicio = models.TimeField(default="00:00", verbose_name="Hora de inicio")
    hora_fin = models.TimeField(default="23:59", verbose_name="Hora de término")
    dias_permitidos = models.CharField(
        max_length=20,
        default="0,1,2,3,4,5,6",
        verbose_name="Días permitidos (0=Lun .. 6=Dom)"
    )
    clases_por_semana = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Clases por semana",
        help_text="Déjalo vacío para clases ilimitadas; 0 si el plan no incluye clases."
    )
    activo = models.BooleanField(default=True, verbose_name="Plan activo")

    class Meta:
        verbose_name = "Plan"
        verbose_name_plural = "Planes"
        ordering = ['precio']

    def __str__(self):
        return f"{self.nombre} (${self.precio:,})".replace(",", ".")

    @property
    def resumen_clases(self) -> str:
        if self.clases_por_semana is None:
            return "Clases ilimitadas"
        if self.clases_por_semana == 0:
            return "Sin clases incluidas"
        return f"{self.clases_por_semana} clase{'s' if self.clases_por_semana != 1 else ''} por semana"

    # --- LÓGICA MIGRADA DE TU ARCHIVO horarios.py ---
    def _lista_dias(self):
        partes = (self.dias_permitidos or "").split(",")
        return sorted([int(p.strip()) for p in partes if p.strip().isdigit()])

    @property
    def formato_dias(self) -> str:
        indices = self._lista_dias()
        if len(indices) == 7:
            return "Todos los días"
        if len(indices) > 2:
            primero, ultimo = indices[0], indices[-1]
            if indices == list(range(primero, ultimo + 1)):
                return f"{DIAS_SEMANA[primero]}–{DIAS_SEMANA[ultimo]}"
        return ", ".join(DIAS_SEMANA[i] for i in indices if 0 <= i <= 6)

    @property
    def resumen_horario(self) -> str:
        h_ini = self.hora_inicio.strftime("%H:%M")
        h_fin = self.hora_fin.strftime("%H:%M")
        texto_horas = "Todo el día" if (h_ini == "00:00" and h_fin == "23:59") else f"{h_ini}–{h_fin}"
        return f"{texto_horas} · {self.formato_dias}"

    def dentro_de_horario(self, ahora=None):
        if ahora is None:
            ahora = timezone.localtime()
        dia_actual = ahora.weekday()
        if dia_actual not in self._lista_dias():
            return False, f"Su plan no incluye el día {DIAS_SEMANA[dia_actual]}"

        hora_actual = ahora.time()
        if not (self.hora_inicio <= hora_actual <= self.hora_fin):
            return False, f"Fuera del horario de su plan ({self.hora_inicio:%H:%M}–{self.hora_fin:%H:%M})"

        return True, ""


class Socio(models.Model):
    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        related_name="perfil_socio",
        verbose_name="Cuenta de usuario"
    )
    rut = models.CharField(
        max_length=12,
        unique=True,
        validators=[validador_rut_django],
        verbose_name="RUT"
    )
    fecha_nacimiento = models.DateField(
        validators=[validador_edad_minima_django],
        verbose_name="Fecha de nacimiento"
    )
    telefono = models.CharField(
        max_length=15,
        validators=[validador_telefono_django],
        verbose_name="Teléfono"
    )
    foto = models.ImageField(
        upload_to=ruta_foto_socio,
        blank=True,
        null=True,
        verbose_name="Foto de perfil"
    )
    token_qr = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name="Token único de acceso QR"
    )
    imagen_qr = models.ImageField(
        upload_to=ruta_qr_socio,
        blank=True,
        null=True,
        editable=False,
        verbose_name="Código QR"
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)
    fecha_baja = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Fecha de baja")
    motivo_baja = models.CharField(max_length=200, blank=True, editable=False, verbose_name="Motivo de la baja")

    class Meta:
        verbose_name = "Socio"
        verbose_name_plural = "Socios"
        ordering = ['-fecha_registro']

    def __str__(self):
        return f"{self.usuario.get_full_name() or self.usuario.username} ({self.rut_formateado})"

    @property
    def rut_formateado(self):
        return formatear_rut(self.rut)

    @property
    def de_baja(self) -> bool:
        return not self.usuario.is_active

    @property
    def ultimo_pago_vigente(self):
        hoy = timezone.localdate()
        return self.pagos.filter(
            anulado=False, fecha_inicio__lte=hoy, fecha_vencimiento__gte=hoy
        ).order_by('-fecha_vencimiento').first()

    @property
    def vencimiento_actual(self):
        """Fecha hasta la que está cubierto (último pago no anulado), o None."""
        return self.pagos.filter(anulado=False).aggregate(m=models.Max('fecha_vencimiento'))['m']

    @property
    def dias_para_vencer(self):
        """Días que faltan para que venza su membresía (None si nunca pagó)."""
        venc = self.vencimiento_actual
        if venc is None:
            return None
        return (venc - timezone.localdate()).days

    def fecha_inicio_renovacion(self):
        """Un pago renueva desde el mayor entre el vencimiento actual y hoy."""
        hoy = timezone.localdate()
        venc = self.vencimiento_actual
        if venc is not None and venc > hoy:
            return venc
        return hoy

    def dar_de_baja(self, motivo: str):
        """Desactiva al socio y su cuenta. Nunca se borra."""
        self.usuario.is_active = False
        self.usuario.save(update_fields=['is_active'])
        self.fecha_baja = timezone.now()
        self.motivo_baja = motivo.strip()[:200]
        self.save(update_fields=['fecha_baja', 'motivo_baja'])

    def reactivar(self):
        """Reactiva al socio y su cuenta juntos."""
        self.usuario.is_active = True
        self.usuario.save(update_fields=['is_active'])
        self.fecha_baja = None
        self.motivo_baja = ""
        self.save(update_fields=['fecha_baja', 'motivo_baja'])

    def regenerar_qr(self):
        """Crea un código nuevo: el anterior deja de servir."""
        self.token_qr = uuid.uuid4()
        if self.imagen_qr:
            self.imagen_qr.delete(save=False)
        self.generar_qr()
        self.save(update_fields=['token_qr', 'imagen_qr'])

    @property
    def esta_vigente(self) -> bool:
        return self.ultimo_pago_vigente is not None

    def generar_qr(self):
        """Genera la imagen PNG del código QR usando el token único del socio."""
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(str(self.token_qr))
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        nombre_archivo = f"{limpiar_rut(self.rut)}.png"
        self.imagen_qr.save(nombre_archivo, ContentFile(buffer.getvalue()), save=False)

    def _procesar_foto(self):
        """Aplica tu lógica de fotos.py: rota EXIF, convierte a RGB, reduce a 600x600 y guarda JPEG."""
        if not self.foto:
            return
        img = Image.open(self.foto)
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((600, 600))

        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=88)
        nombre_archivo = f"{limpiar_rut(self.rut)}.jpg"

        # Borra la foto anterior para no acumular archivos con sufijos raros.
        if self.pk:
            anterior = Socio.objects.filter(pk=self.pk).values_list('foto', flat=True).first()
            if anterior:
                self.foto.storage.delete(anterior)
        self.foto.save(nombre_archivo, ContentFile(buffer.getvalue()), save=False)

    def save(self, *args, **kwargs):
        self.rut = limpiar_rut(self.rut)
        if not self.imagen_qr:
            self.generar_qr()
        # Solo se procesa una foto recién subida (aún no guardada en disco).
        if self.foto and not getattr(self.foto, '_committed', True):
            self._procesar_foto()
        super().save(*args, **kwargs)


class Pago(models.Model):
    class MetodoPago(models.TextChoices):
        EFECTIVO = 'EFECTIVO', 'Efectivo'
        DEBITO = 'DEBITO', 'Tarjeta de Débito'
        CREDITO = 'CREDITO', 'Tarjeta de Crédito'
        TRANSFERENCIA = 'TRANSFERENCIA', 'Transferencia Bancaria'

    socio = models.ForeignKey(
        Socio,
        on_delete=models.PROTECT,
        related_name="pagos",
        verbose_name="Socio"
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="pagos",
        verbose_name="Plan contratado"
    )
    monto_pagado = models.PositiveIntegerField(verbose_name="Monto pagado (CLP)")
    metodo_pago = models.CharField(
        max_length=20,
        choices=MetodoPago.choices,
        default=MetodoPago.DEBITO,
        verbose_name="Método de pago"
    )
    fecha_pago = models.DateTimeField(default=timezone.now, verbose_name="Fecha y hora de pago")
    fecha_inicio = models.DateField(default=timezone.localdate, verbose_name="Inicio de vigencia")
    fecha_vencimiento = models.DateField(blank=True, verbose_name="Fin de vigencia")
    registrado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Registrado por"
    )
    descuento = models.PositiveIntegerField(default=0, verbose_name="Descuento (CLP)")
    descuento_autorizado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="descuentos_autorizados",
        verbose_name="Descuento autorizado por"
    )
    anulado = models.BooleanField(default=False, verbose_name="Pago anulado")
    motivo_anulacion = models.CharField(max_length=200, blank=True, verbose_name="Motivo de la anulación")
    anulado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_anulados",
        verbose_name="Anulado por"
    )
    fecha_anulacion = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de anulación")

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ['-fecha_pago']

    def __str__(self):
        return f"Pago #{self.id} - {self.socio.rut_formateado} ({self.plan.nombre})"

    def anular(self, motivo: str, usuario):
        """Los pagos no se editan ni se borran: se anulan con motivo."""
        self.anulado = True
        self.motivo_anulacion = motivo.strip()[:200]
        self.anulado_por = usuario
        self.fecha_anulacion = timezone.now()
        self.save(update_fields=['anulado', 'motivo_anulacion', 'anulado_por', 'fecha_anulacion'])

    def save(self, *args, **kwargs):
        if not self.monto_pagado and self.plan:
            self.monto_pagado = max(self.plan.precio - (self.descuento or 0), 1)
        if not self.fecha_vencimiento and self.plan:
            self.fecha_vencimiento = self.fecha_inicio + timedelta(days=self.plan.duracion_dias)
        super().save(*args, **kwargs)
