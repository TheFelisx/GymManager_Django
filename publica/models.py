from django.db import models


class Entrenador(models.Model):
    nombre = models.CharField(max_length=100, verbose_name="Nombre")
    especialidad = models.CharField(max_length=120, verbose_name="Especialidad")
    foto = models.ImageField(upload_to="entrenadores/", blank=True, null=True, verbose_name="Foto")
    orden = models.PositiveSmallIntegerField(default=0, verbose_name="Orden")
    activo = models.BooleanField(default=True, verbose_name="Visible en la página")

    class Meta:
        verbose_name = "Entrenador"
        verbose_name_plural = "Entrenadores"
        ordering = ['orden', 'nombre']

    def __str__(self):
        return f"{self.nombre} ({self.especialidad})"


class PreguntaFrecuente(models.Model):
    pregunta = models.CharField(max_length=200, verbose_name="Pregunta")
    respuesta = models.TextField(verbose_name="Respuesta")
    orden = models.PositiveSmallIntegerField(default=0, verbose_name="Orden")
    activa = models.BooleanField(default=True, verbose_name="Visible en la página")

    class Meta:
        verbose_name = "Pregunta frecuente"
        verbose_name_plural = "Preguntas frecuentes"
        ordering = ['orden', 'id']

    def __str__(self):
        return self.pregunta


class MensajeContacto(models.Model):
    nombre = models.CharField(max_length=100)
    email = models.EmailField()
    telefono = models.CharField(max_length=20, blank=True)
    mensaje = models.TextField(max_length=1500)
    fecha = models.DateTimeField(auto_now_add=True)
    atendido = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Mensaje de contacto"
        verbose_name_plural = "Mensajes de contacto"
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.nombre} ({self.fecha:%d/%m/%Y %H:%M})"
