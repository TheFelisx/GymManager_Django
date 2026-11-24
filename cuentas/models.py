from django.db import models

# Create your models here.
from django.contrib.auth.models import AbstractUser, UserManager


class UsuarioManager(UserManager):
    """El comando createsuperuser crea al MASTER (dueño del sistema)."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('rol', 'MASTER')
        extra_fields.setdefault('debe_cambiar_clave', False)
        return super().create_superuser(username, email, password, **extra_fields)


class Usuario(AbstractUser):
    class Rol(models.TextChoices):
        MASTER = 'MASTER', 'Master'
        ADMIN = 'ADMIN', 'Administrador'
        RECEPCIONISTA = 'RECEPCIONISTA', 'Recepcionista'
        GUARDIA = 'GUARDIA', 'Guardia'
        INSTRUCTOR = 'INSTRUCTOR', 'Instructor'
        SOCIO = 'SOCIO', 'Socio'

    rol = models.CharField(
        max_length=20,
        choices=Rol.choices,
        default=Rol.SOCIO,
        verbose_name='Rol en el sistema'
    )
    creado_por = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='usuarios_creados',
        verbose_name='Creado por'
    )
    debe_cambiar_clave = models.BooleanField(
        default=True,
        verbose_name='Debe cambiar clave'
    )

    objects = UsuarioManager()

    class Meta:
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'

    @property
    def es_master(self):
        return self.is_superuser or self.rol == self.Rol.MASTER

    @property
    def es_admin(self):
        return self.rol == self.Rol.ADMIN

    @property
    def es_personal(self):
        """Master, administrador o recepcionista (acceden al panel)."""
        return self.es_master or self.rol in (self.Rol.ADMIN, self.Rol.RECEPCIONISTA)

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"


class RegistroAuditoria(models.Model):
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='Quién lo hizo'
    )
    accion = models.CharField(max_length=100, verbose_name='Qué hizo')
    detalle = models.TextField(verbose_name='Sobre qué (detalle)')
    fecha_hora = models.DateTimeField(auto_now_add=True, verbose_name='Cuándo')

    class Meta:
        verbose_name = 'Registro de auditoría'
        verbose_name_plural = 'Registros de auditoría'
        ordering = ['-fecha_hora']

    def __str__(self):
        actor = self.usuario.username if self.usuario else 'Sistema'
        return f"[{self.fecha_hora:%Y-%m-%d %H:%M}] {actor}: {self.accion}"
