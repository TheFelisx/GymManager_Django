import re
from datetime import date
from django.core.exceptions import ValidationError

EDAD_MINIMA = 14

def limpiar_rut(rut: str) -> str:
    return re.sub(r"[^0-9kK]", "", rut or "").upper()

def validar_rut(rut: str) -> bool:
    r = limpiar_rut(rut)
    if len(r) < 2 or not r[:-1].isdigit():
        return False
    cuerpo, dv = r[:-1], r[-1]
    suma, mult = 0, 2
    for d in reversed(cuerpo):
        suma += int(d) * mult
        mult = 2 if mult == 7 else mult + 1
    esperado = 11 - (suma % 11)
    esperado = "0" if esperado == 11 else "K" if esperado == 10 else str(esperado)
    return dv == esperado

def formatear_rut(rut: str) -> str:
    rut_limpio = limpiar_rut(rut)
    if len(rut_limpio) < 2:
        return rut_limpio
    cuerpo_plano = rut_limpio[:-1]
    digito_verificador = rut_limpio[-1]
    cuerpo_numerico = int(cuerpo_plano)
    cuerpo_con_puntos = f"{cuerpo_numerico:,}".replace(",", ".")
    return f"{cuerpo_con_puntos}-{digito_verificador}"

def calcular_edad(fecha_nacimiento: date, fecha_actual: date | None = None) -> int:
    if fecha_actual is None:
        fecha_actual = date.today()
    edad_preliminar = fecha_actual.year - fecha_nacimiento.year
    todavia_no_cumple = (fecha_actual.month, fecha_actual.day) < (fecha_nacimiento.month, fecha_nacimiento.day)
    return edad_preliminar - 1 if todavia_no_cumple else edad_preliminar

def validar_telefono(tel: str) -> bool:
    telefono_limpio = (tel or "").replace(" ", "")
    return re.fullmatch(r"\+?\d{8,12}", telefono_limpio) is not None

def validador_rut_django(valor: str):
    if not validar_rut(valor):
        raise ValidationError("El RUT ingresado no es válido (verifique dígito verificador).")

def validador_edad_minima_django(fecha_nacimiento: date):
    if fecha_nacimiento > date.today():
        raise ValidationError("La fecha de nacimiento no puede ser futura.")
    if calcular_edad(fecha_nacimiento) < EDAD_MINIMA:
        raise ValidationError(f"El usuario debe tener al menos {EDAD_MINIMA} años.")

def validador_telefono_django(valor: str):
    if not validar_telefono(valor):
        raise ValidationError("Teléfono inválido. Debe contener entre 8 y 12 dígitos.")
