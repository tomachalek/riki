#!/usr/bin/env python3
"""
Check all links in markdown files and mark broken ones with an emoji.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
import requests
from typing import Dict, List, Tuple


class LinkChecker:
    def __init__(self, data_dir: str, timeout: int = 10):
        self.data_dir = Path(data_dir)
        self.timeout = timeout
        self.stats = {
            'total_links': 0,
            'ok_links': 0,
            'dead_links': 0,
            'files_processed': 0,
            'files_modified': 0
        }
        # Regex to find markdown links [text](url)
        self.link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        # Emoji to mark broken links
        self.broken_emoji = ' ⚠️'

    def check_url(self, url: str) -> bool:
        """
        Check if a URL is accessible.
        Uses HEAD request first to minimize data transfer.
        """
        # Skip internal anchors and relative links
        if url.startswith('#') or not url.startswith('http'):
            return True

        try:
            # Try HEAD request first (no body data transferred)
            response = requests.head(
                url,
                timeout=self.timeout,
                allow_redirects=True,
                headers={'User-Agent': 'Mozilla/5.0 (Link Checker)'}
            )

            # Some servers don't support HEAD, try GET with stream=True
            if response.status_code == 405 or response.status_code >= 400:
                response = requests.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True,
                    stream=True,  # Don't download body
                    headers={'User-Agent': 'Mozilla/5.0 (Link Checker)'}
                )
                # Close connection immediately without reading body
                response.close()

            return response.status_code < 400

        except requests.RequestException as e:
            return False

    def extract_links(self, content: str) -> List[Tuple[str, str, str]]:
        """
        Extract all markdown links from content.
        Returns list of tuples: (full_match, link_text, url)
        """
        matches = []
        for match in self.link_pattern.finditer(content):
            full_match = match.group(0)
            link_text = match.group(1)
            url = match.group(2)
            matches.append((full_match, link_text, url))
        return matches

    def process_file(self, file_path: Path) -> bool:
        """
        Process a single markdown file.
        Returns True if file was modified.
        """
        print(f"\n📄 Processing: {file_path.relative_to(self.data_dir)}")

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content
        links = self.extract_links(content)

        if not links:
            print("  No links found")
            return False

        for full_match, link_text, url in links:
            self.stats['total_links'] += 1

            # Skip if already marked as broken
            if link_text.endswith(self.broken_emoji):
                print(f"  {url} - SKIPPED (already marked)")
                continue

            is_alive = self.check_url(url)

            if is_alive:
                self.stats['ok_links'] += 1
                print(f"  ✓ {url} - OK")
            else:
                self.stats['dead_links'] += 1
                print(f"  ✗ {url} - DEAD")

                # Mark the link as broken by adding emoji to link text
                new_link_text = link_text + self.broken_emoji
                new_match = f"[{new_link_text}]({url})"
                content = content.replace(full_match, new_match, 1)

        # Write back if modified
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.stats['files_modified'] += 1
            return True

        return False

    def process_directory(self):
        """
        Process all markdown files in the data directory.
        """
        if not self.data_dir.exists():
            print(f"Error: Data directory not found: {self.data_dir}")
            sys.exit(1)

        md_files = list(self.data_dir.rglob('*.md'))

        if not md_files:
            print(f"No markdown files found in {self.data_dir}")
            return

        print(f"Found {len(md_files)} markdown file(s)")
        print("=" * 60)

        for md_file in md_files:
            self.stats['files_processed'] += 1
            self.process_file(md_file)

        self.print_stats()

    def print_stats(self):
        """Print final statistics."""
        print("\n" + "=" * 60)
        print("📊 SUMMARY")
        print("=" * 60)
        print(f"Files processed:  {self.stats['files_processed']}")
        print(f"Files modified:   {self.stats['files_modified']}")
        print(f"Total links:      {self.stats['total_links']}")
        print(f"OK links:         {self.stats['ok_links']} ✓")
        print(f"Dead links:       {self.stats['dead_links']} ✗")

        if self.stats['total_links'] > 0:
            success_rate = (self.stats['ok_links'] / self.stats['total_links']) * 100
            print(f"Success rate:     {success_rate:.1f}%")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Check links in markdown files and mark broken ones'
    )
    parser.add_argument(
        '--config',
        default='config.json',
        help='Path to config file (default: config.json)'
    )
    parser.add_argument(
        '--data-dir',
        help='Override data directory from config'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=10,
        help='HTTP request timeout in seconds (default: 10)'
    )

    args = parser.parse_args()

    # Load config to get data directory
    if args.data_dir:
        data_dir = args.data_dir
    else:
        try:
            with open(args.config, 'r') as f:
                config = json.load(f)
                data_dir = config.get('dataDir')
                if not data_dir:
                    print(f"Error: 'dataDir' not found in {args.config}")
                    sys.exit(1)
        except FileNotFoundError:
            print(f"Error: Config file not found: {args.config}")
            sys.exit(1)
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON in {args.config}")
            sys.exit(1)

    print(f"Data directory: {data_dir}")
    print(f"Timeout: {args.timeout}s")

    checker = LinkChecker(data_dir, timeout=args.timeout)
    checker.process_directory()


if __name__ == '__main__':
    main()
