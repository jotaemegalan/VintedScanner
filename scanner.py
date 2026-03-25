#!/usr/bin/env python3
"""
Recotinta Scanner — Wallapop + Vinted
Busca anuncios de consumibles de impresión y envía alertas a Telegram.
Ejecutado via GitHub Actions cada 30 minutos.
"""

import os
import json
import time
import logging
import requests
from pathlib import Path

# ── CONFIGURACIÓN ─────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT   = os.environ.get('TELEGRAM_CHAT_ID', '')
SEEN_FILE       = 'seen_ids.json'
MAX_SEEN        = 3000
MAX_ALERTAS_RUN = 15   # máximo de alertas por ejecución (anti-spam)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# ── TÉRMINOS DE BÚSQUEDA ──────────────────────────────────────────────────────
# Separados en grupos para rotar y no lanzar todo cada vez
TERMINOS_GENERICOS = [
    'lote toner', 'lote tinta', 'toner original lote',
    'cartucho original', 'toner precintado', 'toner sin usar',
    'consumibles impresora', 'lote consumibles',
]

TERMINOS_MARCA = [
    'toner hp original', 'toner brother original', 'toner canon original',
    'toner lexmark original', 'toner kyocera original', 'toner ricoh original',
    'toner oki original', 'toner xerox original',
    'lote hp', 'lote brother', 'lote canon', 'lote kyocera', 'lote ricoh',
]

MODELOS_ESPECIFICOS = [
    # Brother
    'TN910', 'TN326', 'TN329', 'TN3520', 'TN423', 'TN426', 'TN245', 'TN247',
    # HP
    'CF410X', 'CE390X', 'CF325X', 'CE505X', 'Q7551X', 'CF283X', 'CE285X', 'CF226X',
    # Lexmark
    'C950X2', '24B6015', 'C792X1', 'C780H1', 'C540H1', 'C544X1', 'C746H1', 'C748H1',
    # Canon
    'CEXV34', 'CEXV33', 'CEXV21', 'CEXV18', 'CEXV14', 'CEXV17', '719H',
    # Kyocera
    'TK8115', 'TK5305', 'TK5240', 'TK3190', 'TK5280', 'TK5270', 'TK1170', 'TK3130',
    # Ricoh
    '407635', '842024', '406482', '406475', '406349', '406052', '407246', '406837',
]

# ── PALABRAS NEGATIVAS ────────────────────────────────────────────────────────
NEGATIVOS = [
    # ES
    'compatible', 'compatibles', 'reciclado', 'reciclados',
    'remanufacturado', 'remanufacturados', 'generico', 'genericos',
    'relleno', 'rellenado', 'rellenar', 'refill', 'chip reset',
    'busco', 'se busca', 'wanted', 'compro', 'busco toner',
    'usado', 'usados', 'vacío', 'vacíos',
    # FR
    'compatible', 'recyclé', 'rechargé', 'remanufacturé',
    'generique', 'cherche', 'recherche',
]

# ── FILTRO DE PRECIO ──────────────────────────────────────────────────────────
PRECIO_MIN = 0     # sin filtro de precio mínimo
PRECIO_MAX = 9999  # sin filtro de precio máximo

# ── HEADERS ───────────────────────────────────────────────────────────────────
HEADERS_BASE = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'es-ES,es;q=0.9',
    'Referer': 'https://es.wallapop.com/',
}

# ── CARGAR/GUARDAR VISTOS ─────────────────────────────────────────────────────
def cargar_vistos():
    if Path(SEEN_FILE).exists():
        try:
            return json.loads(Path(SEEN_FILE).read_text())
        except:
            return {}
    return {}

def guardar_vistos(vistos):
    # Limpiar antiguos si supera el límite
    if len(vistos) > MAX_SEEN:
        ordenados = sorted(vistos.items(), key=lambda x: x[1])
        vistos = dict(ordenados[-MAX_SEEN:])
    Path(SEEN_FILE).write_text(json.dumps(vistos))

# ── FILTROS ───────────────────────────────────────────────────────────────────
def tiene_negativo(titulo):
    tl = titulo.lower()
    return any(neg in tl for neg in NEGATIVOS)

def precio_valido(precio):
    return True  # Sin filtro de precio — Tomás decide

# ── WALLAPOP ──────────────────────────────────────────────────────────────────
def buscar_wallapop(termino):
    url = 'https://api.wallapop.com/api/v3/general/search'
    params = {
        'keywords': termino,
        'language': 'es_ES',
        'filters_source': 'quick_filters',
        'order_by': 'newest',
        'start': 0,
        'step': 20,
    }
    try:
        headers = {**HEADERS_BASE, 'X-AppVersion': '81300'}
        r = requests.get(url, params=params, headers=headers, timeout=12)
        if r.status_code != 200:
            log.warning(f"Wallapop {termino}: HTTP {r.status_code}")
            return []
        data = r.json()
        items = data.get('search_objects', [])
        result = []
        for item in items:
            precio = item.get('price', item.get('sale_price', 0))
            if isinstance(precio, dict):
                precio = precio.get('amount', 0)
            result.append({
                'id': 'wp_' + str(item.get('id', '')),
                'titulo': item.get('title', ''),
                'precio': float(precio) if precio else 0,
                'link': 'https://es.wallapop.com/item/' + str(item.get('web_slug', item.get('id', ''))),
                'plataforma': '🟢 Wallapop',
            })
        return result
    except Exception as e:
        log.error(f"Wallapop error {termino}: {e}")
        return []

# ── VINTED ────────────────────────────────────────────────────────────────────
def obtener_cookies_vinted(dominio):
    try:
        s = requests.Session()
        s.get(f'https://www.{dominio}/', headers=HEADERS_BASE, timeout=10)
        return s.cookies.get_dict()
    except:
        return {}

def buscar_vinted(termino, dominio='vinted.es', cookies=None):
    url = f'https://www.{dominio}/api/v2/catalog/items'
    params = {
        'search_text': termino,
        'order': 'newest_first',
        'per_page': 20,
    }
    try:
        headers = {**HEADERS_BASE, 'Referer': f'https://www.{dominio}/'}
        r = requests.get(url, params=params, headers=headers,
                        cookies=cookies or {}, timeout=12)
        if r.status_code != 200:
            log.warning(f"Vinted {dominio} {termino}: HTTP {r.status_code}")
            return []
        data = r.json()
        items = data.get('items', [])
        emoji = '🔵' if dominio == 'vinted.es' else '🟡'
        nombre = 'Vinted ES' if dominio == 'vinted.es' else 'Vinted PT'
        result = []
        for item in items:
            precio = item.get('price', {})
            if isinstance(precio, dict):
                precio = precio.get('amount', 0)
            result.append({
                'id': f'vt_{dominio}_{item.get("id","")}',
                'titulo': item.get('title', ''),
                'precio': float(precio) if precio else 0,
                'link': item.get('url', f'https://www.{dominio}/items/{item.get("id","")}'),
                'plataforma': f'{emoji} {nombre}',
            })
        return result
    except Exception as e:
        log.error(f"Vinted {dominio} error {termino}: {e}")
        return []

# ── TELEGRAM ──────────────────────────────────────────────────────────────────
def enviar_telegram(texto):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        log.error("Telegram no configurado")
        return False
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    try:
        r = requests.post(url, json={
            'chat_id': TELEGRAM_CHAT,
            'text': texto,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }, timeout=10)
        return r.json().get('ok', False)
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False

def formatear_mensaje(anuncio, termino):
    precio_str = f"💰 {anuncio['precio']:.2f} €" if anuncio['precio'] > 0 else "💰 Precio no indicado"
    return (
        f"{anuncio['plataforma']}\n"
        f"📦 <b>{anuncio['titulo']}</b>\n"
        f"{precio_str}\n"
        f"🔍 <i>{termino}</i>\n"
        f"🔗 <a href=\"{anuncio['link']}\">Ver anuncio →</a>"
    )

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    log.info("=== Recotinta Scanner iniciado ===")
    vistos = cargar_vistos()
    alertas_enviadas = 0

    # Obtener cookies de Vinted una sola vez
    cookies_vinted_es = obtener_cookies_vinted('vinted.es')
    cookies_vinted_pt = obtener_cookies_vinted('vinted.pt')

    # Combinar todos los términos
    todos_terminos = TERMINOS_GENERICOS + TERMINOS_MARCA + MODELOS_ESPECIFICOS

    for termino in todos_terminos:
        if alertas_enviadas >= MAX_ALERTAS_RUN:
            log.info(f"Límite de {MAX_ALERTAS_RUN} alertas alcanzado")
            break

        # Buscar en las tres plataformas
        anuncios = []
        # anuncios += buscar_wallapop(termino)  # Desactivado — HTTP 403 desde GitHub Actions
        anuncios += buscar_vinted(termino, 'vinted.es', cookies_vinted_es)
        anuncios += buscar_vinted(termino, 'vinted.pt', cookies_vinted_pt)

        for anuncio in anuncios:
            if alertas_enviadas >= MAX_ALERTAS_RUN:
                break

            aid = anuncio['id']

            # Saltar si ya visto
            if aid in vistos:
                continue

            # Marcar como visto siempre (aunque filtremos)
            vistos[aid] = int(time.time())

            # Filtros
            if not anuncio['titulo']:
                continue
            if tiene_negativo(anuncio['titulo']):
                log.info(f"Filtrado negativo: {anuncio['titulo'][:50]}")
                continue
            if not precio_valido(anuncio['precio']):
                log.info(f"Filtrado precio ({anuncio['precio']}€): {anuncio['titulo'][:50]}")
                continue

            # Enviar alerta
            log.info(f"NUEVO anuncio: [{anuncio['plataforma']}] {anuncio['titulo'][:50]} — {anuncio['precio']}€")
            msg = formatear_mensaje(anuncio, termino)
            if enviar_telegram(msg):
                alertas_enviadas += 1
                log.info(f"✅ Telegram enviado: {anuncio['titulo'][:50]}")
                time.sleep(0.5)  # pausa anti-spam Telegram
            else:
                log.error(f"❌ Telegram FALLÓ: {anuncio['titulo'][:50]}")

        # Pausa entre búsquedas
        time.sleep(0.8)

    guardar_vistos(vistos)
    log.info(f"=== Fin: {alertas_enviadas} alertas enviadas ===")

if __name__ == '__main__':
    main()
