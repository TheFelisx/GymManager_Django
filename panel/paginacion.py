"""Paginación sencilla para limitar cuántas filas se ven por pantalla en las tablas."""
from urllib.parse import urlencode

from django.core.paginator import Paginator


def paginar(request, elementos, por_pagina=15, param='pagina'):
    """Devuelve la página pedida en ?<param>=N, lista para mostrar con partials/paginacion.html.

    Conserva los demás filtros de la URL (búsqueda, estado, fechas...) al cambiar de página.
    """
    paginador = Paginator(elementos, por_pagina)
    pagina = paginador.get_page(request.GET.get(param))
    otros = [(k, v) for k, v in request.GET.items() if k != param]
    pagina.param = param
    pagina.qs_base = urlencode(otros)
    pagina.rango = list(paginador.get_elided_page_range(pagina.number, on_each_side=2, on_ends=1))
    return pagina
