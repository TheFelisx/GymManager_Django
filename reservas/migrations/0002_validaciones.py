import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservas', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tarifa',
            name='precio_clase_suelta',
            field=models.PositiveIntegerField(default=5000, validators=[django.core.validators.MaxValueValidator(1000000)], verbose_name='Precio de la clase suelta (CLP)'),
        ),
        migrations.AlterField(
            model_name='tarifa',
            name='porcentaje_externos',
            field=models.PositiveSmallIntegerField(default=20, validators=[django.core.validators.MaxValueValidator(100)], verbose_name='% de cupo reservado a externos'),
        ),
        migrations.AlterField(
            model_name='sala',
            name='capacidad',
            field=models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(500)], verbose_name='Capacidad máxima'),
        ),
        migrations.AlterField(
            model_name='sala',
            name='precio_hora',
            field=models.PositiveIntegerField(default=0, validators=[django.core.validators.MaxValueValidator(10000000)], verbose_name='Arriendo por hora (CLP)'),
        ),
        migrations.AlterField(
            model_name='sala',
            name='precio_hora_punta',
            field=models.PositiveIntegerField(blank=True, help_text='Vacío = mismo valor que el normal.', null=True, validators=[django.core.validators.MaxValueValidator(10000000)], verbose_name='Arriendo por hora en hora punta (CLP)'),
        ),
        migrations.AlterField(
            model_name='clase',
            name='duracion_min',
            field=models.PositiveSmallIntegerField(default=60, validators=[django.core.validators.MinValueValidator(15), django.core.validators.MaxValueValidator(240)], verbose_name='Duración (minutos)'),
        ),
        migrations.AlterField(
            model_name='clase',
            name='cupo',
            field=models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(500)], verbose_name='Cupo'),
        ),
    ]
