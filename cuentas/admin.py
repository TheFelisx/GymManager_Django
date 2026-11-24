from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, RegistroAuditoria

@admin.register(Usuario)
class CustomUsuarioAdmin(UserAdmin):
    list_display = ('username', 'first_name', 'last_name', 'rol', 'is_active', 'debe_cambiar_clave', 'creado_por')
    list_filter = ('rol', 'is_active', 'debe_cambiar_clave')
    fieldsets = UserAdmin.fieldsets + (
        ('Información de GymManager Pro', {
            'fields': ('rol', 'creado_por', 'debe_cambiar_clave')
        }),
    )

@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    list_display = ('fecha_hora', 'usuario', 'accion', 'detalle')
    list_filter = ('accion', 'fecha_hora')
    search_fields = ('usuario__username', 'accion', 'detalle')
    readonly_fields = ('usuario', 'accion', 'detalle', 'fecha_hora')
