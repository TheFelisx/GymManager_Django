import datetime
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Count, Q
from django.utils import timezone

from cuentas.validators import formatear_rut
from panel.models import DIAS_SEMANA, Pago, Socio

Usuario = settings.AUTH_USER_MODEL


def combinar(fecha, hora):
    """Fecha + hora local (Chile) como datetime con zona horaria."""
    return timezone.make_aware(datetime.datetime.combine(fecha, hora))


# =====================================================================
# Tarifas y bloqueos
# =====================================================================
class Tarifa(models.Model):
    """Configuración única de precios y reglas de visitantes (siempre existe un solo registro)."""
    precio_clase_suelta = models.PositiveIntegerField(default=5000, validators=[MaxValueValidator(1000000)], verbose_name="Precio de la clase suelta (CLP)")
    prueba_gratis = models.BooleanField(default=True, verbose_name="Primera clase de prueba gratis (una por persona)")
    porcentaje_externos = models.PositiveSmallIntegerField(default=20, validators=[MaxValueValidator(100)], verbose_name="% de cupo reservado a externos")
    punta_inicio = models.TimeField(default=datetime.time(18, 0), verbose_name="Inicio de hora punta")
    punta_fin = models.TimeField(default=datetime.time(21, 0), verbose_name="Fin de hora punta")

    class Meta:
        verbose_name = "Tarifa"
        verbose_name_plural = "Tarifas"

    def __str__(self):
        return "Tarifas y reglas de visitantes"

    @classmethod
    def obtener(cls):
        tarifa, _ = cls.objects.get_or_create(pk=1)
        return tarifa


class BloqueoFecha(models.Model):
    """Feriados o cierres: en estas fechas no se dan clases ni se arriendan salas."""
    sala = models.ForeignKey('Sala', on_delete=models.CASCADE, null=True, blank=True, related_name='bloqueos',
                             verbose_name="Sala (vacío = todas)")
    fecha_desde = models.DateField(verbose_name="Desde")
    fecha_hasta = models.DateField(verbose_name="Hasta")
    motivo = models.CharField(max_length=150, verbose_name="Motivo")

    class Meta:
        verbose_name = "Bloqueo de fechas"
        verbose_name_plural = "Bloqueos de fechas"
        ordering = ['-fecha_desde']

    def __str__(self):
        return f"{self.motivo} ({self.fecha_desde:%d/%m/%Y} – {self.fecha_hasta:%d/%m/%Y})"


# =====================================================================
# Salas y clases
# =====================================================================
class Sala(models.Model):
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre")
    capacidad = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(500)], verbose_name="Capacidad máxima")
    descripcion = models.TextField(blank=True, verbose_name="Descripción")
    foto = models.ImageField(upload_to="salas/", blank=True, null=True, verbose_name="Foto")
    precio_hora = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10000000)], verbose_name="Cuánto cuesta por hora (CLP)",
        help_text="Lo que se cobra por cada hora de arriendo de la sala. Al reservar, el sistema calcula el total según las horas.")
    precio_hora_punta = models.PositiveIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(10000000)], verbose_name="Cuánto cuesta por hora en hora punta (CLP)",
        help_text="Opcional. Vacío = mismo valor que el normal.")
    activa = models.BooleanField(default=True, verbose_name="Sala activa")

    class Meta:
        verbose_name = "Sala"
        verbose_name_plural = "Salas"
        ordering = ['nombre']

    def __str__(self):
        return f"{self.nombre} (cap. {self.capacidad})"


class Clase(models.Model):
    class Nivel(models.TextChoices):
        TODOS = 'TODOS', 'Todos los niveles'
        BASICO = 'BASICO', 'Básico'
        INTERMEDIO = 'INTERMEDIO', 'Intermedio'
        AVANZADO = 'AVANZADO', 'Avanzado'

    nombre = models.CharField(max_length=100, verbose_name="Nombre")
    descripcion = models.TextField(blank=True, verbose_name="Descripción")
    nivel = models.CharField(max_length=12, choices=Nivel.choices, default=Nivel.TODOS, verbose_name="Nivel")
    duracion_min = models.PositiveSmallIntegerField(default=60, validators=[MinValueValidator(15), MaxValueValidator(240)], verbose_name="Duración (minutos)")
    instructor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='clases_a_cargo', verbose_name="Instructor")
    sala = models.ForeignKey(Sala, on_delete=models.PROTECT, related_name='clases', verbose_name="Sala")
    cupo = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(500)], verbose_name="Cupo")
    dias_semana = models.CharField(max_length=20, verbose_name="Días (0=Lun .. 6=Dom)")
    hora_inicio = models.TimeField(verbose_name="Hora de inicio")
    activa = models.BooleanField(default=True, verbose_name="Clase activa")

    class Meta:
        verbose_name = "Clase"
        verbose_name_plural = "Clases"
        ordering = ['nombre', 'hora_inicio']

    def __str__(self):
        return f"{self.nombre} · {self.resumen_horario}"

    @property
    def lista_dias(self):
        return sorted(int(p) for p in (self.dias_semana or "").split(",") if p.strip().isdigit())

    @property
    def nombres_dias(self):
        return ", ".join(DIAS_SEMANA[i] for i in self.lista_dias if 0 <= i <= 6)

    @property
    def hora_fin(self):
        inicio = datetime.datetime.combine(datetime.date.today(), self.hora_inicio)
        return (inicio + datetime.timedelta(minutes=self.duracion_min)).time()

    @property
    def resumen_horario(self):
        return f"{self.nombres_dias} {self.hora_inicio:%H:%M}–{self.hora_fin:%H:%M}"

    @property
    def cupo_efectivo(self):
        """El cupo nunca supera la capacidad de la sala."""
        return min(self.cupo, self.sala.capacidad)


class Sesion(models.Model):
    """Cada vez que se da una clase («Yoga del lunes 23 de noviembre»)."""
    class Estado(models.TextChoices):
        NORMAL = 'NORMAL', 'Normal'
        CANCELADA = 'CANCELADA', 'Cancelada'

    clase = models.ForeignKey(Clase, on_delete=models.PROTECT, related_name='sesiones')
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.NORMAL)
    motivo_cancelacion = models.CharField(max_length=200, blank=True)
    instructor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='sesiones_suplente', verbose_name="Instructor suplente")
    cerrada = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Sesión"
        verbose_name_plural = "Sesiones"
        ordering = ['fecha', 'hora_inicio']
        unique_together = [('clase', 'fecha')]

    def __str__(self):
        return f"{self.clase.nombre} {self.fecha:%d/%m/%Y} {self.hora_inicio:%H:%M}"

    # --- tiempo ---
    @property
    def inicio_dt(self):
        return combinar(self.fecha, self.hora_inicio)

    @property
    def fin_dt(self):
        return combinar(self.fecha, self.hora_fin)

    @property
    def instructor_efectivo(self):
        return self.instructor or self.clase.instructor

    @property
    def cancelada(self):
        return self.estado == self.Estado.CANCELADA

    # --- cupos (usan los conteos anotados si existen, para no consultar por cada fila) ---
    def _conteos(self):
        if hasattr(self, 'n_socios'):
            return self.n_socios, self.n_externos, getattr(self, 'n_espera', 0)
        if not hasattr(self, '_cache_conteos'):
            ocupan = [Inscripcion.Estado.CONFIRMADA, Inscripcion.Estado.ASISTIO, Inscripcion.Estado.NO_ASISTIO]
            datos = self.inscripciones.aggregate(
                socios=Count('id', filter=Q(estado__in=ocupan, socio__isnull=False)),
                externos=Count('id', filter=Q(estado__in=ocupan, visitante__isnull=False)),
                espera=Count('id', filter=Q(estado=Inscripcion.Estado.EN_ESPERA)),
            )
            self._cache_conteos = (datos['socios'], datos['externos'], datos['espera'])
        return self._cache_conteos

    @property
    def cupo_total(self):
        return self.clase.cupo_efectivo

    @property
    def externos_reservados(self):
        """Parte del cupo reservada para visitantes (al menos 1)."""
        pct = Tarifa.obtener().porcentaje_externos
        return min(self.cupo_total, max(1, (self.cupo_total * pct) // 100))

    @property
    def ocupados(self):
        socios, externos, _ = self._conteos()
        return socios + externos

    @property
    def en_espera(self):
        return self._conteos()[2]

    @property
    def libres_total(self):
        return max(0, self.cupo_total - self.ocupados)

    @property
    def libres_socio(self):
        """Cupos que pueden tomar los socios: no se tocan los reservados a externos."""
        socios, externos, _ = self._conteos()
        return max(0, self.cupo_total - socios - max(self.externos_reservados, externos))

    @property
    def libres_externo(self):
        return self.libres_total

    def invalidar_cache(self):
        if hasattr(self, '_cache_conteos'):
            del self._cache_conteos


class Visitante(models.Model):
    """Persona externa, sin cuenta: reserva clases sueltas o salas como invitada."""
    nombre = models.CharField(max_length=120)
    rut = models.CharField(max_length=12, unique=True)
    email = models.EmailField()
    email_verificado = models.BooleanField(default=False)
    telefono = models.CharField(max_length=20)
    fecha_nacimiento = models.DateField()
    acepto_terminos = models.BooleanField(default=False)
    acepto_en = models.DateTimeField(null=True, blank=True)
    apoderado_nombre = models.CharField(max_length=120, blank=True)
    apoderado_rut = models.CharField(max_length=12, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Visitante"
        verbose_name_plural = "Visitantes"
        ordering = ['-creado']

    def __str__(self):
        return f"{self.nombre} ({self.rut_formateado})"

    @property
    def rut_formateado(self):
        return formatear_rut(self.rut)

    @property
    def edad(self):
        hoy = timezone.localdate()
        nac = self.fecha_nacimiento
        return hoy.year - nac.year - ((hoy.month, hoy.day) < (nac.month, nac.day))


class Inscripcion(models.Model):
    """Un cupo en una sesión: de un socio o de un visitante."""
    class Estado(models.TextChoices):
        CONFIRMADA = 'CONFIRMADA', 'Confirmada'
        EN_ESPERA = 'EN_ESPERA', 'En lista de espera'
        CANCELADA = 'CANCELADA', 'Cancelada'
        ASISTIO = 'ASISTIO', 'Asistió'
        NO_ASISTIO = 'NO_ASISTIO', 'No asistió'

    sesion = models.ForeignKey(Sesion, on_delete=models.PROTECT, related_name='inscripciones')
    socio = models.ForeignKey(Socio, on_delete=models.PROTECT, null=True, blank=True, related_name='inscripciones')
    visitante = models.ForeignKey(Visitante, on_delete=models.PROTECT, null=True, blank=True, related_name='inscripciones')
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.CONFIRMADA)
    creada = models.DateTimeField(auto_now_add=True)
    en_espera_desde = models.DateTimeField(null=True, blank=True)
    creada_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    marcada_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    marcada_en = models.DateTimeField(null=True, blank=True)
    # Solo visitantes
    codigo = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    es_prueba = models.BooleanField(default=False, verbose_name="Clase de prueba gratis")
    monto = models.PositiveIntegerField(default=0)
    monto_pagado = models.PositiveIntegerField(default=0)
    metodo_pago = models.CharField(max_length=15, choices=Pago.MetodoPago.choices, blank=True)
    fecha_pago = models.DateTimeField(null=True, blank=True)
    cobrado_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reembolsado = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Inscripción"
        verbose_name_plural = "Inscripciones"
        ordering = ['sesion__fecha', 'sesion__hora_inicio', 'id']

    def __str__(self):
        return f"{self.persona_nombre} → {self.sesion} ({self.get_estado_display()})"

    @property
    def persona_nombre(self):
        if self.socio_id:
            return self.socio.usuario.get_full_name()
        return self.visitante.nombre if self.visitante_id else "—"

    @property
    def es_visitante(self):
        return self.visitante_id is not None

    @property
    def pagada(self):
        return self.monto_pagado >= self.monto

    @property
    def ocupa_cupo(self):
        return self.estado in (self.Estado.CONFIRMADA, self.Estado.ASISTIO, self.Estado.NO_ASISTIO)


class ReservaSala(models.Model):
    """Uso de una sala: la hace recepción/administración, o la solicita un visitante."""
    class Estado(models.TextChoices):
        SOLICITADA = 'SOLICITADA', 'Solicitada'
        APROBADA = 'APROBADA', 'Aprobada'
        RECHAZADA = 'RECHAZADA', 'Rechazada'
        CANCELADA = 'CANCELADA', 'Cancelada'

    class Origen(models.TextChoices):
        INTERNA = 'INTERNA', 'Interna (personal)'
        VISITANTE = 'VISITANTE', 'Visitante'

    sala = models.ForeignKey(Sala, on_delete=models.PROTECT, related_name='reservas')
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    motivo = models.CharField(max_length=200)
    personas = models.PositiveSmallIntegerField(default=1)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.APROBADA)
    origen = models.CharField(max_length=10, choices=Origen.choices, default=Origen.INTERNA)
    visitante = models.ForeignKey(Visitante, on_delete=models.PROTECT, null=True, blank=True, related_name='reservas_sala')
    creada_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    creada = models.DateTimeField(auto_now_add=True)
    aprobada_en = models.DateTimeField(null=True, blank=True)
    resuelta_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    nota = models.CharField(max_length=200, blank=True)
    codigo = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    precio = models.PositiveIntegerField(default=0)
    monto_pagado = models.PositiveIntegerField(default=0)
    metodo_pago = models.CharField(max_length=15, choices=Pago.MetodoPago.choices, blank=True)
    fecha_pago = models.DateTimeField(null=True, blank=True)
    cobrado_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reembolsado = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Reserva de sala"
        verbose_name_plural = "Reservas de sala"
        ordering = ['fecha', 'hora_inicio']

    def __str__(self):
        return f"{self.sala.nombre} {self.fecha:%d/%m/%Y} {self.hora_inicio:%H:%M}–{self.hora_fin:%H:%M}"

    @property
    def inicio_dt(self):
        return combinar(self.fecha, self.hora_inicio)

    @property
    def fin_dt(self):
        return combinar(self.fecha, self.hora_fin)

    @property
    def pagada(self):
        return self.monto_pagado >= self.precio

    @property
    def activa(self):
        return self.estado in (self.Estado.SOLICITADA, self.Estado.APROBADA)


class SolicitudCambio(models.Model):
    """El instructor pide cancelar una sesión o que lo reemplacen; la resuelve administración."""
    class Tipo(models.TextChoices):
        CANCELAR = 'CANCELAR', 'Cancelar la sesión'
        SUPLENCIA = 'SUPLENCIA', 'Pedir suplente'

    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        APROBADA = 'APROBADA', 'Aprobada'
        RECHAZADA = 'RECHAZADA', 'Rechazada'

    sesion = models.ForeignKey(Sesion, on_delete=models.CASCADE, related_name='solicitudes')
    solicitante = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='solicitudes_cambio')
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    motivo = models.CharField(max_length=200)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    creada = models.DateTimeField(auto_now_add=True)
    resuelta_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Solicitud de cambio"
        verbose_name_plural = "Solicitudes de cambio"
        ordering = ['-creada']

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.sesion}"
