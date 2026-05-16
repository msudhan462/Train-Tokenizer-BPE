"""Stage 7: Rebalance — log-smoothed weighted sampling across languages and domains."""
import gzip
import json
import logging
import math
import os
import random
from collections import defaultdict
from io import BytesIO

import boto3

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUCKET            = config.BUCKET
INPUT_PREFIX      = config.PREFIX_DEDUPLICATE
OUTPUT_PREFIX     = config.PREFIX_REBALANCE
MAX_LANG_FRACTION = config.MAX_LANG_FRACTION
TARGET_DOCS       = config.TARGET_DOCS
SHARD_SIZE        = config.SHARD_SIZE
RANDOM_SEED       = config.RANDOM_SEED

random.seed(RANDOM_SEED)
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


def compute_quotas(lang_sizes: dict[str, int], total: int) -> dict[str, int]:
    """Log-smooth sampling so rare languages get a boosted share, English can't dominate."""
    log_sizes = {lang: math.log(n + 1) for lang, n in lang_sizes.items()}
    total_log = sum(log_sizes.values())

    quotas: dict[str, int] = {}
    if TARGET_DOCS:
        for lang, ls in log_sizes.items():
            fraction = min(ls / total_log, MAX_LANG_FRACTION)
            quotas[lang] = min(round(fraction * TARGET_DOCS), lang_sizes[lang])
    else:
        max_per_lang = round(total * MAX_LANG_FRACTION)
        for lang, n in lang_sizes.items():
            quotas[lang] = min(n, max_per_lang)

    return quotas


def main() -> None:
    shards = list_shards(INPUT_PREFIX)
    log.info("found %d input shards — loading corpus for rebalancing", len(shards))

    by_lang: dict[str, list[dict]] = defaultdict(list)
    total = 0
    for shard_key in shards:
        for doc in read_shard(shard_key):
            by_lang[doc.get("lang", "unknown")].append(doc)
            total += 1

    log.info("loaded %d docs across %d languages", total, len(by_lang))

    lang_sizes = {lang: len(docs) for lang, docs in by_lang.items()}
    quotas = compute_quotas(lang_sizes, total)

    output_docs: list[dict] = []
    for lang, quota in sorted(quotas.items()):
        sampled = random.sample(by_lang[lang], quota)
        output_docs.extend(sampled)
        log.info("lang %-8s %6d → %6d docs", lang, lang_sizes[lang], quota)

    random.shuffle(output_docs)

    shard_idx = 0
    for i in range(0, len(output_docs), SHARD_SIZE):
        upload_shard(output_docs[i : i + SHARD_SIZE], f"{OUTPUT_PREFIX}/shard_{shard_idx:05d}.jsonl.gz")
        shard_idx += 1

    log.info("rebalance complete: %d → %d docs across %d shards", total, len(output_docs), shard_idx)


if __name__ == "__main__":
    main()
