#!/usr/bin/env python3
"""
Transform Alkosto product records into the Philipp_Alkosto_AI index schema.

Schema reference: 2026-06-05-algolia-index-schema.md.
- Filters to laptop, desktop, all_in_one, tablet.
- Stores every measurable spec twice: a clean numeric value for filtering /
  ranking, plus a human-readable label for display (e.g. ram_gb=16, ram_label="16 GB").
- Conservative on booleans: only emits a field when the source text contains a
  clear keyword signal. Otherwise omits the field — never fabricates.
"""

import argparse
import json
import re
import sys


# --- Generic value parsing ---

def _first_number(value):
    if not isinstance(value, str):
        return None
    m = re.search(r'(\d+(?:[.,]\d+)?)', value)
    if not m:
        return None
    return float(m.group(1).replace(',', '.'))


def parse_ram(raw):
    n = _first_number(raw)
    if not n or n <= 0:
        return None, None
    return int(n), f"{int(n)} GB"


def parse_storage(raw):
    """'Estado Solido SSD 512 GB' → (512, '512 GB SSD');  '1 TB' → (1024, '1 TB SSD')."""
    if not isinstance(raw, str):
        return None, None
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(GB|TB|MB)', raw, re.IGNORECASE)
    if not m:
        return None, None
    n = float(m.group(1).replace(',', '.'))
    unit = m.group(2).upper()
    gb = int(n * 1024) if unit == 'TB' else int(n)
    is_ssd = 'SSD' in raw.upper() or 'SOLID' in raw.upper()
    n_disp = int(n) if n == int(n) else n
    label = f"{n_disp} {unit}" + (' SSD' if is_ssd else '')
    return gb, label


def parse_screen(raw):
    n = _first_number(raw)
    if not n or n <= 0:
        return None, None
    n_disp = int(n) if n == int(n) else round(n, 1)
    return n, f'{n_disp}"'


def parse_weight(raw):
    """'1.23 Kilogramos' → (1.23, '1.23 kg').  '850 Gramos' → (0.85, '850 g')."""
    n = _first_number(raw)
    if n is None or not isinstance(raw, str):
        return None, None
    is_g = 'gramo' in raw.lower() and 'kilo' not in raw.lower()
    kg = round(n / 1000, 3) if is_g else round(n, 3)
    n_disp = int(n) if n == int(n) else n
    label = f'{n_disp} g' if is_g else f'{n_disp} kg'
    return kg, label


def parse_battery(raw):
    n = _first_number(raw)
    if n is None or n <= 0:
        return None, None
    return int(n), f'{int(n)} h'


def parse_cores(raw):
    n = _first_number(raw)
    return int(n) if n else None


def parse_os(raw):
    if not isinstance(raw, str):
        return None
    s = raw.lower()
    if 'ipad' in s: return 'ipados'
    if 'macos' in s or 'mac os' in s: return 'macos'
    if 'windows' in s: return 'windows'
    if 'android' in s: return 'android'
    if 'chrome' in s: return 'chromeos'
    return None


def parse_cpu_brand(marca, procesador):
    s = ' '.join(x for x in (marca, procesador) if isinstance(x, str)).lower()
    if not s:
        return None
    if 'intel' in s: return 'intel'
    if 'amd' in s: return 'amd'
    if 'apple' in s: return 'apple'
    if 'snapdragon' in s or 'qualcomm' in s: return 'snapdragon'
    if 'mediatek' in s: return 'mediatek'
    return None


def parse_gpu_brand(marca):
    if not isinstance(marca, str):
        return None
    s = marca.lower()
    if 'no tiene' in s or 'no posee' in s:
        return 'none'
    if 'nvidia' in s: return 'nvidia'
    if 'amd' in s or 'radeon' in s: return 'amd'
    if 'intel' in s: return 'intel'
    return None


def parse_category(record):
    cat = record.get('Categoría', '') or ''
    titulo = (record.get('Título') or '').lower()
    if 'Tabletas' in cat:
        return 'tablet'
    if 'Portátiles' in cat:
        return 'laptop'
    if 'Escritorio' in cat or 'All in One' in cat:
        if 'all in one' in titulo or 'all-in-one' in titulo or ' aio ' in f' {titulo} ':
            return 'all_in_one'
        return 'desktop'
    return None


def format_cop(n):
    if not isinstance(n, (int, float)):
        return None
    return f'$ {int(n):,}'.replace(',', '.')


# --- Boolean detection: conservative (only set True when signal is clear) ---

def _haystack(record):
    parts = []
    for k in ('Título', 'Características', 'Caracteristicas Especiales',
              'Caracteristicas del Teclado', 'Qué incluye el producto'):
        v = record.get(k)
        if isinstance(v, str):
            parts.append(v)
    for i in range(1, 6):
        v = record.get(f'Caracteristica claves_{i}')
        if isinstance(v, str):
            parts.append(v)
    return ' '.join(parts).lower()


_AI_PAT = re.compile(r'\bcopilot\b|copilot\+|inteligencia artificial|\bai pc\b|snapdragon x', re.IGNORECASE)
_TOUCH_PAT = re.compile(r'\btáctil\b|\btactil\b|touchscreen|touch screen|multi-?touch', re.IGNORECASE)
_FINGERPRINT_PAT = re.compile(r'huella(?:s)?\b|lector(?:\s+de)?\s+huellas?|fingerprint|reconocimiento.{0,15}(?:dactilar|huella)', re.IGNORECASE)
_BACKLIT_PAT = re.compile(r'retroilumina|teclado iluminado|backlit', re.IGNORECASE)
_WEBCAM_PAT = re.compile(r'\bwebcam\b|cámara (?:web|fhd|hd)|camara (?:web|fhd|hd)|hd camera', re.IGNORECASE)
_CONVERTIBLE_PAT = re.compile(r'\bconvertible\b|2 en 1|2-en-1', re.IGNORECASE)


def _has_signal(record, pattern):
    if pattern.search(_haystack(record)):
        return True
    return None


def detect_is_convertible(record):
    # Do NOT key off the Categoría path: the umbrella subcategory is literally
    # "Portátiles Laptops y Convertibles 2 en 1", so its name matches every
    # plain laptop. Use only title/feature keyword evidence.
    return _has_signal(record, _CONVERTIBLE_PAT)


# --- Main transform ---

INCLUDED_CATEGORIES = {'laptop', 'desktop', 'all_in_one', 'tablet'}


def transform(record):
    category = parse_category(record)
    if category not in INCLUDED_CATEGORIES:
        return None

    out = {}

    def put(k, v):
        if v is not None and v != '':
            out[k] = v

    # Identity + display
    put('objectID', str(record.get('Identificador del producto') or ''))
    put('name', record.get('Título'))
    put('url', record.get('Enlace del producto'))
    put('image_url', record.get('Enlace link1'))
    put('brand', record.get('Marca'))
    put('category', category)

    # Price
    price_sale = record.get('Precio de venta')
    price_list = record.get('Precio de lista')
    put('price_sale', price_sale)
    put('price_list', price_list)
    put('price_sale_label', format_cop(price_sale))
    put('discount_pct', record.get('descuento_porcentaje'))

    # Numeric specs + display labels
    ram_gb, ram_label = parse_ram(record.get('Memoria RAM'))
    put('ram_gb', ram_gb); put('ram_label', ram_label)
    storage_gb, storage_label = parse_storage(record.get('Capacidad de Disco'))
    put('storage_gb', storage_gb); put('storage_label', storage_label)
    screen_inches, screen_label = parse_screen(record.get('Tamaño Pantalla_1'))
    put('screen_inches', screen_inches); put('screen_label', screen_label)
    weight_kg, weight_label = parse_weight(record.get('Peso'))
    put('weight_kg', weight_kg); put('weight_label', weight_label)
    battery_hours, battery_label = parse_battery(record.get('Duracion de la Bateria'))
    put('battery_hours', battery_hours); put('battery_label', battery_label)
    put('cpu_cores', parse_cores(record.get('Número de Núcleos (más núcleos más multitareas)')))

    # OS / CPU / GPU enums
    put('os', parse_os(record.get('Sistema Operativo')))
    cpu_brand = parse_cpu_brand(record.get('Marca del Procesador'), record.get('Procesador'))
    put('cpu_brand', cpu_brand)
    put('cpu_model', record.get('Modelo del Procesador'))
    gpu_brand = parse_gpu_brand(record.get('Marca Tarjeta de Video/Grafica'))
    put('gpu_brand', gpu_brand)
    gpu_model = record.get('Modelo Tarjeta de Video/Grafica')
    if isinstance(gpu_model, str) and 'no tiene' not in gpu_model.lower():
        put('gpu_model', gpu_model)
    if gpu_brand is not None:
        out['has_dedicated_gpu'] = gpu_brand in ('nvidia', 'amd')

    # Conservative booleans
    put('has_ai', _has_signal(record, _AI_PAT))
    put('is_convertible', detect_is_convertible(record))
    put('is_touchscreen', _has_signal(record, _TOUCH_PAT))
    put('has_fingerprint', _has_signal(record, _FINGERPRINT_PAT))
    put('backlit_keyboard', _has_signal(record, _BACKLIT_PAT))
    put('has_webcam', _has_signal(record, _WEBCAM_PAT))

    # Availability
    stock = record.get('Disponibilidad')
    if isinstance(stock, (int, float)):
        out['stock'] = int(stock)
        out['in_stock'] = int(stock) > 0

    # Soft context
    short_parts = []
    if ram_label:
        short_parts.append(f'{ram_label} RAM')
    proc = record.get('Procesador') or record.get('Modelo del Procesador')
    if isinstance(proc, str) and proc.strip():
        short_parts.append(proc.strip())
    if storage_label:
        short_parts.append(storage_label)
    if screen_label:
        short_parts.append(screen_label)
    if short_parts:
        out['short_specs'] = ' | '.join(short_parts)

    key_features = [
        record.get(f'Caracteristica claves_{i}') for i in range(1, 6)
    ]
    key_features = [k.strip() for k in key_features if isinstance(k, str) and k.strip()]
    if key_features:
        out['key_features'] = key_features

    desc = record.get('Características')
    if isinstance(desc, str) and desc.strip():
        out['description'] = desc.strip()

    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True, help='Path to filtered_products.json')
    p.add_argument('--output', required=True, help='Path to write the transformed JSON')
    args = p.parse_args()

    with open(args.input, encoding='utf-8') as f:
        records = json.load(f)

    out = [t for t in (transform(r) for r in records) if t is not None]

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f'✓ {len(out)} of {len(records)} records → {args.output}')


if __name__ == '__main__':
    main()
