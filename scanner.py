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
MAX_ALERTAS_RUN = 50   # máximo de alertas por ejecución

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# ── TÉRMINOS DE BÚSQUEDA ──────────────────────────────────────────────────────
# Wallapop: sin filtro de categoría, términos directos
TERMINOS_WALLAPOP = [
    # Confirmados por Tomás
    'toner', 'cartucho', 'laserjet',
    # Genéricos
    'lote toner', 'toner original', 'cartucho original', 'tambor impresora',
    # Por marca
    'toner hp', 'toner brother', 'toner canon', 'toner lexmark',
    'toner kyocera', 'toner ricoh', 'toner oki', 'toner xerox',
    'lote hp', 'lote brother', 'lote canon', 'lote lexmark',
    # Modelos Brother
    'TN910', 'TN326', 'TN3520', 'TN423', 'TN426', 'TN247',
    # Modelos HP
    'CF410X', 'CE390X', 'CF325X', 'CE505X', 'CF283X', 'CF226X',
    # Modelos Lexmark
    'C950X2', 'C792X1', 'C780H1', 'C746H1', 'C748H1',
    # Modelos Canon
    'CEXV34', 'CEXV33', 'CEXV21', 'CEXV18', 'CEXV14',
    # Modelos Kyocera
    'TK8115', 'TK5305', 'TK5240', 'TK5280', 'TK1170',
    # Modelos Ricoh
    '407635', '842024', '406482', '406349',
]

# Vinted: sin filtro de categoría — catalog_ids eliminados porque los IDs
# disponibles públicamente no corresponden a la categoría correcta y
# fuerzan resultados de otras familias (ropa, moda...)
# Los términos específicos + palabras negativas son suficiente filtro
TERMINOS_VINTED = [
    # Genéricos — suficientemente específicos para impresión
    'toner', 'toner original', 'toner impresora',
    'toner hp', 'toner brother', 'toner canon',
    'toner kyocera', 'toner ricoh', 'toner xerox', 'toner lexmark',
    'cartucho impresora', 'lote toner', 'lote cartuchos',
    'tambor impresora',
    # Modelos específicos — inequívocos
    'CF410X', 'CF226X', 'CE505X', 'CF283X',
    'TN910', 'TN3520', 'TK5240', 'TK8115', 'TK5305',
    'C950X2', 'CEXV34', '407635',
]

# ── PALABRAS NEGATIVAS ────────────────────────────────────────────────────────
NEGATIVOS = [
    # Consumibles no originales
    'compatible', 'compatibles', 'reciclado', 'reciclados',
    'remanufacturado', 'remanufacturados', 'generico', 'genericos',
    'relleno', 'rellenado', 'rellenar', 'refill', 'chip reset',
    'busco', 'se busca', 'wanted', 'compro', 'busco toner',
    'usado', 'usados', 'vacío', 'vacíos',
    # Ropa y moda
    'ropa', 'camiseta', 'pantalon', 'pantalón', 'vestido', 'camisa',
    'blusa', 'chaqueta', 'abrigo', 'zapatos', 'zapatillas', 'bolso',
    'moda', 'outfit', 'jersey', 'falda', 'sudadera', 'vaqueros',
    'prendas', 'tallas', 'kiabi', 'zara', 'h&m', 'mango',
    'bebé', 'bebe', 'niño', 'nino', 'infantil',
    # Cosmética y belleza
    'belleza', 'cosmetica', 'cosmética', 'crema', 'serum', 'sérum',
    'maquillaje', 'perfume', 'colonia', 'labial', 'capilar',
    'skincare', 'beauty', 'tónico facial', 'tonico facial',
    'mascarilla', 'hidratante', 'acondicionador',
    # Arte y hobby
    'acuarela', 'pintura', 'oleo', 'óleo', 'scrapbooking',
    'yugioh', 'yu-gi-oh', 'pokemon', 'carta ', 'cartas ',
    'boosters', 'booster', 'figuras', 'pegatinas',
    # Hogar y otros
    'copas', 'cristal', 'libro', 'libros', 'sorpresa', 'misterio',
    'jogging', 'streetwear', 'vintage tela', 'tela ',
    'camisolas', 'bodys', 'conjuntos ropa',
    # Cosmética — toner facial / tónico
    'tónico', 'tonico', 'facial', 'skincare', 'k-beauty', 'kbeauty',
    'coreano', 'coreana', 'arroz', 'hair', 'cabello', 'pelo',
    'micellar', 'hidratacion', 'hidratación', 'esencia toner',
    'rice toner', 'barrier', 'glazer', 'pyunkang', 'revuele',
    'sibari', 'kiehl', 'sisley', 'loreal', 'loreal',
    'schwarzkopf', 'naturtint', 'decoloracion', 'decoloración',
    'tinte pelo', 'tinte cabello', 'tintes peluqueria',
    'neceser', 'muestras', 'muestra ',
    # Videojuegos y electrónica
    'nintendo', 'switch', 'gameboy', 'game boy', 'sega',
    'famicom', 'gba', '3ds', 'sonic', 'kirby', 'dragon ball',
    'mahjong', 'aladdin', 'rayman', 'astroboy', 'pokémon',
    'pokemon', 'mega drive', 'super famicom', 'microfono',
    'micrófono', 'camara', 'cámara', 'philips lumea',
    # FR
    'recyclé', 'rechargé', 'remanufacturé', 'generique',
    'cherche', 'recherche', 'vetement', 'vêtement', 'robe',
    'ensemble bébé', 'pièces fille', 'pull ', 'blouse ',
    'boutons couture', 'pellicule', 'porte-clés',
    # Videojuegos
    'cartucho juego', 'cartucho nintendo', 'cartucho sega',
    'cartucho gba', 'cartucho nds', 'cartucho n64',
    'playstation', 'ps1', 'ps2', 'ps3', 'ps4', 'ps5',
    'xbox', 'game boy', 'gameboy', 'nds', 'gba', 'n64',
    'snes', 'nes ', 'mega drive', 'master system',
    'retro juego', 'videojuego', 'video juego',
    # Móviles y fundas — "lote kyocera" da móviles
    'funda', 'fundas', 'carcasa', 'movil', 'móvil', 'smartphone',
    'iphone', 'samsung', 'nokia', 'motorola', 'huawei', 'xiaomi',
    'telefono', 'teléfono', 'tablet',
    # Moda adicional
    'cazadora', 'esquí', 'esqui', 'chaqueta esqui',
    'deportiva', 'running', 'trekking', 'ciclismo',
    # Precios absurdos (señal de artículo incorrecto)
    # No filtramos por precio pero añadimos palabras clave
    'decoracion', 'decoración', 'cuadro', 'lampara', 'lámpara',
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

# ── PALABRAS QUE DEBEN APARECER EN EL TÍTULO ────────────────────────────────
# Si el título no contiene ninguna de estas palabras, el anuncio se descarta
# Esto evita que artículos de ropa/cosmética aparezcan por estar en la descripción
POSITIVOS_TITULO = [
    # Tipos de consumible
    'toner', 'tóner', 'tonner', 'cartucho', 'cartuchos',
    'tambor', 'drum', 'fusor', 'fuser', 'inkjet', 'laserjet',
    # Marcas de impresión (solo relevantes en contexto de toners)
    'hp laserjet', 'brother tn', 'brother dr', 'canon cexv',
    'kyocera tk', 'ricoh', 'lexmark', 'xerox',
    # Modelos específicos — si aparecen en título es 100% relevante
    'cf226', 'cf410', 'ce505', 'cf283', 'ce390',
    'tn910', 'tn326', 'tn3520', 'tn423', 'tn247',
    'tk8115', 'tk5305', 'tk5240', 'tk5280', 'tk1170',
    'c950x2', 'cexv34', 'cexv33', 'cexv21',
    '407635', '842024', '406482',
    # Términos de lote/impresión
    'lote toner', 'lote cartuchos', 'lote consumibles',
    'impresora original', 'consumible',
]

# ── FILTROS ───────────────────────────────────────────────────────────────────
def tiene_negativo(texto):
    tl = texto.lower()
    return any(neg in tl for neg in NEGATIVOS)

def titulo_es_relevante(titulo):
    """Verifica que el título contiene al menos una palabra de impresión.
    Evita que artículos de ropa/cosmética pasen por estar en la descripción."""
    tl = titulo.lower()
    return any(pos in tl for pos in POSITIVOS_TITULO)

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
            # Extraer URL de imagen
            foto = ''
            photo = item.get('photo', {})
            if isinstance(photo, dict):
                foto = photo.get('full_size_url', photo.get('url', ''))
            result.append({
                'id': f'vt_{item.get("id","")}',  # sin dominio para evitar duplicados ES/PT
                'titulo': item.get('title', ''),
                'descripcion': item.get('description', ''),
                'precio': float(precio) if precio else 0,
                'link': item.get('url', f'https://www.{dominio}/items/{item.get("id","")}'),
                'plataforma': f'{emoji} {nombre}',
                'foto': foto,
            })
        return result
    except Exception as e:
        log.error(f"Vinted {dominio} error {termino}: {e}")
        return []

# ── TELEGRAM ──────────────────────────────────────────────────────────────────
def enviar_telegram(texto, foto_url=''):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        log.error("Telegram no configurado")
        return False
    try:
        if foto_url:
            # Enviar foto con caption
            url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto'
            r = requests.post(url, json={
                'chat_id': TELEGRAM_CHAT,
                'photo': foto_url,
                'caption': texto,
                'parse_mode': 'HTML',
            }, timeout=10)
            result = r.json()
            if result.get('ok'):
                return True
            # Si falla la foto, enviar solo texto
        # Enviar solo texto
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
        r = requests.post(url, json={
            'chat_id': TELEGRAM_CHAT,
            'text': texto,
            'parse_mode': 'HTML',
            'disable_web_page_preview': False,
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

    # ── Wallapop (desactivado — HTTP 403 desde GitHub Actions) ──────────────
    # for termino in TERMINOS_WALLAPOP:
    #     if alertas_enviadas >= MAX_ALERTAS_RUN: break
    #     anuncios = buscar_wallapop(termino)
    #     ... procesar anuncios

    # ── Vinted ────────────────────────────────────────────────────────────────
    for termino in TERMINOS_VINTED:
        if alertas_enviadas >= MAX_ALERTAS_RUN:
            log.info(f"Límite de {MAX_ALERTAS_RUN} alertas alcanzado")
            break

        anuncios = []
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

            # 1. El TÍTULO debe contener una palabra de impresión
            # (evita ropa/cosmética que tiene "toner" en la descripción)
            if not titulo_es_relevante(anuncio['titulo']):
                log.info(f"Título irrelevante: {anuncio['titulo'][:60]}")
                continue

            # 2. Negativos en título Y descripción
            texto_completo = anuncio['titulo'] + ' ' + anuncio.get('descripcion', '')
            if tiene_negativo(texto_completo):
                log.info(f"Filtrado negativo: {anuncio['titulo'][:50]}")
                continue

            if not precio_valido(anuncio['precio']):
                log.info(f"Filtrado precio ({anuncio['precio']}€): {anuncio['titulo'][:50]}")
                continue

            # Enviar alerta
            msg = formatear_mensaje(anuncio, termino)
            if enviar_telegram(msg, anuncio.get('foto', '')):
                alertas_enviadas += 1
                log.info(f"✅ {anuncio['plataforma']} — {anuncio['titulo'][:50]} — {anuncio['precio']}€")
                time.sleep(1.5)  # pausa anti-spam Telegram
            else:
                log.error(f"❌ Telegram falló: {anuncio['titulo'][:50]}")

        # Pausa entre búsquedas
        time.sleep(0.8)

    guardar_vistos(vistos)
    log.info(f"=== Fin: {alertas_enviadas} alertas enviadas ===")

if __name__ == '__main__':
    main()
