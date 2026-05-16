"""Stage 6: Deduplication — MinHash LSH to remove near-duplicate documents."""
import gzip
import json
import logging
import os
from io import BytesIO

import boto3
from datasketch import MinHash, MinHashLSH

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUCKET            = config.BUCKET
INPUT_PREFIX      = config.PREFIX_LANGUAGE
OUTPUT_PREFIX     = config.PREFIX_DEDUPLICATE
MINHASH_THRESHOLD = config.MINHASH_THRESHOLD
MINHASH_PERMS     = config.MINHASH_PERMS
SHINGLE_SIZE      = config.SHINGLE_SIZE

s3 = boto3.client("s3")


def make_minhash(text: str) -> MinHash:
    m = MinHash(num_perm=MINHASH_PERMS)
    words = text.split()
    for i in range(max(1, len(words) - SHINGLE_SIZE + 1)):
        shingle = " ".join(words[i : i + SHINGLE_SIZE])
        m.update(shingle.encode())
    return m


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

    lsh = MinHashLSH(threshold=MINHASH_THRESHOLD, num_perm=MINHASH_PERMS)
    total = dup = 0

    for shard_key in shards:
        shard_name = os.path.basename(shard_key)
        kept: list[dict] = []

        for doc in read_shard(shard_key):
            total += 1
            mh = make_minhash(doc["text"])
            if lsh.query(mh):
                dup += 1
                continue
            lsh.insert(doc["id"], mh)
            kept.append(doc)

        upload_shard(kept, f"{OUTPUT_PREFIX}/{shard_name}")
        log.info("shard %s: %d kept, %d duplicates removed so far", shard_name, len(kept), dup)

    log.info(
        "dedup complete: %d → %d docs (%d duplicates, %.1f%% removed)",
        total, total - dup, dup, 100 * dup / max(total, 1),
    )


if __name__ == "__main__":
    main()
