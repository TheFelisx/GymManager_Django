import re
from django import forms
from .models import Usuario
from .validators import limpiar_rut, validar_rut


class LoginForm(forms.Form):
    username = forms.CharField(
        label="RUT o Usuario",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: 12.345.678-9',
            'autofocus': True
        })
    )
    password = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control'
        })
    )


class EditarUsuarioForm(forms.ModelForm):
    """Edita nombre y correo del personal (el rol y el usuario no cambian aquí)."""

    class Meta:
        model = Usuario
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }


class CrearUsuarioForm(forms.ModelForm):
    password = forms.CharField(
        label="Contraseña temporal",
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text="Mínimo 8 caracteres. El usuario deberá cambiarla al entrar."
    )
    password_confirm = forms.CharField(
        label="Repetir contraseña",
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Usuario
        fields = ['username', 'first_name', 'last_name', 'email', 'rol']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: recepcion.ana (3-30 caracteres)'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'rol': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, creador=None, **kwargs):
        super().__init__(*args, **kwargs)
        if creador:
            # Los socios se crean desde «Enrolar socio» (necesitan RUT, foto y QR),
            # por eso no aparecen aquí. El master crea administradores; el
            # administrador solo crea recepcionistas y guardias.
            if creador.es_master:
                self.fields['rol'].choices = [
                    (Usuario.Rol.ADMIN, 'Administrador'),
                    (Usuario.Rol.RECEPCIONISTA, 'Recepcionista'),
                    (Usuario.Rol.GUARDIA, 'Guardia'),
                    (Usuario.Rol.INSTRUCTOR, 'Instructor'),
                ]
            elif creador.rol == Usuario.Rol.ADMIN:
                self.fields['rol'].choices = [
                    (Usuario.Rol.RECEPCIONISTA, 'Recepcionista'),
                    (Usuario.Rol.GUARDIA, 'Guardia'),
                    (Usuario.Rol.INSTRUCTOR, 'Instructor'),
                ]
            else:
                self.fields['rol'].choices = []
        self._creador = creador

    def clean_rol(self):
        """Los roles que cada usuario puede crear se validan también en el servidor."""
        rol = self.cleaned_data['rol']
        permitidos = [valor for valor, _ in self.fields['rol'].choices]
        if rol not in permitidos:
            raise forms.ValidationError("No tienes permiso para crear usuarios con este rol.")
        return rol

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{3,30}", username):
            raise forms.ValidationError("El usuario debe tener de 3 a 30 caracteres (letras, números, punto, guion o guion bajo).")
        
        # El usuario del personal no puede parecerse a un RUT (el de los socios es su RUT).
        if re.fullmatch(r"\d{1,2}\.?\d{3}\.?\d{3}-?[\dkK]", username) or validar_rut(username):
            raise forms.ValidationError("El usuario del personal no puede parecerse a un RUT. Usa un nombre, por ejemplo: recepcion.ana")
        if Usuario.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ese nombre de usuario ya existe.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username', '')
        clave = cleaned_data.get('password', '')
        clave_repetida = cleaned_data.get('password_confirm', '')

        if clave:
            if len(clave) < 8:
                self.add_error('password', "La contraseña debe tener al menos 8 caracteres.")
            elif len(clave.encode()) > 72:
                self.add_error('password', "La contraseña es demasiado larga (máximo 72 caracteres).")
            elif username and clave.lower() == username.lower():
                self.add_error('password', "La contraseña no puede ser igual al nombre de usuario.")

        if clave and clave_repetida and clave != clave_repetida:
            self.add_error('password_confirm', "Las contraseñas no coinciden.")

        return cleaned_data

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.set_password(self.cleaned_data['password'])
        usuario.debe_cambiar_clave = True
        if commit:
            usuario.save()
        return usuario
