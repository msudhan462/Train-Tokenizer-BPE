"""Stage 4: Encoding Recovery — detect and fix Unicode corruption in text."""
import gzip
import json
import logging
import os
from io import BytesIO

import boto3
import ftfy

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUCKET        = config.BUCKET
INPUT_PREFIX  = config.PREFIX_EXTRACT
OUTPUT_PREFIX = config.PREFIX_ENCODING

s3 = boto3.client("s3")


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

    total = fixed = 0
    for shard_key in shards:
        shard_name = os.path.basename(shard_key)
        docs: list[dict] = []

        for doc in read_shard(shard_key):
            original = doc["text"]
            recovered = ftfy.fix_text(original, normalization="NFC")
            if recovered != original:
                fixed += 1
            doc["text"] = recovered
            docs.append(doc)
            total += 1

        upload_shard(docs, f"{OUTPUT_PREFIX}/{shard_name}")
        log.info("shard %s: %d docs", shard_name, len(docs))

    log.info(
        "encoding recovery: %d docs, %d fixed (%.1f%%)",
        total, fixed, 100 * fixed / max(total, 1),
    )


if __name__ == "__main__":
    main()
