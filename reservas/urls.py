from django.urls import path
from . import views

app_name = 'reservas'

urlpatterns = [
    # Público y visitantes
    path('', views.horario_publico, name='horario'),
    path('visitantes/', views.visitante_acceso, name='visitante_acceso'),
    path('visitantes/verificar/', views.visitante_verificar, name='visitante_verificar'),
    path('reservar/<int:pk>/', views.visitante_reservar_clase, name='visitante_reservar'),
    path('arriendo/', views.visitante_arrendar, name='visitante_arrendar'),
    path('mi-reserva/', views.visitante_consulta, name='visitante_consulta'),

    # Socio
    path('mis-clases/', views.mis_clases, name='mis_clases'),
    path('mis-clases/inscribirse/<int:pk>/', views.socio_inscribirse, name='socio_inscribirse'),
    path('mis-clases/cancelar/<int:pk>/', views.socio_cancelar, name='socio_cancelar'),

    # Recepción
    path('ocupacion/', views.ocupacion, name='ocupacion'),
    path('sesion/<int:pk>/', views.sesion_detalle, name='sesion_detalle'),
    path('sesion/<int:pk>/inscribir-socio/', views.staff_inscribir_socio, name='staff_inscribir_socio'),
    path('sesion/<int:pk>/inscribir-visitante/', views.staff_inscribir_visitante, name='staff_inscribir_visitante'),
    path('qr/<str:tipo>/<int:pk>/', views.qr_visita, name='qr_visita'),
    path('visitante-estado/', views.visitante_estado, name='visitante_estado'),
    path('inscripcion/<int:pk>/cancelar/', views.staff_cancelar_inscripcion, name='staff_cancelar_inscripcion'),
    path('inscripcion/<int:pk>/cobrar/', views.staff_cobrar_inscripcion, name='staff_cobrar_inscripcion'),
    path('salas/reservas/', views.salas_reservas, name='salas_reservas'),
    path('salas/reservar/', views.reservar_sala_staff, name='reservar_sala'),
    path('salas/reservas/<int:pk>/aprobar/', views.aprobar_reserva, name='aprobar_reserva'),
    path('salas/reservas/<int:pk>/rechazar/', views.rechazar_reserva, name='rechazar_reserva'),
    path('salas/reservas/<int:pk>/cancelar/', views.cancelar_reserva, name='cancelar_reserva'),
    path('salas/reservas/<int:pk>/cobrar/', views.cobrar_reserva, name='cobrar_reserva'),

    # Instructor
    path('agenda/', views.agenda, name='agenda'),
    path('agenda/<int:pk>/', views.sesion_instructor, name='sesion_instructor'),
    path('agenda/inscripcion/<int:pk>/marcar/', views.instructor_marcar, name='instructor_marcar'),
    path('agenda/<int:pk>/cerrar/', views.instructor_cerrar, name='instructor_cerrar'),
    path('agenda/<int:pk>/pedir-cambio/', views.instructor_pedir_cambio, name='instructor_pedir_cambio'),

    # Administración
    path('salas/', views.lista_salas, name='lista_salas'),
    path('salas/nueva/', views.crear_sala, name='crear_sala'),
    path('salas/<int:pk>/editar/', views.editar_sala, name='editar_sala'),
    path('administrar/clases/', views.lista_clases, name='lista_clases'),
    path('administrar/clases/nueva/', views.crear_clase, name='crear_clase'),
    path('administrar/clases/<int:pk>/editar/', views.editar_clase, name='editar_clase'),
    path('administrar/clases/<int:pk>/sesiones/', views.clase_sesiones, name='clase_sesiones'),
    path('administrar/clases/<int:pk>/alternar/', views.alternar_clase, name='alternar_clase'),
    path('sesion/<int:pk>/cancelar/', views.cancelar_sesion, name='cancelar_sesion'),
    path('sesion/<int:pk>/suplente/', views.sesion_suplente, name='sesion_suplente'),
    path('administrar/bloqueos/', views.lista_bloqueos, name='lista_bloqueos'),
    path('administrar/bloqueos/nuevo/', views.crear_bloqueo, name='crear_bloqueo'),
    path('administrar/bloqueos/<int:pk>/eliminar/', views.eliminar_bloqueo, name='eliminar_bloqueo'),
    path('administrar/tarifas/', views.editar_tarifas, name='editar_tarifas'),
    path('administrar/cambios/', views.solicitudes_cambio, name='solicitudes_cambio'),
    path('administrar/cambios/<int:pk>/resolver/', views.resolver_cambio, name='resolver_cambio'),
    path('administrar/informe/', views.informe, name='informe'),
]
