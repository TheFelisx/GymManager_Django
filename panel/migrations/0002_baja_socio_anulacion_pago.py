import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('panel', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='socio',
            name='fecha_baja',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Fecha de baja'),
        ),
        migrations.AddField(
            model_name='socio',
            name='motivo_baja',
            field=models.CharField(blank=True, editable=False, max_length=200, verbose_name='Motivo de la baja'),
        ),
        migrations.AddField(
            model_name='pago',
            name='descuento',
            field=models.PositiveIntegerField(default=0, verbose_name='Descuento (CLP)'),
        ),
        migrations.AddField(
            model_name='pago',
            name='descuento_autorizado_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='descuentos_autorizados', to=settings.AUTH_USER_MODEL, verbose_name='Descuento autorizado por'),
        ),
        migrations.AddField(
            model_name='pago',
            name='anulado',
            field=models.BooleanField(default=False, verbose_name='Pago anulado'),
        ),
        migrations.AddField(
            model_name='pago',
            name='motivo_anulacion',
            field=models.CharField(blank=True, max_length=200, verbose_name='Motivo de la anulación'),
        ),
        migrations.AddField(
            model_name='pago',
            name='anulado_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pagos_anulados', to=settings.AUTH_USER_MODEL, verbose_name='Anulado por'),
        ),
        migrations.AddField(
            model_name='pago',
            name='fecha_anulacion',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Fecha de anulación'),
        ),
    ]
