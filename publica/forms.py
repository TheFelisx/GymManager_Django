from django import forms

from cuentas.validators import validar_telefono
from .models import MensajeContacto


class ContactoForm(forms.ModelForm):
    # Campo trampa para bots: las personas no lo ven ni lo llenan.
    sitio_web = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'tabindex': '-1', 'autocomplete': 'off', 'style': 'position:absolute;left:-9999px;', 'aria-hidden': 'true',
    }))

    class Meta:
        model = MensajeContacto
        fields = ['nombre', 'email', 'telefono', 'mensaje']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tu nombre'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Tu correo'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Teléfono (opcional)'}),
            'mensaje': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': '¿En qué podemos ayudarte?'}),
        }

    def clean_telefono(self):
        tel = self.cleaned_data.get('telefono', '').strip()
        if tel and not validar_telefono(tel):
            raise forms.ValidationError("Teléfono inválido. Debe tener entre 8 y 12 dígitos.")
        return tel

    def clean_sitio_web(self):
        if self.cleaned_data.get('sitio_web'):
            raise forms.ValidationError("Solicitud no válida.")
        return ''
