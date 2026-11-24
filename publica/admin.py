from django.contrib import admin
from .models import Entrenador, PreguntaFrecuente, MensajeContacto


@admin.register(Entrenador)
class EntrenadorAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'especialidad', 'orden', 'activo')
    list_editable = ('orden', 'activo')


@admin.register(PreguntaFrecuente)
class PreguntaFrecuenteAdmin(admin.ModelAdmin):
    list_display = ('pregunta', 'orden', 'activa')
    list_editable = ('orden', 'activa')


@admin.register(MensajeContacto)
class MensajeContactoAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'nombre', 'email', 'telefono', 'atendido')
    list_filter = ('atendido',)
    search_fields = ('nombre', 'email', 'mensaje')
    readonly_fields = ('nombre', 'email', 'telefono', 'mensaje', 'fecha')
