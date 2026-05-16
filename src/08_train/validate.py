"""Stage 8b: Validate — roundtrip checks and corpus-level quality metrics."""
import gzip
import json
import logging
import os
import tempfile
from io import BytesIO

import boto3
from tokenizers import Tokenizer

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUCKET               = config.BUCKET
TOKENIZER_PREFIX     = config.PREFIX_TRAIN
CORPUS_PREFIX        = config.PREFIX_REBALANCE
NUM_VALIDATION_DOCS  = config.NUM_VALIDATION_DOCS

s3 = boto3.client("s3")

PROBE_TEXTS: dict[str, str] = {
    "english": "The quick brown fox jumps over the lazy dog.",
    "chinese": "人工智能正在改变世界的方方面面。",
    "arabic": "الذكاء الاصطناعي يغير العالم بطرق لا تعد ولا تحصى.",
    "russian": "Искусственный интеллект меняет мир.",
    "code_python": "def fibonacci(n):\n    return n if n <= 1 else fibonacci(n-1) + fibonacci(n-2)",
    "math": "∑_{i=1}^{n} i = n(n+1)/2  and  ∫₀¹ x² dx = 1/3",
    "multilingual": "Hello Bonjour Hola 你好 مرحبا Привет こんにちは",
    "unicode_edge": "Ｈｅｌｌｏ　Ｗｏｒｌｄ！ ← full-width",
}


def load_tokenizer() -> Tokenizer:
    obj = s3.get_object(Bucket=BUCKET, Key=f"{TOKENIZER_PREFIX}/tokenizer.json")
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="wb") as f:
        f.write(obj["Body"].read())
        tmp_path = f.name
    return Tokenizer.from_file(tmp_path)


def roundtrip_ok(tokenizer: Tokenizer, text: str, label: str) -> bool:
    enc = tokenizer.encode(text)
    decoded = tokenizer.decode(enc.ids, skip_special_tokens=True)
    ok = text.strip() == decoded.strip()
    status = "OK" if ok else "MISMATCH"
    log.info("[%s] %s  tokens=%d  sample=%s", label, status, len(enc.tokens), enc.tokens[:8])
    if not ok:
        log.warning("  original: %r", text[:80])
        log.warning("  decoded:  %r", decoded[:80])
    return ok


def load_sample_texts(n: int) -> list[str]:
    texts: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=CORPUS_PREFIX + "/"):
        for obj in page.get("Contents", []):
            raw = s3.get_object(Bucket=BUCKET, Key=obj["Key"])
            with gzip.GzipFile(fileobj=BytesIO(raw["Body"].read())) as gz:
                for line in gz:
                    text = json.loads(line).get("text", "").strip()
                    if text:
                        texts.append(text)
                    if len(texts) >= n:
                        return texts
    return texts


def compression_ratio(tokenizer: Tokenizer, texts: list[str]) -> float:
    total_chars = sum(len(t) for t in texts)
    total_tokens = sum(len(tokenizer.encode(t).ids) for t in texts)
    return total_chars / max(total_tokens, 1)


def fertility(tokenizer: Tokenizer, texts: list[str]) -> float:
    total_words = sum(len(t.split()) for t in texts)
    total_tokens = sum(len(tokenizer.encode(t).ids) for t in texts)
    return total_tokens / max(total_words, 1)


def main() -> None:
    log.info("loading tokenizer from s3://%s/%s/tokenizer.json", BUCKET, TOKENIZER_PREFIX)
    tokenizer = load_tokenizer()
    log.info("vocab size: %d", tokenizer.get_vocab_size())

    log.info("=== roundtrip checks ===")
    failures = sum(1 for label, text in PROBE_TEXTS.items() if not roundtrip_ok(tokenizer, text, label))
    log.info("roundtrip: %d/%d passed", len(PROBE_TEXTS) - failures, len(PROBE_TEXTS))

    log.info("=== corpus metrics (n=%d) ===", NUM_VALIDATION_DOCS)
    sample_texts = load_sample_texts(NUM_VALIDATION_DOCS)
    if sample_texts:
        cr = compression_ratio(tokenizer, sample_texts)
        fert = fertility(tokenizer, sample_texts)
        log.info("compression ratio (chars/token): %.2f  (GPT-4 ≈ 4.0)", cr)
        log.info("fertility (tokens/word):          %.2f  (good BPE ≈ 1.2–1.5)", fert)
        log.info("docs sampled: %d", len(sample_texts))

    log.info("=== token analysis ===")
    vocab = tokenizer.get_vocab()
    special = [t for t in vocab if t.startswith("<") and t.endswith(">")]
    log.info("special tokens: %s", special)
    probe_enc = tokenizer.encode("Hello world! This is a tokenizer validation test.")
    log.info("probe tokens: %s", probe_enc.tokens)

    results = {
        "vocab_size": tokenizer.get_vocab_size(),
        "roundtrip_failures": failures,
        "compression_ratio": round(cr, 3) if sample_texts else None,
        "fertility": round(fert, 3) if sample_texts else None,
        "docs_sampled": len(sample_texts),
    }
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{TOKENIZER_PREFIX}/validation_results.json",
        Body=json.dumps(results, indent=2).encode(),
        ContentType="application/json",
    )
    log.info("validation results saved → s3://%s/%s/validation_results.json", BUCKET, TOKENIZER_PREFIX)
    log.info("validation complete: %s", results)


if __name__ == "__main__":
    main()
