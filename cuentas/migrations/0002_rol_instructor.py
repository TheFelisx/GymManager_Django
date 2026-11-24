from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cuentas', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='usuario',
            name='rol',
            field=models.CharField(choices=[('MASTER', 'Master'), ('ADMIN', 'Administrador'), ('RECEPCIONISTA', 'Recepcionista'), ('GUARDIA', 'Guardia'), ('INSTRUCTOR', 'Instructor'), ('SOCIO', 'Socio')], default='SOCIO', max_length=20, verbose_name='Rol en el sistema'),
        ),
    ]
