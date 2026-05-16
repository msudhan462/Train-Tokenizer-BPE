"""Central configuration — all pipeline stages read env vars here."""
import os

# ── Required ──────────────────────────────────────────────────────────────────
BUCKET: str = os.environ["S3_BUCKET"]
RUN_ID: str = os.environ["RUN_ID"]

# ── S3 stage prefixes (derived — never set manually) ─────────────────────────
PREFIX_INGEST      = f"{RUN_ID}/stage01_ingest"
PREFIX_FILTER      = f"{RUN_ID}/stage02_filter"
PREFIX_EXTRACT     = f"{RUN_ID}/stage03_extract"
PREFIX_ENCODING    = f"{RUN_ID}/stage04_encoding"
PREFIX_LANGUAGE    = f"{RUN_ID}/stage05_language"
PREFIX_DEDUPLICATE = f"{RUN_ID}/stage06_deduplicate"
PREFIX_REBALANCE   = f"{RUN_ID}/stage07_rebalance"
PREFIX_TRAIN       = f"{RUN_ID}/stage08_train"

# ── Stage 1: Ingest ───────────────────────────────────────────────────────────
SOURCE_TYPE    = os.environ.get("SOURCE_TYPE", "hf_dataset")
SOURCE_DATASET = os.environ.get("SOURCE_DATASET", "allenai/c4")
SOURCE_SPLIT   = os.environ.get("SOURCE_SPLIT", "train")
SOURCE_CONFIG  = os.environ.get("SOURCE_CONFIG", "en")
SHARD_SIZE     = int(os.environ.get("SHARD_SIZE", "10000"))
MAX_DOCS       = int(os.environ.get("MAX_DOCS", "0"))          # 0 = unlimited

# ── Stage 2: Filter ───────────────────────────────────────────────────────────
MIN_CHARS        = int(os.environ.get("MIN_CHARS", "100"))
MAX_CHARS        = int(os.environ.get("MAX_CHARS", "1000000"))
MAX_HTML_RATIO   = float(os.environ.get("MAX_HTML_RATIO", "0.1"))
MIN_AVG_LINE_LEN = int(os.environ.get("MIN_AVG_LINE_LEN", "20"))

# ── Stage 5: Language detection ───────────────────────────────────────────────
MIN_LANG_CONFIDENCE = float(os.environ.get("MIN_LANG_CONFIDENCE", "0.8"))

# ── Stage 6: Deduplication ────────────────────────────────────────────────────
MINHASH_THRESHOLD = float(os.environ.get("MINHASH_THRESHOLD", "0.85"))
MINHASH_PERMS     = int(os.environ.get("MINHASH_PERMS", "128"))
SHINGLE_SIZE      = int(os.environ.get("SHINGLE_SIZE", "5"))

# ── Stage 7: Rebalance ────────────────────────────────────────────────────────
MAX_LANG_FRACTION = float(os.environ.get("MAX_LANG_FRACTION", "0.3"))
TARGET_DOCS       = int(os.environ.get("TARGET_DOCS", "0"))    # 0 = keep all after capping
RANDOM_SEED       = int(os.environ.get("RANDOM_SEED", "42"))

# ── Stage 8: Train & Validate ─────────────────────────────────────────────────
VOCAB_SIZE           = int(os.environ.get("VOCAB_SIZE", "32000"))
MIN_FREQUENCY        = int(os.environ.get("MIN_FREQUENCY", "2"))
NUM_VALIDATION_DOCS  = int(os.environ.get("NUM_VALIDATION_DOCS", "1000"))
