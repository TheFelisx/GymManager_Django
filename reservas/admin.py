from django.contrib import admin
from .models import (
    BloqueoFecha, Clase, Inscripcion, ReservaSala, Sala, Sesion, SolicitudCambio, Tarifa, Visitante,
)


@admin.register(Sala)
class SalaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'capacidad', 'precio_hora', 'activa')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Clase)
class ClaseAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'sala', 'instructor', 'cupo', 'activa')
    list_filter = ('activa', 'sala')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Sesion)
class SesionAdmin(admin.ModelAdmin):
    list_display = ('clase', 'fecha', 'hora_inicio', 'estado', 'cerrada')
    list_filter = ('estado', 'cerrada', 'clase')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Inscripcion)
class InscripcionAdmin(admin.ModelAdmin):
    list_display = ('id', 'sesion', 'socio', 'visitante', 'estado', 'monto', 'monto_pagado')
    list_filter = ('estado',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReservaSala)
class ReservaSalaAdmin(admin.ModelAdmin):
    list_display = ('sala', 'fecha', 'hora_inicio', 'hora_fin', 'estado', 'origen', 'precio', 'monto_pagado')
    list_filter = ('estado', 'origen')

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Visitante)
admin.site.register(BloqueoFecha)
admin.site.register(Tarifa)
admin.site.register(SolicitudCambio)
