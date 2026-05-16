"""Stage 2: Filter — detect and remove HTML, binary, and low-quality documents."""
import gzip
import json
import logging
import os
import re
from io import BytesIO

import boto3

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUCKET           = config.BUCKET
INPUT_PREFIX     = config.PREFIX_INGEST
OUTPUT_PREFIX    = config.PREFIX_FILTER
MIN_CHARS        = config.MIN_CHARS
MAX_CHARS        = config.MAX_CHARS
MAX_HTML_RATIO   = config.MAX_HTML_RATIO
MIN_AVG_LINE_LEN = config.MIN_AVG_LINE_LEN

s3 = boto3.client("s3")

_HTML_TAG = re.compile(r"<[^>]{1,100}>")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")


def is_binary(text: str) -> bool:
    return bool(_CONTROL_CHARS.search(text[:2000]))


def has_excessive_html(text: str) -> bool:
    words = len(text.split())
    tags = len(_HTML_TAG.findall(text))
    return words > 0 and tags / words > MAX_HTML_RATIO


def is_quality(text: str) -> bool:
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        return False
    non_empty_lines = [l for l in text.splitlines() if l.strip()]
    if not non_empty_lines:
        return False
    avg_len = sum(len(l) for l in non_empty_lines) / len(non_empty_lines)
    return avg_len >= MIN_AVG_LINE_LEN


def list_shards(prefix: str) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix + "/"):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return sorted(keys)


def read_shard(key: str):
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    with gzip.GzipFile(fileobj=BytesIO(obj["Body"].read())) as gz:
        for line in gz:
            yield json.loads(line)


def upload_shard(docs: list[dict], key: str) -> None:
    buf = BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for doc in docs:
            gz.write((json.dumps(doc, ensure_ascii=False) + "\n").encode())
    s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())


def main() -> None:
    shards = list_shards(INPUT_PREFIX)
    log.info("found %d input shards", len(shards))

    total_in = total_out = 0
    for shard_key in shards:
        shard_name = os.path.basename(shard_key)
        kept: list[dict] = []
        shard_in = 0

        for doc in read_shard(shard_key):
            shard_in += 1
            total_in += 1
            text = doc.get("text", "")
            if is_binary(text) or has_excessive_html(text) or not is_quality(text):
                continue
            kept.append(doc)
            total_out += 1

        upload_shard(kept, f"{OUTPUT_PREFIX}/{shard_name}")
        log.info("shard %s: %d → %d docs", shard_name, shard_in, len(kept))

    log.info(
        "filter complete: %d → %d docs (%.1f%% kept)",
        total_in, total_out, 100 * total_out / max(total_in, 1),
    )


if __name__ == "__main__":
    main()
