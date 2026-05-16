"""Stage 1: Ingest — stream corpus data and upload shards to S3."""
import gzip
import json
import logging
import os
import uuid
from io import BytesIO
from typing import Iterator

import boto3
from datasets import load_dataset
from tqdm import tqdm

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUCKET        = config.BUCKET
OUTPUT_PREFIX = config.PREFIX_INGEST
SOURCE_TYPE   = config.SOURCE_TYPE
SOURCE_DATASET = config.SOURCE_DATASET
SOURCE_SPLIT  = config.SOURCE_SPLIT
SOURCE_CONFIG = config.SOURCE_CONFIG
SHARD_SIZE    = config.SHARD_SIZE
MAX_DOCS      = config.MAX_DOCS

s3 = boto3.client("s3")


def upload_shard(docs: list[dict], shard_idx: int) -> None:
    buf = BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for doc in docs:
            gz.write((json.dumps(doc, ensure_ascii=False) + "\n").encode())
    key = f"{OUTPUT_PREFIX}/shard_{shard_idx:05d}.jsonl.gz"
    s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())
    log.info("uploaded shard %05d (%d docs) → s3://%s/%s", shard_idx, len(docs), BUCKET, key)


def iter_hf_dataset() -> Iterator[dict]:
    log.info("loading %s / %s / %s (streaming)", SOURCE_DATASET, SOURCE_CONFIG, SOURCE_SPLIT)
    ds = load_dataset(SOURCE_DATASET, SOURCE_CONFIG, split=SOURCE_SPLIT, streaming=True, trust_remote_code=True)
    for item in ds:
        text = item.get("text") or item.get("content") or item.get("passage") or ""
        if not text.strip():
            continue
        yield {
            "id": str(uuid.uuid4()),
            "text": text,
            "source": SOURCE_DATASET,
            "meta": {k: v for k, v in item.items() if k != "text" and isinstance(v, (str, int, float, bool))},
        }


def main() -> None:
    if SOURCE_TYPE == "hf_dataset":
        stream = iter_hf_dataset()
    else:
        raise ValueError(f"unsupported SOURCE_TYPE: {SOURCE_TYPE}")

    shard: list[dict] = []
    shard_idx = 0
    total = 0

    for doc in tqdm(stream, desc="ingest"):
        shard.append(doc)
        total += 1

        if len(shard) >= SHARD_SIZE:
            upload_shard(shard, shard_idx)
            shard = []
            shard_idx += 1

        if MAX_DOCS and total >= MAX_DOCS:
            break

    if shard:
        upload_shard(shard, shard_idx)
        shard_idx += 1

    log.info("ingest complete: %d docs across %d shards", total, shard_idx)


if __name__ == "__main__":
    main()
