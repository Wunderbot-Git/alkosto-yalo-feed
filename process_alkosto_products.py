#!/usr/bin/env python3
"""
Script to download, filter, clean, and convert Alkosto product CSV to JSON.
"""

import csv
import json
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

# Filter: include everything under this level-1 category, except the excluded subcategories
CATEGORY_LEVEL1 = "Computadores y Tablet"
EXCLUDED_SUBCATEGORIES = [
    "Computadores y Tablet>Impresión>Resmas Papel",
    "Computadores y Tablet>Impresión>Tintas, Tóner y Cartuchos",
    "Computadores y Tablet>Proyectores y Videobeam",
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


def filter_by_categories(input_file, level1, excluded, output_file):
    """
    Filter CSV rows: keep everything under the given level-1 category,
    minus the excluded full subcategory paths.
    """
    print(f"Filtering products by categories...")

    # Read CSV with pandas, handling encoding properly
    try:
        df = pd.read_csv(input_file, low_memory=False, encoding='utf-8')
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(input_file, low_memory=False, encoding='latin-1')
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

    # Filter: level-1 prefix match minus explicit exclusions
    prefix = f"{level1}>"
    categories_str = df[category_column].astype(str)
    mask = categories_str.str.startswith(prefix) & ~categories_str.isin(excluded)
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
    """
    print(f"Converting to JSON and saving to {output_file}...")

    df_safe = df.astype(object).where(df.notna(), None)
    raw = df_safe.to_dict(orient='records')

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
    df_filtered = filter_by_categories(downloaded_file, CATEGORY_LEVEL1, EXCLUDED_SUBCATEGORIES, OUTPUT_CSV)
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
