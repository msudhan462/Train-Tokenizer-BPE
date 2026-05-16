# Industry-Level BPE Tokenizer on AWS

A production-grade Byte Pair Encoding (BPE) tokenizer trained on a large text corpus, fully hosted on AWS. Designed as a one-time manual end-to-end pipeline — trigger once, everything runs automatically from data download to trained artifact in S3.

Built as a resume/portfolio project to demonstrate LLM infrastructure skills.

---

## What This Does

Trains a BPE tokenizer (same algorithm used by GPT, LLaMA, etc.) on a real large-scale corpus (Wikipedia dump), saves the trained vocab and merge rules to S3, and validates it with sample encode/decode runs.

---

## Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.11+ |
| Tokenizer | BPE — HuggingFace `tokenizers` *(or SentencePiece / tiktoken — one to be chosen before coding)* |
| Compute | AWS EC2 spot instance (t3.xlarge or c5.2xlarge) |
| Storage | AWS S3 (raw corpus in, tokenizer artifacts out) |
| Orchestration | Single Python runner script (`src/run.py`) — no Step Functions, no IaC |
| CI | GitHub Actions (lint + type-check only, no auto-deploy) |

**Tokenizer library decision not yet made.** Options:
- `HuggingFace tokenizers` — fastest, most control, industry standard for LLM training (recommended)
- `SentencePiece` — Google's library, used in LLaMA/T5, better for multilingual
- `tiktoken` — OpenAI's, fast but limited configurability for training from scratch

---

## Architecture

```
[ Local Machine ]
      |
      | SSH / aws CLI (manual trigger)
      v
[ EC2 Spot Instance ]
      |
      |-- Step 1: Download corpus (Wikipedia dump) --> upload to S3
      |-- Step 2: Pull corpus from S3, train BPE tokenizer
      |-- Step 3: Save vocab.json + merges.txt to S3
      |-- Step 4: Validate (sample encode/decode, log stats to S3)
      v
[ S3 Bucket ]
   /raw/         <- corpus chunks
   /artifacts/   <- trained tokenizer files
   /logs/        <- validation output
```

---

## Project Structure

```
train-tokenizer/
├── README.md                        # this file — full project context
├── requirements.txt                 # Python dependencies
├── .gitignore
│
├── src/
│   ├── run.py                       # main orchestrator — runs all 4 steps in sequence
│   ├── data/
│   │   └── download.py              # downloads Wikipedia dump, uploads chunks to S3
│   ├── tokenizer/
│   │   └── train.py                 # trains BPE tokenizer on corpus from S3
│   └── validate/
│       └── validate.py              # encodes/decodes sample sentences, logs stats
│
├── infra/
│   └── setup.sh                     # AWS CLI commands: create S3 bucket, launch EC2 spot
│
├── docs/
│   └── architecture.png             # architecture diagram
│
└── .github/
    └── workflows/
        └── lint.yml                 # GitHub Actions: ruff lint + mypy type-check
```

---

## How to Run (One-Time Manual)

```bash
# 1. Provision AWS resources (S3 bucket + EC2 spot)
bash infra/setup.sh

# 2. SSH into EC2
ssh -i your-key.pem ec2-user@<EC2_PUBLIC_IP>

# 3. Clone repo and install deps
git clone https://github.com/<your-handle>/train-tokenizer
cd train-tokenizer
pip install -r requirements.txt

# 4. Trigger full pipeline
python src/run.py --bucket <S3_BUCKET_NAME> --vocab-size 32000
```

Pipeline steps run sequentially: download → train → save → validate. Logs go to stdout and S3.

---

## AWS Cost Estimate (one run)

| Resource | Est. Cost |
|----------|-----------|
| EC2 spot (c5.2xlarge, ~2–4 hrs) | ~$0.20–$0.60 |
| S3 storage (corpus + artifacts) | ~$0.05 |
| Data transfer | ~$0.01 |
| **Total** | **< $1** |

Terminate the EC2 instance after the run — S3 artifacts persist.

---

## Output Artifacts (saved to S3)

- `artifacts/vocab.json` — vocabulary (default 32k tokens)
- `artifacts/merges.txt` — BPE merge rules
- `artifacts/tokenizer.json` — full tokenizer config (HuggingFace format)
- `logs/validation.txt` — encode/decode stats

---

## Status

- [ ] Tokenizer library chosen
- [ ] `infra/setup.sh` written
- [ ] `src/data/download.py` written
- [ ] `src/tokenizer/train.py` written
- [ ] `src/validate/validate.py` written
- [ ] `src/run.py` orchestrator written
- [ ] Architecture diagram added
- [ ] End-to-end tested on AWS
