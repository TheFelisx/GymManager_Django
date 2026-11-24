# GymManager Pro (Django)

Apps: `publica`, `cuentas`, `panel`, `totem`, `finanzas`, `reservas` (clases, salas, visitantes).

## Puesta en marcha
```
pip install -r requirements.txt
copy .env.example .env        # y ajusta tus datos
python manage.py migrate
python manage.py createsuperuser      # se crea como MASTER
python manage.py cargar_datos_ejemplo # opcional: un usuario por rol
python manage.py check
python manage.py test
python manage.py generar_sesiones     # crea las sesiones de las próximas 4 semanas (úsalo a diario)
python manage.py runserver
```
## Notas
- La cámara del tótem exige **HTTPS** (en producción `DEBUG=False` lo activa).
- El límite de intentos usa la caché local; con varios procesos, configura una caché compartida.
- Las claves temporales son aleatorias y se muestran una sola vez.
- Las sesiones de clases se generan solas (4 semanas hacia adelante); `generar_sesiones` también cancela reservas cuyo plan venció y libera reservas de visitantes sin pagar en 24 horas.
- El visitante verifica su correo con un código de 6 dígitos (se imprime en la consola mientras `EMAIL_BACKEND` sea el de consola).
- Los pagos en línea no están implementados: el cobro de visitantes se registra en recepción.
