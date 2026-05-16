# Industry-Level BPE Tokenizer on AWS

A production-grade Byte Pair Encoding (BPE) tokenizer pipeline modeled after how frontier AI companies (OpenAI, Google, Meta) train tokenizers at 100TB+ scale. Covers the full 8-stage preprocessing and training pipeline — from raw web dumps to a trained, validated tokenizer artifact in S3.

Built as a resume/portfolio project. One manual trigger runs the entire pipeline end-to-end.

LinkedIn write-up: https://www.linkedin.com/feed/update/urn:li:activity:7460340028435632128/

---

## What This Does

Most tutorials jump straight to BPE training. Real industry pipelines run 8 stages before and around training:

1. **Ingest** — stream compressed web/corpus data from cloud storage into S3
2. **Filter** — detect and remove HTML, PDFs, binaries, corrupted files (garbage in = damaged vocabulary)
3. **Extract** — parse clean text from PDFs, HTML, OCR documents
4. **Encoding Recovery** — fix Unicode corruption common in internet-scale web dumps
5. **Language & Domain Detection** — tag each document by language, domain, source to prevent tokenizer bias
6. **Deduplication** — remove duplicate repos, boilerplate, repetitive content to prevent overfitting
7. **Rebalance** — weighted sampling across languages and domains so tokenizer isn't English-centric
8. **Train & Validate** — BPE training on cleaned corpus, evaluate across languages, code, math, compression

---

## Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.11+ |
| Tokenizer | BPE — HuggingFace `tokenizers` *(or SentencePiece / tiktoken — to be finalized)* |
| Compute | AWS EC2 Spot Instance (c5.2xlarge) |
| Storage | AWS S3 (raw → processed → artifacts → logs) |
| Orchestration | Single Python runner script (`src/run.py`) — no Step Functions, no IaC |
| CI | GitHub Actions (ruff lint + mypy type-check only) |

---

## Architecture

Intermediate S3 writes are **optional** — pass `--save-stages` flag to persist each stage's output to S3, or omit it to stream stage-to-stage in memory (faster, cheaper).

```
[ Local Machine ]
      |
      | SSH (manual trigger)
      v
[ EC2 Spot Instance ]
      |
      |-- 01_ingest/download.py        --> S3 /01_raw          (if --save-stages)
      |-- 02_filter/content_filter.py  --> S3 /02_filtered     (if --save-stages)
      |-- 03_extract/text_extract.py   --> S3 /03_extracted    (if --save-stages)
      |-- 04_encoding/encoding_recovery.py --> S3 /04_encoded  (if --save-stages)
      |-- 05_language/lang_detect.py   --> S3 /05_tagged       (if --save-stages)
      |-- 06_deduplicate/dedup.py      --> S3 /06_deduped      (if --save-stages)
      |-- 07_rebalance/rebalance.py    --> S3 /07_balanced     (if --save-stages)
      |-- 08_train/train.py            --> S3 /artifacts       (always saved)
      |-- 08_train/validate.py         --> S3 /logs            (always saved)
      v
[ S3 Bucket ]
   /01_raw        <- original corpus chunks
   /02_filtered   <- after content filtering
   /03_extracted  <- clean text only
   /04_encoded    <- Unicode-fixed text
   /05_tagged     <- language + domain metadata
   /06_deduped    <- deduplicated corpus
   /07_balanced   <- rebalanced/sampled corpus
   /artifacts     <- vocab.json, merges.txt, tokenizer.json  (always)
   /logs          <- per-stage stats and validation output   (always)
```

---

## Project Structure

```
train-tokenizer/
├── README.md                            # full project context
├── requirements.txt                     # Python dependencies
├── .gitignore
│
├── src/
│   ├── run.py                           # orchestrator — runs all 8 stages in sequence
│   ├── 01_ingest/
│   │   └── download.py                  # stream corpus data, upload shards to S3
│   ├── 02_filter/
│   │   └── content_filter.py            # detect & discard HTML, PDFs, binaries
│   ├── 03_extract/
│   │   └── text_extract.py              # extract clean text from PDFs, HTML, OCR
│   ├── 04_encoding/
│   │   └── encoding_recovery.py         # detect and fix Unicode/encoding corruption
│   ├── 05_language/
│   │   └── lang_detect.py               # tag documents by language, domain, source
│   ├── 06_deduplicate/
│   │   └── dedup.py                     # MinHash dedup, remove boilerplate/repeated content
│   ├── 07_rebalance/
│   │   └── rebalance.py                 # weighted sampling across languages and domains
│   └── 08_train/
│       ├── train.py                     # BPE tokenizer training on balanced corpus
│       └── validate.py                  # encode/decode validation, log stats
│
├── infra/
│   └── setup.sh                         # AWS CLI: create S3 bucket, launch EC2 spot
│
├── docs/
│   └── architecture.png                 # architecture diagram
│
└── .github/
    └── workflows/
        └── lint.yml                     # ruff lint + mypy type-check
```

---

## How to Run (One-Time Manual)

```bash
# 1. Provision AWS resources
bash infra/setup.sh

# 2. SSH into EC2
ssh -i your-key.pem ec2-user@<EC2_PUBLIC_IP>

# 3. Clone repo and install deps
git clone https://github.com/msudhan462/Train-Tokenizer-BPE
cd Train-Tokenizer-BPE
pip install -r requirements.txt

# 4. Trigger full 8-stage pipeline
python src/run.py --bucket <S3_BUCKET_NAME> --vocab-size 32000

# Optional: persist each stage's output to S3 (useful for debugging / resuming)
python src/run.py --bucket <S3_BUCKET_NAME> --vocab-size 32000 --save-stages
```

Without `--save-stages`, stages stream data in memory (faster, cheaper). With it, each stage's output is saved to S3 so you can resume from any stage or inspect intermediate data. Logs always written to stdout and S3 `/logs`.

---

## AWS Cost Estimate (one run)

| Resource | Est. Cost |
|----------|-----------|
| EC2 Spot c5.2xlarge (~4–8 hrs) | ~$0.40–$1.20 |
| S3 storage (all stages) | ~$0.10–$0.50 |
| Data transfer | ~$0.05 |
| **Total** | **< $2** |

Terminate EC2 after the run. S3 artifacts persist.

---

## Output Artifacts (S3 `/artifacts`)

- `vocab.json` — vocabulary (default 32k tokens)
- `merges.txt` — BPE merge rules
- `tokenizer.json` — full tokenizer config (HuggingFace format)
- `logs/validation.txt` — per-language encode/decode stats + compression ratio

---

## Status

- [ ] Tokenizer library chosen (HuggingFace / SentencePiece / tiktoken)
- [ ] `infra/setup.sh`
- [ ] Stage 1: `01_ingest/download.py`
- [ ] Stage 2: `02_filter/content_filter.py`
- [ ] Stage 3: `03_extract/text_extract.py`
- [ ] Stage 4: `04_encoding/encoding_recovery.py`
- [ ] Stage 5: `05_language/lang_detect.py`
- [ ] Stage 6: `06_deduplicate/dedup.py`
- [ ] Stage 7: `07_rebalance/rebalance.py`
- [ ] Stage 8: `08_train/train.py` + `validate.py`
- [ ] `src/run.py` orchestrator
- [ ] Architecture diagram (`docs/architecture.png`)
- [ ] End-to-end tested on AWS
