from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('panel', '0002_baja_socio_anulacion_pago'),
    ]

    operations = [
        migrations.AddField(
            model_name='plan',
            name='clases_por_semana',
            field=models.PositiveSmallIntegerField(blank=True, help_text='Déjalo vacío para clases ilimitadas; 0 si el plan no incluye clases.', null=True, verbose_name='Clases por semana'),
        ),
    ]
