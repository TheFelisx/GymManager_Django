from django import forms
from django.utils import timezone

from panel.forms import MinimosMixin
from .models import Gasto


class GastoForm(MinimosMixin, forms.ModelForm):
    MINIMOS = {'monto': 1}

    class Meta:
        model = Gasto
        fields = ['concepto', 'categoria', 'monto', 'fecha']
        widgets = {
            'concepto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Pago cuenta de luz mes actual'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def clean_monto(self):
        monto = self.cleaned_data['monto']
        if monto < 1 or monto > 100000000:
            raise forms.ValidationError("El monto debe estar entre $1 y $100.000.000.")
        return monto

    def clean_fecha(self):
        fecha = self.cleaned_data['fecha']
        if fecha > timezone.localdate():
            raise forms.ValidationError("La fecha del gasto no puede ser futura.")
        if fecha.year < timezone.localdate().year - 5:
            raise forms.ValidationError("La fecha del gasto es demasiado antigua.")
        return fecha
