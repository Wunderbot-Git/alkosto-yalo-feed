#!/usr/bin/env python3
"""
Script to replace image URLs in the JSON file with static CDN URLs.
Replaces Enlace link1 and Enlace link2 with static URLs based on product ID.
"""

import json
import sys
from pathlib import Path


# Static CDN base URL
CDN_BASE_URL = "https://cdn.dam.alkosto.com/products"


def replace_image_urls(input_json, output_json=None, cdn_base_url=CDN_BASE_URL):
    """
    Replace image URLs with static CDN URLs based on product ID.

    Args:
        input_json: Path to input JSON file
        output_json: Path to output JSON file (if None, overwrites input)
        cdn_base_url: Base URL for CDN
    """
    print("=" * 70)
    print("Replace Image URLs with Static CDN URLs")
    print("=" * 70)
    print()

    # Load JSON file
    try:
        with open(input_json, 'r', encoding='utf-8') as f:
            products = json.load(f)
        print(f"✓ Loaded {len(products)} products from {input_json}")
    except Exception as e:
        print(f"✗ Error loading JSON file: {e}")
        sys.exit(1)

    # Process each product
    print(f"Replacing image URLs with static CDN URLs...")
    print(f"CDN Base URL: {cdn_base_url}")
    print()

    updated_count = 0

    for product in products:
        product_id = product.get('Identificador del producto')

        if not product_id:
            continue

        # Build new static URLs
        new_link1 = f"{cdn_base_url}/{product_id}/{product_id}-001.webp"
        new_link2 = f"{cdn_base_url}/{product_id}/{product_id}-002.webp"

        # Replace URLs
        old_link1 = product.get('Enlace link1', '')
        old_link2 = product.get('Enlace link2', '')

        if old_link1 != new_link1 or old_link2 != new_link2:
            product['Enlace link1'] = new_link1
            product['Enlace link2'] = new_link2
            updated_count += 1

    print(f"✓ Updated {updated_count} products with new image URLs")
    print()

    # Determine output file
    if output_json is None:
        output_json = input_json

    # Save updated JSON
    try:
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(products, f, indent=2, ensure_ascii=False)
        print(f"✓ Saved updated JSON to: {output_json}")
    except Exception as e:
        print(f"✗ Error saving JSON file: {e}")
        sys.exit(1)

    # Show sample URLs
    if products:
        sample = products[0]
        sample_id = sample.get('Identificador del producto')
        print()
        print("=" * 70)
        print("Sample URLs")
        print("=" * 70)
        print(f"Product ID: {sample_id}")
        print(f"Link 1: {sample.get('Enlace link1')}")
        print(f"Link 2: {sample.get('Enlace link2')}")

    print("=" * 70)


def main():
    """Main execution."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Replace image URLs with static CDN URLs in JSON file.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Replace URLs in filtered_products.json (overwrites file):
  %(prog)s filtered_products.json

  # Replace URLs and save to new file:
  %(prog)s filtered_products.json --output filtered_products_cdn.json

  # Specify custom CDN base URL:
  %(prog)s filtered_products.json --cdn-url https://custom.cdn.com/images
        '''
    )

    parser.add_argument('input',
                       help='Path to input JSON file')
    parser.add_argument('-o', '--output',
                       help='Path to output JSON file (default: overwrites input)')
    parser.add_argument('--cdn-url',
                       default=CDN_BASE_URL,
                       help=f'CDN base URL (default: {CDN_BASE_URL})')

    args = parser.parse_args()

    # Check if input file exists
    if not Path(args.input).exists():
        print(f"✗ Input file not found: {args.input}")
        sys.exit(1)

    # Use custom CDN URL if provided
    replace_image_urls(args.input, args.output, args.cdn_url)


if __name__ == "__main__":
    main()
