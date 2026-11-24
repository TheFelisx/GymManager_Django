import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservas', '0002_validaciones'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sala',
            name='precio_hora',
            field=models.PositiveIntegerField(help_text='Lo que se cobra por cada hora de arriendo de la sala. Al reservar, el sistema calcula el total según las horas.', validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(10000000)], verbose_name='Cuánto cuesta por hora (CLP)'),
        ),
        migrations.AlterField(
            model_name='sala',
            name='precio_hora_punta',
            field=models.PositiveIntegerField(blank=True, help_text='Opcional. Vacío = mismo valor que el normal.', null=True, validators=[django.core.validators.MaxValueValidator(10000000)], verbose_name='Cuánto cuesta por hora en hora punta (CLP)'),
        ),
    ]
