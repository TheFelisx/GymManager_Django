from django.contrib import admin
from .models import Plan, Socio, Pago


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'precio', 'duracion_dias', 'resumen_horario', 'activo')
    list_filter = ('activo',)
    search_fields = ('nombre',)

    def has_delete_permission(self, request, obj=None):
        return False   # los planes nunca se borran: se desactivan


@admin.register(Socio)
class SocioAdmin(admin.ModelAdmin):
    list_display = ('rut_formateado', 'usuario', 'telefono', 'esta_vigente', 'fecha_registro')
    search_fields = ('rut', 'usuario__first_name', 'usuario__last_name', 'usuario__email')
    readonly_fields = ('token_qr', 'imagen_qr', 'fecha_baja', 'motivo_baja')

    def has_delete_permission(self, request, obj=None):
        return False   # los socios nunca se borran: se dan de baja


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ('id', 'socio', 'plan', 'monto_pagado', 'metodo_pago', 'fecha_inicio', 'fecha_vencimiento', 'anulado', 'registrado_por')
    list_filter = ('metodo_pago', 'plan', 'anulado', 'fecha_pago')
    search_fields = ('socio__rut', 'socio__usuario__first_name', 'socio__usuario__last_name')

    # Los pagos no se editan ni se borran: se anulan con motivo desde el panel.
    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
