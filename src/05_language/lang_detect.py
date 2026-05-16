"""Stage 5: Language & Domain Detection — tag documents by language and domain."""
import gzip
import json
import logging
import os
from io import BytesIO

import boto3
from langdetect import DetectorFactory, LangDetectException, detect_langs

DetectorFactory.seed = 0  # reproducible detection

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUCKET              = config.BUCKET
INPUT_PREFIX        = config.PREFIX_ENCODING
OUTPUT_PREFIX       = config.PREFIX_LANGUAGE
MIN_LANG_CONFIDENCE = config.MIN_LANG_CONFIDENCE

s3 = boto3.client("s3")

_DOMAIN_HINTS: dict[str, list[str]] = {
    "code": ["def ", "function ", "import ", "class ", "```", "github.com", "stackoverflow"],
    "math": ["theorem", "proof", "equation", "∑", "∫", "arxiv.org"],
    "legal": ["whereas", "pursuant", "hereinafter", "jurisdiction"],
    "medical": ["patient", "diagnosis", "treatment", "clinical"],
    "news": ["reported", "according to", "press release", "breaking news"],
}


def detect_language(text: str) -> tuple[str, float]:
    try:
        results = detect_langs(text[:2000])
        if results:
            top = results[0]
            return top.lang, top.prob
    except LangDetectException:
        pass
    return "unknown", 0.0


def detect_domain(text: str) -> str:
    sample = text[:500].lower()
    for domain, hints in _DOMAIN_HINTS.items():
        if any(h in sample for h in hints):
            return domain
    return "web"


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

    lang_counts: dict[str, int] = {}
    total = kept = 0

    for shard_key in shards:
        shard_name = os.path.basename(shard_key)
        docs: list[dict] = []

        for doc in read_shard(shard_key):
            total += 1
            lang, conf = detect_language(doc["text"])
            if conf < MIN_LANG_CONFIDENCE:
                continue
            doc["lang"] = lang
            doc["lang_confidence"] = round(conf, 3)
            doc["domain"] = detect_domain(doc["text"])
            docs.append(doc)
            kept += 1
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

        upload_shard(docs, f"{OUTPUT_PREFIX}/{shard_name}")
        log.info("shard %s: %d docs kept", shard_name, len(docs))

    log.info("language detection: %d → %d docs", total, kept)
    top_langs = sorted(lang_counts.items(), key=lambda x: -x[1])[:15]
    log.info("top languages: %s", top_langs)


if __name__ == "__main__":
    main()
