# Industry-Level BPE Tokenizer on AWS

A production-grade Byte Pair Encoding (BPE) tokenizer pipeline modeled after how frontier AI companies (OpenAI, Google, Meta) train tokenizers at 100TB+ scale. Covers the full 8-stage preprocessing and training pipeline — from raw web dumps to a trained, validated tokenizer artifact in S3.

Built as a resume/portfolio project. One manual CLI command triggers the entire pipeline via AWS Step Functions → Batch Fargate.

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
| Containers | Docker — single image, stage selected via `STAGE` env var |
| Container Registry | AWS ECR |
| Compute | AWS Batch (Fargate) — no EC2, no SSH |
| Orchestration | AWS Step Functions — state machine chains all 8 stages |
| Storage | AWS S3 |
| Logging | AWS CloudWatch (automatic from Fargate) |
| CI | GitHub Actions (ruff lint + mypy type-check only) |

---

## Architecture

![AWS Architecture](docs/AWS%20Architecture.png)

```
[ Local Machine ]
      |
      | aws stepfunctions start-execution (one manual command)
      v
[ Step Functions State Machine ]
      |
      |-- Task 1 --> Batch Job: 01_ingest
      |-- Task 2 --> Batch Job: 02_filter
      |-- Task 3 --> Batch Job: 03_extract
      |-- Task 4 --> Batch Job: 04_encoding
      |-- Task 5 --> Batch Job: 05_language
      |-- Task 6 --> Batch Job: 06_deduplicate
      |-- Task 7 --> Batch Job: 07_rebalance
      |-- Task 8 --> Batch Job: 08_train
      |-- Task 9 --> Batch Job: 08_validate
      v
[ AWS Batch — Fargate ]          [ ECR ]
  runs Docker container   <---   stores image
      |
      | (optional: --save-stages)
      v
[ S3 Bucket ]
   /01_raw        <- original corpus chunks          (if --save-stages)
   /02_filtered   <- after content filtering         (if --save-stages)
   /03_extracted  <- clean text only                 (if --save-stages)
   /04_encoded    <- Unicode-fixed text              (if --save-stages)
   /05_tagged     <- language + domain metadata      (if --save-stages)
   /06_deduped    <- deduplicated corpus             (if --save-stages)
   /07_balanced   <- rebalanced/sampled corpus       (if --save-stages)
   /artifacts     <- vocab.json, merges.txt, tokenizer.json  (always)
   /logs          <- per-stage stats + validation           (always)

[ CloudWatch Logs ]  <- all Fargate container logs (automatic)
```

---

## AWS Services Used

| Service | Role | Cost driver |
|---------|------|-------------|
| **Step Functions** | Orchestrate 8-stage state machine | ~$0.025 per 1000 state transitions (essentially free here) |
| **AWS Batch (Fargate)** | Run each stage as a container job | ~$0.40/hr per job (pay per use, no idle) |
| **ECR** | Store Docker image | ~$0.10/GB/month |
| **S3** | Store corpus + artifacts | ~$0.023/GB/month |
| **CloudWatch** | Container logs | ~$0.50/GB ingested |
| **Total (one run)** | | **~$2–4** |

---

## Project Structure

```
train-tokenizer/
├── README.md                                  # full project context
├── Dockerfile                                 # single image — stage set via STAGE env var
├── requirements.txt                           # Python dependencies
├── .gitignore
│
├── src/
│   ├── 01_ingest/
│   │   └── download.py                        # stream corpus, upload shards to S3
│   ├── 02_filter/
│   │   └── content_filter.py                  # detect & discard HTML, PDFs, binaries
│   ├── 03_extract/
│   │   └── text_extract.py                    # extract clean text from PDFs, HTML, OCR
│   ├── 04_encoding/
│   │   └── encoding_recovery.py               # detect and fix Unicode/encoding corruption
│   ├── 05_language/
│   │   └── lang_detect.py                     # tag documents by language, domain, source
│   ├── 06_deduplicate/
│   │   └── dedup.py                           # MinHash dedup, remove boilerplate
│   ├── 07_rebalance/
│   │   └── rebalance.py                       # weighted sampling across languages/domains
│   └── 08_train/
│       ├── train.py                           # BPE tokenizer training
│       └── validate.py                        # encode/decode validation, log stats
│
├── infra/
│   ├── setup.sh                               # provision ECR, Batch, Step Functions via AWS CLI
│   ├── batch/
│   │   └── job_definitions.json               # Batch job definition for each stage
│   └── stepfunctions/
│       └── state_machine.json                 # Step Functions state machine definition (ASL)
│
├── docs/
│   └── architecture.png                       # architecture diagram
│
└── .github/
    └── workflows/
        └── lint.yml                           # ruff lint + mypy type-check
```

---

## How to Run (One-Time Manual)

```bash
# 1. Provision all AWS resources (ECR, Batch, Step Functions)
bash infra/setup.sh

# 2. Build and push Docker image to ECR
aws ecr get-login-password | docker login --username AWS --password-stdin <ECR_URI>
docker build -t tokenizer .
docker tag tokenizer:latest <ECR_URI>/tokenizer:latest
docker push <ECR_URI>/tokenizer:latest

# 3. Trigger the full 8-stage pipeline (one command)
aws stepfunctions start-execution \
  --state-machine-arn <STATE_MACHINE_ARN> \
  --input '{"bucket": "<S3_BUCKET>", "vocab_size": 32000, "save_stages": false}'

# 4. Monitor in AWS Console → Step Functions → state machine execution
#    or watch CloudWatch Logs for each stage
```

---

## How Step Functions + Batch Works

```
Step Functions state machine
  ├── Each Task state calls: BatchSubmitJob API
  ├── Waits for job SUCCEEDED / FAILED
  ├── Passes S3 output path of stage N as input to stage N+1
  └── On any failure: execution stops, CloudWatch has full logs

Each Batch job
  ├── Pulls Docker image from ECR
  ├── Fargate spins up container (no EC2 managed)
  ├── Runs src/<stage>/<script>.py
  └── Exits — Fargate terminates automatically
```

---

## Status

- [ ] Tokenizer library chosen (HuggingFace / SentencePiece / tiktoken)
- [ ] `Dockerfile`
- [ ] `infra/setup.sh` — ECR + Batch + Step Functions provisioning
- [ ] `infra/batch/job_definitions.json`
- [ ] `infra/stepfunctions/state_machine.json`
- [ ] Stage 1: `01_ingest/download.py`
- [ ] Stage 2: `02_filter/content_filter.py`
- [ ] Stage 3: `03_extract/text_extract.py`
- [ ] Stage 4: `04_encoding/encoding_recovery.py`
- [ ] Stage 5: `05_language/lang_detect.py`
- [ ] Stage 6: `06_deduplicate/dedup.py`
- [ ] Stage 7: `07_rebalance/rebalance.py`
- [ ] Stage 8: `08_train/train.py` + `validate.py`
- [ ] Architecture diagram (`docs/architecture.png`)
- [ ] End-to-end tested on AWS
