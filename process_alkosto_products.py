#!/usr/bin/env python3
"""
Script to download, filter, clean, and convert Alkosto product CSV to JSON.
"""

import csv
import json
import re
import requests
from requests.auth import HTTPBasicAuth
import pandas as pd
import sys
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration
CSV_URL = "https://www.alkosto.com/alkostows/integration/datafeedfull/productFeed.csv"
OUTPUT_CSV = "filtered_products.csv"
OUTPUT_JSON = "filtered_products.json"

# Filter: include everything whose category starts with any of these prefixes,
# except the explicit subcategory exclusions. Trailing '>' on each prefix is
# required so we match category-tree nodes and not arbitrary substrings.
CATEGORY_PREFIXES = [
    "Computadores y Tablet>",
    "TV>Smart TV>",
    "Celulares>Smartphones>",
    "Electrodomésticos>Refrigeración>",
    "Electrodomésticos>Lavado>",
    "Electrodomésticos>Climatización>",
    "Electrodomésticos>Cocina>",
    "Electrodomésticos>Pequeños Electrodomésticos>",
    "Audio>",
    "Videojuegos>",
    "Smartwatch>",
    "Cámaras>",
    "Casa Inteligente - Domótica>",
    "Accesorios de Electrónica>",
]
EXCLUDED_SUBCATEGORIES = []

# Derived 'tipo_producto' field — maps a category-tree prefix to a short type
# label. Used by Algolia Rules so query routing doesn't depend on enumerating
# brand-level paths. Order matters: first matching prefix wins, so list the
# longest/most-specific first (e.g. 'Impresión>Resmas Papel' must come before
# the generic 'Impresión>' fallback).
TIPO_PRODUCTO_PREFIXES = [
    ("TV>Smart TV>", "televisor"),
    ("Celulares>Smartphones>", "celular"),
    ("Computadores y Tablet>Computadores Portátiles>", "laptop"),
    ("Computadores y Tablet>Computadores Escritorio y All in One", "desktop"),
    ("Computadores y Tablet>Tabletas y iPads", "tablet"),
    ("Computadores y Tablet>Monitores", "monitor"),
    ("Computadores y Tablet>Impresión>Resmas Papel", "papel"),
    ("Computadores y Tablet>Impresión>Tintas, Tóner y Cartuchos", "tinta"),
    ("Computadores y Tablet>Impresión>", "impresora"),
    ("Electrodomésticos>Refrigeración>Nevecones", "nevecon"),
    ("Electrodomésticos>Refrigeración>Neveras", "nevera"),
    ("Electrodomésticos>Refrigeración>Congeladores", "congelador"),
    ("Electrodomésticos>Refrigeración>Vineras, Minibares y Mini Neveras", "vinera_minibar"),
    ("Electrodomésticos>Refrigeración>Dispensadores Agua", "dispensador_agua"),
    ("Electrodomésticos>Refrigeración>Máquinas Fabricadoras Hielo", "fabricador_hielo"),
    ("Electrodomésticos>Lavado>Lavadora-Secadora y Torres", "lavadora_secadora"),
    ("Electrodomésticos>Lavado>Lavadoras", "lavadora"),
    ("Electrodomésticos>Lavado>Secadoras", "secadora"),
    ("Computadores y Tablet>Proyectores y Videobeam", "proyector"),
    # Audio
    ("Audio>Audio Para el Hogar>Amplificadores", "amplificador"),
    ("Audio>Audio Para el Hogar>Barras de Sonido", "barra_sonido"),
    ("Audio>Audio Para el Hogar>Equipos de Sonido", "equipo_sonido"),
    ("Audio>Audio Para el Hogar>Parlantes y Subwoofer", "parlante"),
    ("Audio>Audífonos", "audifono"),
    ("Audio>Car Audio", "car_audio"),
    ("Audio>Radios, Reproductores y Grabadoras", "radio"),
    # Climatización
    ("Electrodomésticos>Climatización>Aires Acondicionados", "aire_acondicionado"),
    ("Electrodomésticos>Climatización>Calentadores", "calentador"),
    ("Electrodomésticos>Climatización>Duchas Eléctricas", "ducha_electrica"),
    ("Electrodomésticos>Climatización>Ventiladores y Calefactores", "ventilador"),
    # Cocina (piso/mesa + empotre)
    ("Electrodomésticos>Cocina>Estufas de Piso y Mesa", "estufa"),
    ("Electrodomésticos>Cocina>Línea de Empotre>Campanas Extractoras", "campana"),
    ("Electrodomésticos>Cocina>Línea de Empotre>Estufas de empotrar", "estufa_empotrar"),
    ("Electrodomésticos>Cocina>Línea de Empotre>Hornos de Empotrar", "horno_empotrar"),
    ("Electrodomésticos>Cocina>Línea de Empotre>Lavavajillas", "lavavajillas"),
    # Pequeños electrodomésticos > Cuidado del Hogar
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado del Hogar>Aspiradoras", "aspiradora"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado del Hogar>Aspiradoras Inalámbricas", "aspiradora"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado del Hogar>Aspiradoras Robóticas", "aspiradora"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado del Hogar>Aspiradoras de Canasta", "aspiradora"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado del Hogar>Combos del Hogar", "combo_hogar"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado del Hogar>Hidrolavadoras", "hidrolavadora"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado del Hogar>Maquinas Coser", "maquina_coser"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado del Hogar>Planchas Ropa", "plancha_ropa"),
    # Pequeños electrodomésticos > Cuidado Personal
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado Personal>Afeitadoras y Depiladoras", "afeitadora"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado Personal>Combos de Cuidado Personal", "combo_personal"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado Personal>Cuidado Dental", "cuidado_dental"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado Personal>Masajeadores", "masajeador"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado Personal>Otros Productos de Salud y Bienestar", "salud_bienestar"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado Personal>Planchas y Cepillos de aire", "plancha_cabello"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Cuidado Personal>Secadores de Cabello", "secador_cabello"),
    # Pequeños electrodomésticos > Preparación de Alimentos
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Batidoras", "batidora"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Cafeteras Expresso", "cafetera"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Cafeteras de Goteo", "cafetera"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Combos de Preparación de Alimentos", "combo_preparacion"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Exprimidores y Extractores Jugos", "exprimidor"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Freidoras de Aire", "freidora_aire"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Hornos Tostadores", "horno_tostador"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Licuadoras", "licuadora"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Microondas", "microondas"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Ollas Arroceras", "olla_arrocera"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Ollas Multifuncionales", "olla_multifuncional"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Otros Productos de Preparación", "otro_preparacion"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Planchas y Sartenes Eléctricos", "plancha_sarten"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Procesador de Alimentos", "procesador_alimentos"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Sandwicheras y Wafleras", "sandwichera"),
    ("Electrodomésticos>Pequeños Electrodomésticos>Preparación de Alimentos>Tostadoras", "tostadora"),
    # Videojuegos (agrupados por función)
    ("Videojuegos>Consolas>Consolas Nintendo", "consola"),
    ("Videojuegos>Consolas>Consolas Otras Plataformas", "consola"),
    ("Videojuegos>Consolas>Consolas PlayStation", "consola"),
    ("Videojuegos>Juegos>Juegos Nintendo", "juego"),
    ("Videojuegos>Juegos>Juegos PlayStation", "juego"),
    ("Videojuegos>Juegos>Juegos Xbox", "juego"),
    ("Videojuegos>Accesorios Videojuegos>Accesorios Nintendo", "accesorio_videojuego"),
    ("Videojuegos>Accesorios Videojuegos>Accesorios PlayStation", "accesorio_videojuego"),
    ("Videojuegos>Accesorios Videojuegos>Accesorios Xbox", "accesorio_videojuego"),
    ("Videojuegos>Accesorios Videojuegos>Accesorios para Otras Plataformas", "accesorio_videojuego"),
    ("Videojuegos>Coleccionables>Figuras Coleccionables", "figura_coleccionable"),
    # Smartwatch
    ("Smartwatch>Relojes Inteligentes", "smartwatch"),
    ("Smartwatch>Bandas de Actividad", "banda_actividad"),
    # Cámaras
    ("Cámaras>Cámaras Fotográficas", "camara"),
    ("Cámaras>Cámaras de Acción", "camara_accion"),
    ("Cámaras>Drones", "dron"),
    # Casa Inteligente - Domótica
    ("Casa Inteligente - Domótica>Cerraduras Inteligentes", "cerradura_smart"),
    ("Casa Inteligente - Domótica>Cámaras Seguridad", "camara_seguridad"),
    ("Casa Inteligente - Domótica>Iluminación y Electricidad>Bombillos Inteligentes", "bombillo_smart"),
    ("Casa Inteligente - Domótica>Iluminación y Electricidad>Multitomas Inteligentes", "multitoma_smart"),
    ("Casa Inteligente - Domótica>Iluminación y Electricidad>Switches Inteligentes", "switch_smart"),
    ("Casa Inteligente - Domótica>Iluminación y Electricidad>Tomacorrientes Inteligentes", "tomacorriente_smart"),
    ("Casa Inteligente - Domótica>Otros Dispositivos Inteligentes", "otro_smart"),
    ("Casa Inteligente - Domótica>Redes Y WiFi>Extensores Señal", "extensor_wifi"),
    ("Casa Inteligente - Domótica>Redes Y WiFi>Routers", "router"),
    ("Casa Inteligente - Domótica>Redes Y WiFi>Switches de Red", "switch_red"),
    ("Casa Inteligente - Domótica>Sensores", "sensor_smart"),
    # Accesorios de Electrónica > Audio
    ("Accesorios de Electrónica>Accesorios Audio>Bases Parlantes", "accesorio_audio"),
    ("Accesorios de Electrónica>Accesorios Audio>Cover, Estuches y Maletines Audio", "accesorio_audio"),
    ("Accesorios de Electrónica>Accesorios Audio>Micrófonos", "microfono"),
    ("Accesorios de Electrónica>Accesorios Audio", "accesorio_audio"),
    # Accesorios de Electrónica > Celulares/Tabletas
    ("Accesorios de Electrónica>Accesorios Celulares y Tabletas>Carcasas, Estuches Y Protectores", "carcasa_celular"),
    ("Accesorios de Electrónica>Accesorios Celulares y Tabletas>Otros Accesorios Celular-Tablet", "accesorio_celular"),
    # Accesorios de Electrónica > Computadores > Gaming (agrupados)
    ("Accesorios de Electrónica>Accesorios Computadores>Accesorios Gaming>Audifonos y Parlantes Gamers", "accesorio_gaming_pc"),
    ("Accesorios de Electrónica>Accesorios Computadores>Accesorios Gaming>Controles PC Gaming", "accesorio_gaming_pc"),
    ("Accesorios de Electrónica>Accesorios Computadores>Accesorios Gaming>Micrófonos Gamers", "accesorio_gaming_pc"),
    ("Accesorios de Electrónica>Accesorios Computadores>Accesorios Gaming>Morrales y Maletines Gamers", "accesorio_gaming_pc"),
    ("Accesorios de Electrónica>Accesorios Computadores>Accesorios Gaming>Mouse y Pad Mouse Gamers", "accesorio_gaming_pc"),
    ("Accesorios de Electrónica>Accesorios Computadores>Accesorios Gaming>Teclados Gamers", "accesorio_gaming_pc"),
    ("Accesorios de Electrónica>Accesorios Computadores>Accesorios Gaming>Timones y Palancas Gamers", "accesorio_gaming_pc"),
    # Accesorios de Electrónica > Computadores > (otros)
    ("Accesorios de Electrónica>Accesorios Computadores>Discos Duros", "disco_duro"),
    ("Accesorios de Electrónica>Accesorios Computadores>Maletines, Morrales y Fundas", "maletin_computador"),
    # Accesorios de Electrónica > Periféricos
    ("Accesorios de Electrónica>Accesorios Computadores>Periféricos>Apuntadores, Presentadores", "apuntador"),
    ("Accesorios de Electrónica>Accesorios Computadores>Periféricos>Combos de Periféricos", "combo_periferico"),
    ("Accesorios de Electrónica>Accesorios Computadores>Periféricos>HUB", "hub"),
    ("Accesorios de Electrónica>Accesorios Computadores>Periféricos>Mouse", "mouse"),
    ("Accesorios de Electrónica>Accesorios Computadores>Periféricos>Parlantes Computadores", "parlante_computador"),
    ("Accesorios de Electrónica>Accesorios Computadores>Periféricos>Soportes y Bases Para Computador", "soporte_computador"),
    ("Accesorios de Electrónica>Accesorios Computadores>Periféricos>Tabletas Digitalizadoras", "tableta_digitalizadora"),
    ("Accesorios de Electrónica>Accesorios Computadores>Periféricos>Teclados", "teclado"),
    ("Accesorios de Electrónica>Accesorios Computadores>Periféricos>Webcam", "webcam"),
    # Accesorios de Electrónica > Cámaras / Deportes / TV / General
    ("Accesorios de Electrónica>Accesorios Cámaras", "accesorio_camara"),
    ("Accesorios de Electrónica>Accesorios Para Deporte y Salud", "accesorio_deporte"),
    ("Accesorios de Electrónica>Accesorios Tv y Video>Antenas", "antena_tv"),
    ("Accesorios de Electrónica>Accesorios Tv y Video>Bases y Soportes Tv", "soporte_tv"),
    ("Accesorios de Electrónica>Accesorios Tv y Video>Decodificadores", "decodificador"),
    ("Accesorios de Electrónica>Baterías Externas PowerBank", "powerbank"),
    ("Accesorios de Electrónica>Cables, Cargadores, Adaptadores", "cable_cargador"),
    ("Accesorios de Electrónica>Pilas Recargables", "pila"),
    ("Accesorios de Electrónica>Reguladores Voltaje, UPS, Multitomas", "ups"),
    ("Accesorios de Electrónica>USB y Tarjetas de Memoria", "memoria_usb"),
]


def download_csv(url, username, password, output_file="productFeed.csv"):
    """
    Download CSV from password-protected URL using Basic Auth.
    """
    print(f"Downloading CSV from {url}...")
    try:
        response = requests.get(
            url,
            auth=HTTPBasicAuth(username, password),
            timeout=60
        )
        response.raise_for_status()

        with open(output_file, 'wb') as f:
            f.write(response.content)

        print(f"✓ CSV downloaded successfully to {output_file}")
        return output_file
    except requests.exceptions.RequestException as e:
        print(f"✗ Error downloading CSV: {e}")
        sys.exit(1)


def filter_by_categories(input_file, prefixes, excluded, output_file):
    """
    Filter CSV rows: keep everything whose category starts with any of the
    given prefixes, minus the excluded full subcategory paths.
    """
    print(f"Filtering products by categories...")

    # Read CSV with pandas, handling encoding properly
    # Force product ID to string so SKUs that start with '0' keep their leading
    # zeros. Without this, pandas types the column as int64 and silently drops
    # the leading 0 (breaks the EAN itself and the derived CDN image URLs).
    sku_dtype = {'Identificador del producto': str}
    try:
        df = pd.read_csv(input_file, low_memory=False, encoding='utf-8', dtype=sku_dtype)
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(input_file, low_memory=False, encoding='latin-1', dtype=sku_dtype)
        except Exception as e:
            print(f"✗ Error reading CSV: {e}")
            sys.exit(1)
    except Exception as e:
        print(f"✗ Error reading CSV: {e}")
        sys.exit(1)

    print(f"Total products before filtering: {len(df)}")

    # Try to find the category column (case-insensitive, handles accents)
    category_column = None
    for col in df.columns:
        col_lower = col.lower()
        if 'categor' in col_lower:  # Matches both "category" and "categoría"
            category_column = col
            break

    if category_column is None:
        print("✗ Could not find category column in CSV")
        print(f"Available columns: {', '.join(df.columns[:20])}...")
        sys.exit(1)

    print(f"Using column '{category_column}' for filtering")

    # Filter: any-of-prefixes match minus explicit exclusions
    categories_str = df[category_column].astype(str)
    mask = categories_str.str.startswith(tuple(prefixes)) & ~categories_str.isin(excluded)
    df_filtered = df[mask]

    print(f"Products after filtering: {len(df_filtered)}")

    matched = sorted(df_filtered[category_column].astype(str).unique())
    print(f"Matched subcategories ({len(matched)}):")
    for cat in matched:
        count = (df_filtered[category_column].astype(str) == cat).sum()
        print(f"  - {cat} ({count})")

    if len(df_filtered) == 0:
        print("⚠ Warning: No products matched the specified categories")
        print(f"Sample categories in data: {df[category_column].unique()[:10]}")

    return df_filtered


def clean_columns(df):
    """
    Remove columns that are completely empty or have all null values.
    """
    print("Cleaning empty columns...")

    original_columns = len(df.columns)

    # Remove columns where all values are null or empty
    df_cleaned = df.dropna(axis=1, how='all')

    # Remove columns where all values are empty strings
    df_cleaned = df_cleaned.loc[:, (df_cleaned != '').any(axis=0)]

    removed_columns = original_columns - len(df_cleaned.columns)
    print(f"✓ Removed {removed_columns} empty columns")
    print(f"Remaining columns: {len(df_cleaned.columns)}")

    return df_cleaned


def save_to_csv(df, output_file):
    """
    Save DataFrame to CSV.
    """
    print(f"Saving cleaned CSV to {output_file}...")
    df.to_csv(output_file, index=False)
    print(f"✓ CSV saved successfully")


def convert_to_json(df, output_file):
    """
    Convert DataFrame to JSON format. Drops attributes that are null or empty
    string per record, so they're not sent downstream (e.g. to Algolia).
    Also expands 'Precio por método de pago' (format: 'method:value;method:value')
    into per-method numeric fields plus a 'metodos_pago' array. Method names are
    discovered dynamically — no hard-coded list.
    """
    print(f"Converting to JSON and saving to {output_file}...")

    df_safe = df.astype(object).where(df.notna(), None)
    raw = df_safe.to_dict(orient='records')

    for record in raw:
        # Derive tipo_producto from the category prefix (first match wins).
        cat = record.get('Categoría')
        if isinstance(cat, str):
            for prefix, tipo in TIPO_PRODUCTO_PREFIXES:
                if cat.startswith(prefix):
                    record['tipo_producto'] = tipo
                    break

        # Derive discount percentage: ((lista - venta) / lista) * 100, truncated
        # towards zero — same rounding direction alkosto.com uses (17.9% → 17,
        # 56.5% → 56). Using round() would flip half-values the wrong way and
        # show different discounts in the bot vs the website.
        lista = record.get('Precio de lista')
        venta = record.get('Precio de venta')
        if isinstance(lista, (int, float)) and isinstance(venta, (int, float)) and lista > 0:
            record['descuento_porcentaje'] = int((lista - venta) / lista * 100)

        # Numeric screen size (inches). Source uses two columns with mixed units:
        # Tamaño Pantalla_2 holds inches for monitors/TVs; Tamaño Pantalla_1
        # holds inches for laptops/tablets/cellphones/desktops, or centimetres
        # for TVs as a secondary representation. Prefer any 'Pulgadas' value,
        # otherwise convert from 'Centímetros' to inches.
        for raw_val in (record.get('Tamaño Pantalla_2'), record.get('Tamaño Pantalla_1')):
            if not isinstance(raw_val, str) or 'pulgada' not in raw_val.lower():
                continue
            m = re.search(r'(\d+(?:[.,]\d+)?)', raw_val)
            if m:
                record['screen_size_inches'] = float(m.group(1).replace(',', '.'))
                break
        else:
            for raw_val in (record.get('Tamaño Pantalla_1'), record.get('Tamaño Pantalla_2')):
                if not isinstance(raw_val, str) or 'cent' not in raw_val.lower():
                    continue
                m = re.search(r'(\d+(?:[.,]\d+)?)', raw_val)
                if m:
                    cm = float(m.group(1).replace(',', '.'))
                    record['screen_size_inches'] = round(cm / 2.54, 1)
                    break

        pmp = record.get('Precio por método de pago')
        if not isinstance(pmp, str) or not pmp:
            continue
        methods = []
        for part in pmp.split(';'):
            method, _, value = part.strip().partition(':')
            method = re.sub(r'[^a-z0-9_]+', '_', method.strip().lower()).strip('_')
            value = value.strip()
            if not method or not value.isdigit():
                continue
            record[f'precio_{method}'] = int(value)
            methods.append(method)
        if methods:
            record['metodos_pago'] = methods

    data = [
        {k: v for k, v in record.items() if v is not None and v != ''}
        for record in raw
    ]

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✓ JSON saved successfully with {len(data)} products")


def main():
    """
    Main execution flow.
    """
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Download, filter, clean, and convert Alkosto product CSV to JSON.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Using command-line arguments:
  %(prog)s --username myuser --password mypass

  # Using environment variables:
  export ALKOSTO_USERNAME=myuser
  export ALKOSTO_PASSWORD=mypass
  %(prog)s

  # Interactive mode (will prompt for credentials):
  %(prog)s
        '''
    )
    parser.add_argument('-u', '--username', help='Username for authentication')
    parser.add_argument('-p', '--password', help='Password for authentication')
    parser.add_argument('--skip-download', action='store_true',
                       help='Skip download step and use existing productFeed.csv')

    args = parser.parse_args()

    print("=" * 60)
    print("Alkosto Product Feed Processor")
    print("=" * 60)

    # Get credentials from arguments, environment variables, or prompt
    username = args.username or os.environ.get('ALKOSTO_USERNAME')
    password = args.password or os.environ.get('ALKOSTO_PASSWORD')

    # If skip_download is set, we don't need credentials
    if not args.skip_download:
        if not username:
            username = input("Enter username: ").strip()
        if not password:
            password = input("Enter password: ").strip()

        if not username or not password:
            print("✗ Username and password are required")
            sys.exit(1)

        print()

        # Step 1: Download CSV
        downloaded_file = download_csv(CSV_URL, username, password)
        print()
    else:
        downloaded_file = "productFeed.csv"
        if not os.path.exists(downloaded_file):
            print(f"✗ File {downloaded_file} not found. Remove --skip-download to download it.")
            sys.exit(1)
        print(f"Using existing file: {downloaded_file}")
        print()

    # Step 2: Filter by categories
    df_filtered = filter_by_categories(downloaded_file, CATEGORY_PREFIXES, EXCLUDED_SUBCATEGORIES, OUTPUT_CSV)
    print()

    # Step 3: Clean empty columns
    df_cleaned = clean_columns(df_filtered)
    print()

    # Step 4: Save cleaned CSV
    save_to_csv(df_cleaned, OUTPUT_CSV)
    print()

    # Step 5: Convert to JSON
    convert_to_json(df_cleaned, OUTPUT_JSON)
    print()

    print("=" * 60)
    print("✓ Processing complete!")
    print(f"  - Cleaned CSV: {OUTPUT_CSV}")
    print(f"  - JSON output: {OUTPUT_JSON}")
    print("=" * 60)


if __name__ == "__main__":
    main()
