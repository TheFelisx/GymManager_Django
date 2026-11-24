import calendar
import json
from datetime import date

from django.contrib import messages
from django.db.models import Count, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from cuentas.decorators import rol_requerido
from cuentas.utils import registrar_auditoria
from panel.paginacion import paginar
from panel.services import pagos_validos, rango_fechas, resumen_por_metodo
from .forms import GastoForm
from .models import Gasto
from reservas.models import Inscripcion, ReservaSala
from panel.models import Pago


def _mes_desde_texto(texto):
    """Convierte 'YYYY-MM' en un date (primer día del mes) o None."""
    try:
        anio, mes = texto.split('-')
        return date(int(anio), int(mes), 1)
    except (ValueError, AttributeError):
        return None


def _desplazar_mes(primer_dia, meses):
    indice = primer_dia.year * 12 + (primer_dia.month - 1) + meses
    return date(indice // 12, indice % 12 + 1, 1)


@rol_requerido(['MASTER', 'ADMIN'])
def inicio_finanzas(request):
    hoy = timezone.localdate()

    # Selector de mes: ?mes=2026-11 (por defecto el mes actual). También se
    # puede afinar con un rango libre ?desde=...&hasta=...
    mes = _mes_desde_texto(request.GET.get('mes')) or hoy.replace(day=1)
    ultimo = calendar.monthrange(mes.year, mes.month)[1]
    fecha_desde, fecha_hasta = mes, date(mes.year, mes.month, ultimo)
    if request.GET.get('desde') or request.GET.get('hasta'):
        try:
            fecha_desde = date.fromisoformat(request.GET.get('desde', ''))
        except ValueError:
            pass
        try:
            fecha_hasta = date.fromisoformat(request.GET.get('hasta', ''))
        except ValueError:
            pass
        if fecha_desde > fecha_hasta:
            fecha_desde, fecha_hasta = fecha_hasta, fecha_desde

    inicio_dt, fin_dt = rango_fechas(fecha_desde, fecha_hasta)
    pagos_periodo = pagos_validos().select_related('socio__usuario', 'plan').filter(
        fecha_pago__gte=inicio_dt, fecha_pago__lt=fin_dt
    )
    gastos_periodo = Gasto.objects.select_related('registrado_por').filter(
        fecha__gte=fecha_desde, fecha__lte=fecha_hasta
    )

    # Otros orígenes de ingreso: clases sueltas de visitantes y arriendo de salas
    clases_periodo = Inscripcion.objects.filter(
        visitante__isnull=False, reembolsado=False, monto_pagado__gt=0, fecha_pago__gte=inicio_dt, fecha_pago__lt=fin_dt)
    salas_periodo = ReservaSala.objects.filter(
        reembolsado=False, monto_pagado__gt=0, fecha_pago__gte=inicio_dt, fecha_pago__lt=fin_dt)
    ing_membresias = pagos_periodo.aggregate(total=Sum('monto_pagado'))['total'] or 0
    ing_clases = clases_periodo.aggregate(total=Sum('monto_pagado'))['total'] or 0
    ing_salas = salas_periodo.aggregate(total=Sum('monto_pagado'))['total'] or 0
    total_ingresos = ing_membresias + ing_clases + ing_salas
    total_gastos = gastos_periodo.aggregate(total=Sum('monto'))['total'] or 0
    ganancia_neta = total_ingresos - total_gastos

    # Desgloses
    por_plan = list(
        pagos_periodo.values('plan__nombre').annotate(total=Sum('monto_pagado'), n=Count('id')).order_by('-total')
    )
    etiquetas_metodo = dict(Pago.MetodoPago.choices)
    acumulado = {f['metodo']: dict(f) for f in resumen_por_metodo(pagos_periodo)}
    for qs in (clases_periodo, salas_periodo):
        for f in qs.values('metodo_pago').annotate(total=Sum('monto_pagado'), n=Count('id')):
            nombre = etiquetas_metodo.get(f['metodo_pago'], f['metodo_pago'] or 'Sin método')
            fila = acumulado.setdefault(nombre, {'metodo': nombre, 'total': 0, 'n': 0})
            fila['total'] += f['total'] or 0
            fila['n'] += f['n']
    por_metodo = sorted(acumulado.values(), key=lambda f: -f['total'])
    etiquetas_cat = dict(Gasto.Categoria.choices)
    por_categoria = [
        {'categoria': etiquetas_cat.get(f['categoria'], f['categoria']), 'total': f['total'], 'n': f['n']}
        for f in gastos_periodo.values('categoria').annotate(total=Sum('monto'), n=Count('id')).order_by('-total')
    ]

    context = {
        'mes_valor': mes.strftime('%Y-%m'),
        'mes_anterior': _desplazar_mes(mes, -1).strftime('%Y-%m'),
        'mes_siguiente': _desplazar_mes(mes, 1).strftime('%Y-%m'),
        'fecha_desde': fecha_desde.strftime('%Y-%m-%d'),
        'fecha_hasta': fecha_hasta.strftime('%Y-%m-%d'),
        'total_ingresos': total_ingresos,
        'total_gastos': total_gastos,
        'ganancia_neta': ganancia_neta,
        'por_plan': por_plan,
        'por_metodo': por_metodo,
        'por_categoria': por_categoria,
        # Origen del ingreso: membresías, clases sueltas y arriendo de salas.
        'por_origen': [
            {'origen': 'Membresías', 'total': ing_membresias, 'n': pagos_periodo.count()},
            {'origen': 'Clases sueltas', 'total': ing_clases, 'n': clases_periodo.count()},
            {'origen': 'Arriendo de salas', 'total': ing_salas, 'n': salas_periodo.count()},
        ],
        'pag_ingresos': paginar(request, pagos_periodo.order_by('-fecha_pago', '-id'), 10, 'p_ing'),
        'pag_gastos': paginar(request, gastos_periodo.order_by('-fecha', '-id'), 10, 'p_gas'),
        'graf_metodo_etiquetas': json.dumps([f['metodo'] for f in por_metodo]),
        'graf_metodo_valores': json.dumps([f['total'] for f in por_metodo]),
        'graf_categoria_etiquetas': json.dumps([f['categoria'] for f in por_categoria]),
        'graf_categoria_valores': json.dumps([f['total'] for f in por_categoria]),
    }
    return render(request, 'finanzas/inicio.html', context)


@rol_requerido(['MASTER', 'ADMIN'])
def registrar_gasto(request):
    form = GastoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        gasto = form.save(commit=False)
        gasto.registrado_por = request.user
        gasto.save()
        registrar_auditoria(
            request.user,
            "REGISTRAR_GASTO",
            f"Gasto registrado: {gasto.concepto} por ${gasto.monto} ({gasto.get_categoria_display()})"
        )
        messages.success(request, f"Gasto '{gasto.concepto}' registrado por ${gasto.monto}.")
        return redirect('finanzas:inicio')

    return render(request, 'finanzas/gasto_form.html', {'form': form})
