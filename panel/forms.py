from datetime import timedelta

from django import forms
from django.core.validators import MinValueValidator
from django.db import transaction
from django.utils import timezone

from cuentas.models import Usuario
from cuentas.utils import generar_clave_temporal
from cuentas.validators import limpiar_rut, validar_rut
from .models import Plan, Socio, Pago

OPCIONES_DIAS = [
    ('0', 'Lunes'),
    ('1', 'Martes'),
    ('2', 'Miércoles'),
    ('3', 'Jueves'),
    ('4', 'Viernes'),
    ('5', 'Sábado'),
    ('6', 'Domingo'),
]


def _validar_foto(foto):
    """La foto no puede pesar más de 5 MB."""
    if foto and hasattr(foto, 'size') and foto.size > 5 * 1024 * 1024:
        raise forms.ValidationError("La foto no puede pesar más de 5 MB.")
    return foto


class MinimosMixin:
    """Valida el mínimo real de cada campo numérico en el formulario, con UN solo mensaje.

    Los campos PositiveIntegerField de Django agregan por su cuenta un validador
    "mayor o igual a 0", que choca con el mínimo propio del modelo (por ejemplo 1)
    y mostraba mensajes contradictorios. Al validar aquí, Django ya no ejecuta los
    validadores del modelo para ese campo cuando falla.

    Cada formulario define MINIMOS = {'campo': valor_minimo}.
    """
    MINIMOS = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre, minimo in self.MINIMOS.items():
            campo = self.fields.get(nombre)
            if campo is not None:
                campo.validators.insert(0, MinValueValidator(
                    minimo, message=f"Ingresa un valor mayor o igual a {minimo}."))


class PlanForm(MinimosMixin, forms.ModelForm):
    MINIMOS = {'precio': 1, 'duracion_dias': 1}

    dias_seleccionados = forms.MultipleChoiceField(
        label="Días permitidos",
        choices=OPCIONES_DIAS,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        initial=['0', '1', '2', '3', '4', '5', '6']
    )

    class Meta:
        model = Plan
        fields = ['nombre', 'precio', 'duracion_dias', 'clases_por_semana', 'hora_inicio', 'hora_fin', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Plan Full Mensual'}),
            'precio': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'duracion_dias': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 3650}),
            'clases_por_semana': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 50, 'placeholder': 'Vacío = ilimitadas'}),
            'hora_inicio': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'hora_fin': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.dias_permitidos:
            self.fields['dias_seleccionados'].initial = self.instance.dias_permitidos.split(',')

    def clean_precio(self):
        precio = self.cleaned_data['precio']
        if precio < 1 or precio > 10000000:
            raise forms.ValidationError("El precio debe estar entre $1 y $10.000.000.")
        return precio

    def clean_clases_por_semana(self):
        valor = self.cleaned_data.get('clases_por_semana')
        if valor is not None and valor > 50:
            raise forms.ValidationError("Máximo 50 clases por semana (deja vacío para ilimitadas).")
        return valor

    def clean(self):
        cleaned_data = super().clean()
        h_ini = cleaned_data.get('hora_inicio')
        h_fin = cleaned_data.get('hora_fin')
        if h_ini and h_fin and h_ini >= h_fin:
            self.add_error('hora_fin', "La hora de término debe ser posterior a la hora de inicio.")
        return cleaned_data

    def save(self, commit=True):
        plan = super().save(commit=False)
        dias = sorted(self.cleaned_data['dias_seleccionados'], key=int)
        plan.dias_permitidos = ",".join(dias)
        if commit:
            plan.save()
        return plan


class EnrolarSocioForm(forms.ModelForm):
    """Enrola al socio y, si se elige un plan, registra su primer pago en el mismo paso.

    Todo ocurre dentro de una transacción: si algo falla, no queda un socio a medias.
    """
    first_name = forms.CharField(label="Nombres", widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(label="Apellidos", widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(label="Correo electrónico", widget=forms.EmailInput(attrs={'class': 'form-control'}))

    plan = forms.ModelChoiceField(
        label="Primer pago: plan",
        queryset=Plan.objects.none(),
        required=False,
        empty_label="Sin pago por ahora",
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    metodo_pago = forms.ChoiceField(
        label="Primer pago: método",
        choices=[('', '---------')] + list(Pago.MetodoPago.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    descuento = forms.IntegerField(
        label="Descuento (CLP)",
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        help_text="Solo administración puede aplicar descuentos.",
    )

    class Meta:
        model = Socio
        fields = ['rut', 'fecha_nacimiento', 'telefono', 'foto']
        widgets = {
            'rut': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 21.503.224-1'}),
            'fecha_nacimiento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+56912345678'}),
            'foto': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.fields['plan'].queryset = Plan.objects.filter(activo=True)
        if not (actor and (actor.es_master or actor.es_admin)):
            del self.fields['descuento']

    def clean_foto(self):
        return _validar_foto(self.cleaned_data.get('foto'))

    def clean_rut(self):
        rut_limpio = limpiar_rut(self.cleaned_data['rut'])
        if not validar_rut(rut_limpio):
            raise forms.ValidationError("RUT inválido.")
        if Socio.objects.filter(rut=rut_limpio).exists() or Usuario.objects.filter(username=rut_limpio).exists():
            raise forms.ValidationError("Ya existe un socio o usuario registrado con este RUT.")
        return rut_limpio

    def clean(self):
        cleaned = super().clean()
        plan = cleaned.get('plan')
        if plan and not cleaned.get('metodo_pago'):
            self.add_error('metodo_pago', "Indica el método de pago del primer pago.")
        descuento = cleaned.get('descuento') or 0
        if plan and descuento >= plan.precio:
            self.add_error('descuento', "El descuento debe ser menor que el precio del plan.")
        return cleaned

    @transaction.atomic
    def save(self, creador=None, commit=True):
        rut_limpio = self.cleaned_data['rut']
        clave_temporal = generar_clave_temporal()

        usuario = Usuario.objects.create_user(
            username=rut_limpio,
            first_name=self.cleaned_data['first_name'].strip(),
            last_name=self.cleaned_data['last_name'].strip(),
            email=self.cleaned_data['email'].strip(),
            password=clave_temporal,
            rol=Usuario.Rol.SOCIO,
            creado_por=creador,
            debe_cambiar_clave=True
        )

        socio = super().save(commit=False)
        socio.usuario = usuario
        socio.save()

        self.pago = None
        plan = self.cleaned_data.get('plan')
        if plan:
            descuento = self.cleaned_data.get('descuento') or 0
            self.pago = Pago.objects.create(
                socio=socio,
                plan=plan,
                metodo_pago=self.cleaned_data['metodo_pago'],
                fecha_inicio=socio.fecha_inicio_renovacion(),
                monto_pagado=plan.precio - descuento,
                descuento=descuento,
                descuento_autorizado_por=creador if descuento else None,
                registrado_por=creador,
            )
        return socio, clave_temporal


class EditarSocioForm(forms.ModelForm):
    """Edita los datos del socio y su foto. Solo administración corrige el RUT."""
    first_name = forms.CharField(label="Nombres", widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(label="Apellidos", widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(label="Correo electrónico", widget=forms.EmailInput(attrs={'class': 'form-control'}))

    class Meta:
        model = Socio
        fields = ['rut', 'fecha_nacimiento', 'telefono', 'foto']
        widgets = {
            'rut': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha_nacimiento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'foto': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.puede_corregir_rut = bool(actor and (actor.es_master or actor.es_admin))
        if not self.puede_corregir_rut:
            del self.fields['rut']
        usuario = self.instance.usuario
        self.fields['first_name'].initial = usuario.first_name
        self.fields['last_name'].initial = usuario.last_name
        self.fields['email'].initial = usuario.email

    def clean_foto(self):
        return _validar_foto(self.cleaned_data.get('foto'))

    def clean_rut(self):
        rut_limpio = limpiar_rut(self.cleaned_data['rut'])
        if not validar_rut(rut_limpio):
            raise forms.ValidationError("RUT inválido.")
        if Socio.objects.filter(rut=rut_limpio).exclude(pk=self.instance.pk).exists() \
                or Usuario.objects.filter(username=rut_limpio).exclude(pk=self.instance.usuario_id).exists():
            raise forms.ValidationError("Ya existe otra cuenta con este RUT.")
        return rut_limpio

    @transaction.atomic
    def save(self, commit=True):
        socio = super().save(commit=False)
        usuario = socio.usuario
        usuario.first_name = self.cleaned_data['first_name'].strip()
        usuario.last_name = self.cleaned_data['last_name'].strip()
        usuario.email = self.cleaned_data['email'].strip()
        if self.puede_corregir_rut and 'rut' in self.cleaned_data:
            usuario.username = self.cleaned_data['rut']   # el usuario del socio es su RUT
        usuario.save()
        socio.save()
        return socio


class MiPerfilForm(forms.ModelForm):
    """El socio solo actualiza teléfono y correo (la foto y el RUT los cambia el personal)."""
    email = forms.EmailField(label="Correo electrónico", widget=forms.EmailInput(attrs={'class': 'form-control'}))

    class Meta:
        model = Socio
        fields = ['telefono']
        widgets = {'telefono': forms.TextInput(attrs={'class': 'form-control'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].initial = self.instance.usuario.email

    def save(self, commit=True):
        socio = super().save(commit=commit)
        socio.usuario.email = self.cleaned_data['email'].strip()
        socio.usuario.save(update_fields=['email'])
        return socio


class MotivoForm(forms.Form):
    """Motivo obligatorio (baja de un socio o anulación de un pago)."""
    motivo = forms.CharField(
        label="Motivo",
        min_length=5,
        max_length=200,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Explica brevemente el motivo'}),
    )


class PagoForm(forms.ModelForm):
    descuento = forms.IntegerField(
        label="Descuento (CLP)",
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        help_text="Solo administración puede autorizar descuentos.",
    )

    class Meta:
        model = Pago
        fields = ['socio', 'plan', 'metodo_pago', 'fecha_inicio']
        widgets = {
            'socio': forms.Select(attrs={'class': 'form-select'}),
            'plan': forms.Select(attrs={'class': 'form-select'}),
            'metodo_pago': forms.Select(attrs={'class': 'form-select'}),
            'fecha_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.puede_descontar = bool(actor and (actor.es_master or actor.es_admin))
        self.fields['plan'].queryset = Plan.objects.filter(activo=True)
        # No se registran pagos a socios dados de baja.
        self.fields['socio'].queryset = Socio.objects.select_related('usuario').filter(usuario__is_active=True)
        self.fields['fecha_inicio'].required = False
        self.fields['fecha_inicio'].help_text = (
            "Déjala vacía para renovar automáticamente: la membresía parte desde el "
            "mayor entre su vencimiento actual y hoy."
        )
        if not self.puede_descontar:
            del self.fields['descuento']

    def clean(self):
        cleaned = super().clean()
        socio = cleaned.get('socio')
        plan = cleaned.get('plan')
        if socio and socio.de_baja:
            self.add_error('socio', "No se pueden registrar pagos a un socio dado de baja.")
        if socio:
            inicio_auto = socio.fecha_inicio_renovacion()
            inicio = cleaned.get('fecha_inicio')
            if not inicio:
                cleaned['fecha_inicio'] = inicio_auto
            elif inicio < inicio_auto and not self.puede_descontar:
                self.add_error(
                    'fecha_inicio',
                    f"La renovación debe comenzar el {inicio_auto:%d/%m/%Y} o después."
                )
            elif abs((inicio - timezone.localdate()).days) > 365:
                self.add_error('fecha_inicio', "La fecha de inicio no puede estar a más de un año de hoy.")
        descuento = cleaned.get('descuento') or 0
        if plan and descuento >= plan.precio:
            self.add_error('descuento', "El descuento debe ser menor que el precio del plan.")
        return cleaned

    def save(self, commit=True):
        pago = super().save(commit=False)
        descuento = self.cleaned_data.get('descuento') or 0
        pago.fecha_inicio = self.cleaned_data['fecha_inicio']
        pago.descuento = descuento
        pago.monto_pagado = pago.plan.precio - descuento
        if descuento:
            pago.descuento_autorizado_por = self.actor
        pago.registrado_por = self.actor
        if commit:
            pago.save()
        return pago
