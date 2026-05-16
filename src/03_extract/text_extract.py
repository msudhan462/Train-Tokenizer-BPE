"""Stage 3: Extract — parse clean text from HTML and normalize whitespace."""
import gzip
import json
import logging
import os
from io import BytesIO

import boto3
from bs4 import BeautifulSoup

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUCKET        = config.BUCKET
INPUT_PREFIX  = config.PREFIX_FILTER
OUTPUT_PREFIX = config.PREFIX_EXTRACT

s3 = boto3.client("s3")

_HTML_SIGNALS = {"<html", "<body", "<div", "<p>", "<span", "<table"}


def extract_html(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def clean_text(text: str) -> str:
    text_lower = text[:200].lower()
    if any(sig in text_lower for sig in _HTML_SIGNALS):
        return extract_html(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(l for l in lines if l)


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

    total = 0
    for shard_key in shards:
        shard_name = os.path.basename(shard_key)
        docs: list[dict] = []
        for doc in read_shard(shard_key):
            cleaned = clean_text(doc["text"])
            if cleaned:
                doc["text"] = cleaned
                docs.append(doc)
            total += 1

        upload_shard(docs, f"{OUTPUT_PREFIX}/{shard_name}")
        log.info("shard %s: %d docs", shard_name, len(docs))

    log.info("extract complete: %d docs processed", total)


if __name__ == "__main__":
    main()
