from django.urls import path
from . import views

app_name = 'panel'

urlpatterns = [
    # Dashboard y zona del socio
    path('', views.inicio_panel, name='inicio'),
    path('mi-zona/', views.zona_socio, name='zona_socio'),
    path('mi-zona/perfil/', views.mi_perfil, name='mi_perfil'),

    # Planes
    path('planes/', views.lista_planes, name='lista_planes'),
    path('planes/nuevo/', views.crear_plan, name='crear_plan'),
    path('planes/<int:pk>/editar/', views.editar_plan, name='editar_plan'),
    path('planes/<int:pk>/alternar/', views.alternar_plan, name='alternar_plan'),

    # Socios
    path('socios/', views.lista_socios, name='lista_socios'),
    path('socios/nuevo/', views.enrolar_socio, name='enrolar_socio'),
    path('socios/<int:pk>/', views.detalle_socio, name='detalle_socio'),
    path('socios/<int:pk>/editar/', views.editar_socio, name='editar_socio'),
    path('socios/<int:pk>/baja/', views.baja_socio, name='baja_socio'),
    path('socios/<int:pk>/reactivar/', views.reactivar_socio, name='reactivar_socio'),
    path('socios/<int:pk>/regenerar-qr/', views.regenerar_qr, name='regenerar_qr'),
    path('socios/<int:pk>/restablecer-clave/', views.restablecer_clave_socio, name='restablecer_clave_socio'),

    # Pagos y caja
    path('pagos/', views.lista_pagos, name='lista_pagos'),
    path('pagos/nuevo/', views.registrar_pago, name='registrar_pago'),
    path('pagos/exportar/', views.exportar_pagos, name='exportar_pagos'),
    path('pagos/<int:pk>/anular/', views.anular_pago, name='anular_pago'),

    # Cobranza
    path('cobranza/', views.lista_cobranza, name='cobranza'),
    path('cobranza/<int:pk>/recordatorio/', views.enviar_recordatorio, name='enviar_recordatorio'),

    # Personal
    path('usuarios/', views.lista_usuarios, name='lista_usuarios'),
    path('usuarios/nuevo/', views.crear_usuario_personal, name='crear_usuario_personal'),
    path('usuarios/<int:pk>/editar/', views.editar_usuario, name='editar_usuario'),
    path('usuarios/<int:pk>/alternar/', views.alternar_usuario, name='alternar_usuario'),
    path('usuarios/<int:pk>/restablecer-clave/', views.restablecer_clave_usuario, name='restablecer_clave_usuario'),
]
