from django.urls import path
from . import views

app_name = 'publica'

urlpatterns = [
    path('', views.inicio_publico, name='inicio'),
    path('contacto/enviar/', views.enviar_contacto, name='enviar_contacto'),
]
