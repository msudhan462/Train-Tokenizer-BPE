"""Stage 8a: Train — BPE tokenizer training on the cleaned, balanced corpus."""
import gzip
import json
import logging
import os
import tempfile
from io import BytesIO
from typing import Iterator

import boto3
from tokenizers import Tokenizer, pre_tokenizers
from tokenizers.models import BPE
from tokenizers.processors import TemplateProcessing
from tokenizers.trainers import BpeTrainer

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUCKET        = config.BUCKET
INPUT_PREFIX  = config.PREFIX_REBALANCE
OUTPUT_PREFIX = config.PREFIX_TRAIN
VOCAB_SIZE    = config.VOCAB_SIZE
MIN_FREQUENCY = config.MIN_FREQUENCY

SPECIAL_TOKENS = ["<unk>", "<s>", "</s>", "<pad>", "<mask>"]

s3 = boto3.client("s3")


def list_shards(prefix: str) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix + "/"):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return sorted(keys)


def iter_texts(shards: list[str]) -> Iterator[str]:
    for key in shards:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        with gzip.GzipFile(fileobj=BytesIO(obj["Body"].read())) as gz:
            for line in gz:
                text = json.loads(line).get("text", "").strip()
                if text:
                    yield text


def build_tokenizer() -> tuple[Tokenizer, BpeTrainer]:
    tokenizer = Tokenizer(BPE(unk_token="<unk>"))
    # ByteLevel pre-tokenizer: maps every byte to a visible character,
    # enabling lossless encoding of any Unicode without a dedicated <unk> fallback.
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.post_processor = TemplateProcessing(
        single="<s> $A </s>",
        pair="<s> $A </s> $B:1 </s>:1",
        special_tokens=[("<s>", 1), ("</s>", 2)],
    )
    trainer = BpeTrainer(
        vocab_size=VOCAB_SIZE,
        min_frequency=MIN_FREQUENCY,
        special_tokens=SPECIAL_TOKENS,
        show_progress=True,
    )
    return tokenizer, trainer


def main() -> None:
    shards = list_shards(INPUT_PREFIX)
    log.info("found %d input shards for BPE training", len(shards))
    log.info("vocab_size=%d  min_frequency=%d", VOCAB_SIZE, MIN_FREQUENCY)

    tokenizer, trainer = build_tokenizer()
    tokenizer.train_from_iterator(iter_texts(shards), trainer=trainer)

    actual_vocab_size = tokenizer.get_vocab_size()
    log.info("training complete — actual vocab size: %d", actual_vocab_size)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        tokenizer.save(f.name)
        tokenizer_json = open(f.name).read()

    key = f"{OUTPUT_PREFIX}/tokenizer.json"
    s3.put_object(Bucket=BUCKET, Key=key, Body=tokenizer_json.encode(), ContentType="application/json")
    log.info("tokenizer saved → s3://%s/%s", BUCKET, key)

    stats = {
        "vocab_size": actual_vocab_size,
        "vocab_size_requested": VOCAB_SIZE,
        "min_frequency": MIN_FREQUENCY,
        "special_tokens": SPECIAL_TOKENS,
        "run_id": RUN_ID,
    }
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{OUTPUT_PREFIX}/training_stats.json",
        Body=json.dumps(stats, indent=2).encode(),
        ContentType="application/json",
    )
    log.info("training stats: %s", stats)


if __name__ == "__main__":
    main()
