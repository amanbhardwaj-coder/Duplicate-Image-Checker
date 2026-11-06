import csv
import io
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from urllib.parse import urlparse

import imagehash
import requests
from PIL import Image, ImageOps
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_local = threading.local()
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 12_000_000
_decode_slots = threading.BoundedSemaphore(2)

def session():
    if not hasattr(_local, 'session'):
        s = requests.Session()
        adapter = HTTPAdapter(max_retries=Retry(total=2, backoff_factor=.5, status_forcelist=[429, 500, 502, 503, 504]))
        s.mount('https://', adapter)
        s.mount('http://', adapter)
        _local.session = s
    return _local.session

@lru_cache(maxsize=10000)
def get_hash(url):
    if urlparse(url).scheme not in ('http', 'https'):
        raise ValueError('Only HTTP and HTTPS image URLs are supported')
    # Bound both downloaded buffers and decoded images across all scan workers.
    # Network-worker count no longer multiplies full-resolution image memory.
    with _decode_slots:
        with session().get(url, timeout=(5, 20), stream=True) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise ValueError('Image exceeds 20 MB limit')
        with Image.open(io.BytesIO(content)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError('Image exceeds 12 megapixel hosted processing limit; URL preserved')
            # JPEG draft decoding reduces memory before the full pixel buffer exists.
            source.draft('RGB', (512, 512))
            source.thumbnail((512, 512), Image.Resampling.LANCZOS)
            oriented = ImageOps.exif_transpose(source)
            try:
                with oriented.convert('RGBA') as rgba:
                    with Image.new('RGBA', rgba.size, 'white') as bg:
                        bg.alpha_composite(rgba)
                        with bg.convert('RGB') as rgb:
                            return imagehash.phash(rgb)
            finally:
                if oriented is not source:
                    oriented.close()

def process_row(index, row, stock_col, image_cols, threshold):
    kept, matches, errors = [], [], []
    stock = row[stock_col].strip() if stock_col < len(row) else ''
    for col in image_cols:
        url = row[col].strip() if col < len(row) else ''
        if not url:
            continue
        try:
            current = get_hash(url)
            duplicate = next(((k, int(current - h)) for k, h in kept if current - h <= threshold), None)
            if duplicate:
                original, distance = duplicate
                matches.append(dict(row=index, stock=stock, col=col, original_col=original,
                                    url=url, original_url=row[original], distance=distance))
            else:
                kept.append((col, current))
        except Exception as exc:
            errors.append(dict(row=index, stock=stock, column=col + 1, url=url, error=str(exc)))
    return matches, errors

def scan(rows, start, stock_col, image_cols, threshold, workers, progress=None):
    matches, errors = [], []
    # Bounded batches avoid creating a future for every row of a large inventory.
    total = max(0, len(rows) - start)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset in range(start, len(rows), 500):
            futures = [pool.submit(process_row, i, rows[i], stock_col, image_cols, threshold)
                       for i in range(offset, min(offset + 500, len(rows))) ]
            for future in as_completed(futures):
                found, failed = future.result()
                matches.extend(found)
                errors.extend(failed)
                done += 1
                if progress:
                    progress(done, total)
    return sorted(matches, key=lambda m: (m['row'], m['col'])), errors

def csv_bytes(rows):
    output = io.StringIO(newline='')
    csv.writer(output).writerows(rows)
    return output.getvalue().encode('utf-8-sig')

def col_name(number):
    result = ''
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result
