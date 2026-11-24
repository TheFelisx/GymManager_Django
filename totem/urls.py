from django.urls import path
from . import views

app_name = 'totem'

urlpatterns = [
    path('', views.inicio_totem, name='inicio'),
    path('validar/', views.validar, name='validar'),
]
