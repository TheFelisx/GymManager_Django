from django.contrib import admin
from .models import RegistroAcceso

@admin.register(RegistroAcceso)
class RegistroAccesoAdmin(admin.ModelAdmin):
    list_display = ('fecha_hora', 'permitido', 'identificador_ingresado', 'socio', 'metodo', 'motivo', 'validado_por')
    list_filter = ('permitido', 'metodo', 'fecha_hora')
    search_fields = ('identificador_ingresado', 'socio__usuario__first_name', 'socio__usuario__last_name')
