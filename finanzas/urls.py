from django.urls import path
from . import views

app_name = 'finanzas'

urlpatterns = [
    path('', views.inicio_finanzas, name='inicio'),
    path('gastos/nuevo/', views.registrar_gasto, name='registrar_gasto'),
]
