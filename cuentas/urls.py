from django.urls import path
from . import views

app_name = 'cuentas'

urlpatterns = [
    path('login/', views.vista_login, name='login'),
    path('logout/', views.vista_logout, name='logout'),
    path('cambiar-clave/', views.vista_cambiar_clave, name='cambiar_clave'),
]
