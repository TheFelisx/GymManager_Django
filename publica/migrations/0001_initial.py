from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Entrenador',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100, verbose_name='Nombre')),
                ('especialidad', models.CharField(max_length=120, verbose_name='Especialidad')),
                ('foto', models.ImageField(blank=True, null=True, upload_to='entrenadores/', verbose_name='Foto')),
                ('orden', models.PositiveSmallIntegerField(default=0, verbose_name='Orden')),
                ('activo', models.BooleanField(default=True, verbose_name='Visible en la página')),
            ],
            options={
                'verbose_name': 'Entrenador',
                'verbose_name_plural': 'Entrenadores',
                'ordering': ['orden', 'nombre'],
            },
        ),
        migrations.CreateModel(
            name='PreguntaFrecuente',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pregunta', models.CharField(max_length=200, verbose_name='Pregunta')),
                ('respuesta', models.TextField(verbose_name='Respuesta')),
                ('orden', models.PositiveSmallIntegerField(default=0, verbose_name='Orden')),
                ('activa', models.BooleanField(default=True, verbose_name='Visible en la página')),
            ],
            options={
                'verbose_name': 'Pregunta frecuente',
                'verbose_name_plural': 'Preguntas frecuentes',
                'ordering': ['orden', 'id'],
            },
        ),
        migrations.CreateModel(
            name='MensajeContacto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100)),
                ('email', models.EmailField(max_length=254)),
                ('telefono', models.CharField(blank=True, max_length=20)),
                ('mensaje', models.TextField(max_length=1500)),
                ('fecha', models.DateTimeField(auto_now_add=True)),
                ('atendido', models.BooleanField(default=False)),
            ],
            options={
                'verbose_name': 'Mensaje de contacto',
                'verbose_name_plural': 'Mensajes de contacto',
                'ordering': ['-fecha'],
            },
        ),
    ]
