import datetime

from django import forms
from django.utils import timezone

from cuentas.models import Usuario
from cuentas.validators import limpiar_rut, validar_rut, validar_telefono
from panel.forms import OPCIONES_DIAS, MinimosMixin
from panel.models import Pago
from .models import BloqueoFecha, Clase, ReservaSala, Sala, Tarifa, Visitante

CTRL = {'class': 'form-control'}
SEL = {'class': 'form-select'}


def instructores_activos():
    return Usuario.objects.filter(rol=Usuario.Rol.INSTRUCTOR, is_active=True).order_by('first_name', 'username')


class SalaForm(MinimosMixin, forms.ModelForm):
    MINIMOS = {'capacidad': 1, 'precio_hora': 1}

    class Meta:
        model = Sala
        fields = ['nombre', 'capacidad', 'descripcion', 'foto', 'precio_hora', 'precio_hora_punta', 'activa']
        widgets = {
            'nombre': forms.TextInput(attrs=CTRL),
            'capacidad': forms.NumberInput(attrs={**CTRL, 'min': 1}),
            'descripcion': forms.Textarea(attrs={**CTRL, 'rows': 3}),
            'foto': forms.FileInput(attrs={**CTRL, 'accept': 'image/*'}),
            'precio_hora': forms.NumberInput(attrs={**CTRL, 'min': 1, 'placeholder': 'Ej: 15000'}),
            'precio_hora_punta': forms.NumberInput(attrs={**CTRL, 'min': 0, 'placeholder': 'Opcional'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_capacidad(self):
        valor = self.cleaned_data['capacidad']
        if valor < 1:
            raise forms.ValidationError("La capacidad debe ser al menos 1.")
        return valor

    def clean(self):
        datos = super().clean()
        punta, normal = datos.get('precio_hora_punta'), datos.get('precio_hora')
        if punta is not None and normal is not None and punta < normal:
            self.add_error('precio_hora_punta', "El valor en hora punta no puede ser menor que el normal.")
        # No se puede desactivar una sala que todavía se usa.
        if self.instance.pk and datos.get('activa') is False and self.instance.activa:
            if self.instance.clases.filter(activa=True).exists():
                self.add_error('activa', "Esta sala tiene clases activas. Muévelas o desactívalas primero.")
            elif self.instance.reservas.filter(
                    fecha__gte=timezone.localdate(),
                    estado__in=(ReservaSala.Estado.SOLICITADA, ReservaSala.Estado.APROBADA)).exists():
                self.add_error('activa', "Esta sala tiene reservas próximas. Cancélalas primero.")
        return datos


class ClaseForm(MinimosMixin, forms.ModelForm):
    MINIMOS = {'cupo': 1, 'duracion_min': 15}

    dias = forms.MultipleChoiceField(
        label="Días de la semana", choices=OPCIONES_DIAS,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
    )

    class Meta:
        model = Clase
        fields = ['nombre', 'descripcion', 'nivel', 'duracion_min', 'instructor', 'sala', 'cupo', 'hora_inicio', 'activa']
        widgets = {
            'nombre': forms.TextInput(attrs=CTRL),
            'descripcion': forms.Textarea(attrs={**CTRL, 'rows': 3}),
            'nivel': forms.Select(attrs=SEL),
            'duracion_min': forms.NumberInput(attrs={**CTRL, 'min': 15, 'max': 240, 'step': 5}),
            'instructor': forms.Select(attrs=SEL),
            'sala': forms.Select(attrs=SEL),
            'cupo': forms.NumberInput(attrs={**CTRL, 'min': 1}),
            'hora_inicio': forms.TimeInput(attrs={**CTRL, 'type': 'time'}, format='%H:%M'),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['instructor'].queryset = instructores_activos()
        self.fields['instructor'].required = False
        self.fields['sala'].queryset = Sala.objects.filter(activa=True)
        if self.instance.pk:
            self.fields['dias'].initial = [str(d) for d in self.instance.lista_dias]
            # Si la sala actual está inactiva, igual debe verse
            self.fields['sala'].queryset = Sala.objects.filter(activa=True) | Sala.objects.filter(pk=self.instance.sala_id)

    def clean(self):
        datos = super().clean()
        sala, cupo = datos.get('sala'), datos.get('cupo')
        if sala and cupo and cupo > sala.capacidad:
            self.add_error('cupo', f"El cupo no puede superar la capacidad de la sala ({sala.capacidad}).")

        inicio, duracion, dias = datos.get('hora_inicio'), datos.get('duracion_min'), datos.get('dias')
        if not (inicio and duracion and dias):
            return datos
        base = datetime.datetime.combine(datetime.date.today(), inicio)
        fin = base + datetime.timedelta(minutes=duracion)
        if fin.date() != base.date():
            self.add_error('duracion_min', "La clase debe terminar el mismo día (antes de medianoche).")
            return datos

        # Dos clases no pueden usar la misma sala a la vez, ni el mismo instructor estar en dos clases.
        margen = datetime.timedelta(minutes=15)
        otras = Clase.objects.filter(activa=True).exclude(pk=self.instance.pk).select_related('sala')
        for otra in otras:
            dias_comunes = set(int(d) for d in dias) & set(otra.lista_dias)
            if not dias_comunes:
                continue
            o_ini = datetime.datetime.combine(datetime.date.today(), otra.hora_inicio)
            o_fin = o_ini + datetime.timedelta(minutes=otra.duracion_min)
            if o_fin.date() != o_ini.date():
                continue
            nombres = ", ".join(sorted(["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][d] for d in dias_comunes))
            if sala and otra.sala_id == sala.pk and base < o_fin + margen and o_ini < fin + margen:
                self.add_error('hora_inicio', f"La sala ya está ocupada por «{otra.nombre}» ({otra.hora_inicio:%H:%M}–{otra.hora_fin:%H:%M}) el {nombres} (se dejan 15 min de limpieza).")
                break
            instructor = datos.get('instructor')
            if instructor and otra.instructor_id == instructor.pk and base < o_fin and o_ini < fin:
                self.add_error('instructor', f"El instructor ya da «{otra.nombre}» el {nombres} a esa hora.")
                break
        return datos

    def save(self, commit=True):
        clase = super().save(commit=False)
        clase.dias_semana = ",".join(sorted(self.cleaned_data['dias'], key=int))
        if commit:
            clase.save()
        return clase


class TarifaForm(forms.ModelForm):
    class Meta:
        model = Tarifa
        fields = ['precio_clase_suelta', 'prueba_gratis', 'porcentaje_externos', 'punta_inicio', 'punta_fin']
        widgets = {
            'precio_clase_suelta': forms.NumberInput(attrs={**CTRL, 'min': 0}),
            'prueba_gratis': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'porcentaje_externos': forms.NumberInput(attrs={**CTRL, 'min': 0, 'max': 100}),
            'punta_inicio': forms.TimeInput(attrs={**CTRL, 'type': 'time'}, format='%H:%M'),
            'punta_fin': forms.TimeInput(attrs={**CTRL, 'type': 'time'}, format='%H:%M'),
        }

    def clean_porcentaje_externos(self):
        valor = self.cleaned_data['porcentaje_externos']
        if valor > 100:
            raise forms.ValidationError("No puede superar 100%.")
        return valor


class BloqueoForm(forms.ModelForm):
    class Meta:
        model = BloqueoFecha
        fields = ['sala', 'fecha_desde', 'fecha_hasta', 'motivo']
        widgets = {
            'sala': forms.Select(attrs=SEL),
            'fecha_desde': forms.DateInput(attrs={**CTRL, 'type': 'date'}, format='%Y-%m-%d'),
            'fecha_hasta': forms.DateInput(attrs={**CTRL, 'type': 'date'}, format='%Y-%m-%d'),
            'motivo': forms.TextInput(attrs={**CTRL, 'placeholder': 'Ej: Feriado, mantención'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sala'].required = False
        self.fields['sala'].empty_label = "Todas las salas"

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get('fecha_desde'), datos.get('fecha_hasta')
        if desde and hasta and hasta < desde:
            self.add_error('fecha_hasta', "La fecha final no puede ser anterior a la inicial.")
        elif hasta and hasta < timezone.localdate():
            self.add_error('fecha_hasta', "El bloqueo debe incluir hoy o fechas futuras.")
        elif desde and hasta and (hasta - desde).days > 366:
            self.add_error('fecha_hasta', "El bloqueo no puede durar más de un año.")
        return datos


class SesionInstructorForm(forms.Form):
    """Cambia el instructor de una sola sesión (suplente) sin tocar la clase."""
    instructor = forms.ModelChoiceField(
        label="Instructor suplente", queryset=Usuario.objects.none(), required=False,
        empty_label="El de la clase", widget=forms.Select(attrs=SEL),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['instructor'].queryset = instructores_activos()


class CambioForm(forms.Form):
    tipo = forms.ChoiceField(label="¿Qué necesitas?", choices=[
        ('SUPLENCIA', 'Pedir un suplente'), ('CANCELAR', 'Cancelar la sesión'),
    ], widget=forms.Select(attrs=SEL))
    motivo = forms.CharField(label="Motivo", min_length=5, max_length=200, widget=forms.Textarea(attrs={**CTRL, 'rows': 3}))


class ResolverCambioForm(forms.Form):
    suplente = forms.ModelChoiceField(label="Suplente (si es una suplencia)", queryset=Usuario.objects.none(),
                                      required=False, widget=forms.Select(attrs=SEL))
    nota = forms.CharField(label="Nota", required=False, max_length=200, widget=forms.TextInput(attrs=CTRL))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['suplente'].queryset = instructores_activos()


class PagoVisitaForm(forms.Form):
    """El monto NO se elige: siempre se cobra el precio completo de la clase o del arriendo."""
    metodo = forms.ChoiceField(label="Método de pago", choices=Pago.MetodoPago.choices, widget=forms.Select(attrs=SEL))


class ReservaSalaForm(forms.Form):
    sala = forms.ModelChoiceField(queryset=Sala.objects.none(), widget=forms.Select(attrs=SEL))
    fecha = forms.DateField(widget=forms.DateInput(attrs={**CTRL, 'type': 'date'}, format='%Y-%m-%d'))
    hora_inicio = forms.TimeField(label="Hora de inicio", widget=forms.TimeInput(attrs={**CTRL, 'type': 'time'}, format='%H:%M'))
    hora_fin = forms.TimeField(label="Hora de término", widget=forms.TimeInput(attrs={**CTRL, 'type': 'time'}, format='%H:%M'))
    personas = forms.IntegerField(label="Cantidad de personas", min_value=1, max_value=500, initial=1, widget=forms.NumberInput(attrs={**CTRL, 'min': 1}))
    motivo = forms.CharField(label="Motivo", max_length=200,
                             widget=forms.TextInput(attrs={**CTRL, 'placeholder': 'Ej: entrenamiento personal, grupo privado'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sala'].queryset = Sala.objects.filter(activa=True)

    def clean(self):
        datos = super().clean()
        ini, fin, fecha = datos.get('hora_inicio'), datos.get('hora_fin'), datos.get('fecha')
        if ini and fin and ini >= fin:
            self.add_error('hora_fin', "La hora de término debe ser posterior a la de inicio.")
        if fecha and fecha < timezone.localdate():
            self.add_error('fecha', "La fecha no puede estar en el pasado.")
        if fecha and fecha > timezone.localdate() + datetime.timedelta(days=180):
            self.add_error('fecha', "Solo se reserva con hasta 6 meses de anticipación.")
        return datos


class ReservaSalaStaffForm(ReservaSalaForm):
    """Reserva hecha por el personal: se puede cobrar de inmediato el precio completo (por horas)."""
    cobrar_ahora = forms.BooleanField(label="Cobrar ahora el precio completo de la reserva", required=False,
                                      widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    metodo = forms.ChoiceField(label="Método de pago", required=False, choices=[('', '---------')] + list(Pago.MetodoPago.choices),
                               widget=forms.Select(attrs=SEL))

    def clean(self):
        datos = super().clean()
        if datos.get('cobrar_ahora') and not datos.get('metodo'):
            self.add_error('metodo', "Elige el método de pago para cobrar.")
        return datos


class VisitanteForm(forms.Form):
    """Datos del visitante (los mismos en recepción y en la página pública)."""
    nombre = forms.CharField(label="Nombre completo", max_length=120, widget=forms.TextInput(attrs=CTRL))
    rut = forms.CharField(label="RUT", widget=forms.TextInput(attrs={**CTRL, 'placeholder': '12.345.678-9'}))
    email = forms.EmailField(label="Correo electrónico", widget=forms.EmailInput(attrs=CTRL))
    telefono = forms.CharField(label="Teléfono", widget=forms.TextInput(attrs={**CTRL, 'placeholder': '+56912345678'}))
    fecha_nacimiento = forms.DateField(label="Fecha de nacimiento",
                                       widget=forms.DateInput(attrs={**CTRL, 'type': 'date'}, format='%Y-%m-%d'))
    apoderado_nombre = forms.CharField(label="Apoderado (si es menor de 18)", required=False, max_length=120, widget=forms.TextInput(attrs=CTRL))
    apoderado_rut = forms.CharField(label="RUT del apoderado", required=False, widget=forms.TextInput(attrs=CTRL))
    acepto_terminos = forms.BooleanField(label="Acepto los términos y condiciones de uso del gimnasio",
                                         error_messages={'required': "Debes aceptar los términos para continuar."},
                                         widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))

    def __init__(self, *args, staff=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.staff = staff   # el personal puede corregir el correo de un visitante

    def clean_rut(self):
        rut = limpiar_rut(self.cleaned_data['rut'])
        if not validar_rut(rut):
            raise forms.ValidationError("RUT inválido.")
        return rut

    def clean_telefono(self):
        tel = self.cleaned_data['telefono'].strip()
        if not validar_telefono(tel):
            raise forms.ValidationError("Teléfono inválido. Debe tener entre 8 y 12 dígitos.")
        return tel

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data['fecha_nacimiento']
        if fecha >= timezone.localdate() or fecha.year < timezone.localdate().year - 110:
            raise forms.ValidationError("La fecha de nacimiento no es válida.")
        return fecha

    def clean_apoderado_rut(self):
        rut = self.cleaned_data.get('apoderado_rut', '').strip()
        if not rut:
            return ''
        rut = limpiar_rut(rut)
        if not validar_rut(rut):
            raise forms.ValidationError("RUT del apoderado inválido.")
        return rut

    def clean(self):
        datos = super().clean()
        # Nadie puede cambiar el correo de un visitante ya registrado usando solo su RUT.
        rut, email = datos.get('rut'), datos.get('email')
        if rut and email and not self.staff:
            if Visitante.objects.filter(rut=rut).exclude(email__iexact=email).exists():
                self.add_error('email', "Este RUT ya está registrado con otro correo. Usa ese correo o consulta en recepción.")
        nac = datos.get('fecha_nacimiento')
        if nac:
            hoy = timezone.localdate()
            edad = hoy.year - nac.year - ((hoy.month, hoy.day) < (nac.month, nac.day))
            if edad < 18 and not (datos.get('apoderado_nombre') and datos.get('apoderado_rut')):
                self.add_error('apoderado_nombre', "Los menores de 18 años necesitan los datos de su apoderado.")
        return datos

    def guardar(self, email_verificado=False):
        """Crea o actualiza al visitante por su RUT."""
        d = self.cleaned_data
        visitante, _ = Visitante.objects.get_or_create(rut=d['rut'], defaults={
            'nombre': d['nombre'], 'email': d['email'], 'telefono': d['telefono'],
            'fecha_nacimiento': d['fecha_nacimiento'],
        })
        visitante.nombre = d['nombre']
        visitante.email = d['email']
        visitante.telefono = d['telefono']
        visitante.fecha_nacimiento = d['fecha_nacimiento']
        visitante.apoderado_nombre = d.get('apoderado_nombre', '')
        visitante.apoderado_rut = d.get('apoderado_rut', '')
        visitante.acepto_terminos = True
        visitante.acepto_en = visitante.acepto_en or timezone.now()
        visitante.email_verificado = bool(email_verificado)
        visitante.save()
        return visitante


class SolicitarCodigoForm(forms.Form):
    email = forms.EmailField(label="Tu correo electrónico", widget=forms.EmailInput(attrs={**CTRL, 'placeholder': 'tucorreo@ejemplo.cl'}))


class VerificarCodigoForm(forms.Form):
    codigo = forms.CharField(label="Código de 6 dígitos", min_length=6, max_length=6,
                             widget=forms.TextInput(attrs={**CTRL, 'inputmode': 'numeric', 'autocomplete': 'one-time-code'}))


class ConsultaVisitanteForm(forms.Form):
    codigo = forms.CharField(label="Código de reserva", widget=forms.TextInput(attrs=CTRL))
    email = forms.EmailField(label="Correo con el que reservaste", widget=forms.EmailInput(attrs=CTRL))
