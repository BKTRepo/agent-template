#!/usr/bin/env python
"""
Parse JaCoCo HTML coverage reports into structured JSON.

Usage:
    python parse_jacoco.py <code_coverage_file_dir> <output_json>

Output JSON format:
{
  "packages": {
    "com.example.service": {
      "classes": {
        "UserService": {
          "coverage_percent": 75.0,
          "total_lines": 100,
          "covered_lines": 75,
          "missed_lines": 25,
          "lines": {
            "10": {"covered": true, "instruction_pct": "100%"},
            "11": {"covered": false, "instruction_pct": "0%"}
          }
        }
      }
    }
  }
}
"""

import sys
import os
import json
import re
from pathlib import Path


def parse_html_file(filepath):
    """Parse a single JaCoCo HTML coverage file."""
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    result = {
        'total_lines': 0,
        'covered_lines': 0,
        'missed_lines': 0,
        'lines': {}
    }

    # Try to extract overall coverage stats from the table
    # Look for coverage table rows
    coverage_pattern = re.compile(
        r'<tr>.*?<td[^>]*>Total</td>.*?<td[^>]*>(\d+)</td>.*?<td[^>]*>(\d+)</td>.*?<td[^>]*>(\d+)</td>.*?</tr>',
        re.DOTALL
    )
    match = coverage_pattern.search(content)
    if match:
        result['total_lines'] = int(match.group(1))
        result['missed_lines'] = int(match.group(2))
        result['covered_lines'] = int(match.group(3))
        if result['total_lines'] > 0:
            result['coverage_percent'] = round(result['covered_lines'] / result['total_lines'] * 100, 2)

    # Parse line-level coverage from source code table
    # JaCoCo uses class names like "fc" (fully covered), "pc" (partially covered), "nc" (not covered)
    line_pattern = re.compile(
        r'<tr[^>]*>.*?<td[^>]*id="L(\d+)"[^>]*>.*?</td>.*?<td[^>]*class="([^"]*(?:fc|pc|nc)[^"]*)"[^>]*>.*?</td>.*?</tr>',
        re.DOTALL
    )

    for match in line_pattern.finditer(content):
        line_num = match.group(1)
        css_class = match.group(2)

        if 'fc' in css_class:
            covered = True
        elif 'pc' in css_class:
            covered = 'partial'
        elif 'nc' in css_class:
            covered = False
        else:
            continue

        result['lines'][line_num] = {
            'covered': covered
        }

    # Also try alternative patterns for different JaCoCo versions
    # Some versions use inline styles or different class structures
    alt_line_pattern = re.compile(
        r'<tr[^>]*>.*?<td[^>]*id="L(\d+)"[^>]*>.*?</td>.*?<td[^>]*>(.*?)</td>.*?</tr>',
        re.DOTALL
    )

    # If no lines found with first pattern, try broader search
    if not result['lines']:
        for match in alt_line_pattern.finditer(content):
            line_num = match.group(1)
            cell_content = match.group(2)

            # Check for coverage indicators in the cell
            if 'class="fc"' in cell_content or 'class=\"fc\"' in cell_content:
                result['lines'][line_num] = {'covered': True}
            elif 'class="nc"' in cell_content or 'class=\"nc\"' in cell_content:
                result['lines'][line_num] = {'covered': False}
            elif 'class="pc"' in cell_content or 'class=\"pc\"' in cell_content:
                result['lines'][line_num] = {'covered': 'partial'}

    return result


def extract_class_name_from_file(filepath):
    """Extract class name from JaCoCo HTML filename or content."""
    filename = os.path.basename(filepath)
    # Remove .html extension
    name = filename.replace('.html', '')
    return name


def extract_package_from_path(filepath, base_dir):
    """Extract package name from relative path."""
    rel_path = os.path.relpath(filepath, base_dir)
    dir_path = os.path.dirname(rel_path)
    # Convert path separators to dots
    package = dir_path.replace(os.sep, '.').replace('/', '.')
    return package if package else 'default'


def parse_coverage_directory(dir_path):
    """Parse all HTML files in the coverage directory."""
    result = {'packages': {}}

    base_path = Path(dir_path)

    # Find all HTML files
    html_files = list(base_path.rglob('*.html'))

    for html_file in html_files:
        filepath = str(html_file)

        # Skip index.html files (they're summary pages)
        if html_file.name.lower() == 'index.html':
            continue

        # Parse the file
        file_data = parse_html_file(filepath)

        if not file_data['lines'] and not file_data.get('total_lines'):
            continue

        # Extract package and class name
        package = extract_package_from_path(filepath, dir_path)
        class_name = extract_class_name_from_file(filepath)

        # Initialize package if not exists
        if package not in result['packages']:
            result['packages'][package] = {'classes': {}}

        result['packages'][package]['classes'][class_name] = file_data

    return result


def main():
    if len(sys.argv) != 3:
        print("Usage: python parse_jacoco.py <code_coverage_file_dir> <output_json>")
        sys.exit(1)

    input_dir = sys.argv[1]
    output_file = sys.argv[2]

    if not os.path.isdir(input_dir):
        print(f"Error: Directory not found: {input_dir}")
        sys.exit(1)

    print(f"Parsing JaCoCo reports from: {input_dir}")

    coverage_data = parse_coverage_directory(input_dir)

    # Count totals
    total_classes = 0
    total_packages = len(coverage_data['packages'])
    for pkg in coverage_data['packages'].values():
        total_classes += len(pkg['classes'])

    # Also count total line coverage
    total_lines = 0
    covered_lines = 0
    missed_lines = 0
    for pkg in coverage_data['packages'].values():
        for cls in pkg['classes'].values():
            total_lines += cls.get('total_lines', 0)
            covered_lines += cls.get('covered_lines', 0)
            missed_lines += cls.get('missed_lines', 0)

    print(f"Found {total_packages} packages, {total_classes} classes")
    print(f"Total lines: {total_lines}, Covered: {covered_lines}, Missed: {missed_lines}")

    # Write output
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(coverage_data, f, ensure_ascii=False, indent=2)

    print(f"Coverage data written to: {output_file}")


if __name__ == '__main__':
    main()
