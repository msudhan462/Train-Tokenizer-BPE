#!/usr/bin/env bash
# Provision all AWS resources for the tokenizer pipeline.
# Usage: bash infra/setup.sh
# Requires: aws CLI configured with IAM permissions for ECR, S3, Batch, IAM, Step Functions.
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="tokenizer"
S3_BUCKET="${TOKENIZER_S3_BUCKET:-tokenizer-corpus-${ACCOUNT_ID}}"
BATCH_CE="tokenizer-compute-env"
BATCH_QUEUE="tokenizer-queue"
JOB_DEF_PREFIX="tokenizer-stage"
STATE_MACHINE_NAME="tokenizer-pipeline"
BATCH_ROLE_NAME="TokenizerBatchRole"
SF_ROLE_NAME="TokenizerStepFunctionsRole"

ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"

echo "=== Provisioning tokenizer pipeline ==="
echo "  Region:  $REGION"
echo "  Account: $ACCOUNT_ID"
echo "  Bucket:  s3://$S3_BUCKET"
echo "  ECR:     $ECR_URI"
echo ""

# ── 1. S3 ────────────────────────────────────────────────────────────────────
echo "[1/6] S3 bucket..."
if aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
    echo "  already exists"
else
    if [ "$REGION" = "us-east-1" ]; then
        aws s3api create-bucket --bucket "$S3_BUCKET" --region "$REGION"
    else
        aws s3api create-bucket --bucket "$S3_BUCKET" --region "$REGION" \
            --create-bucket-configuration LocationConstraint="$REGION"
    fi
    aws s3api put-bucket-versioning --bucket "$S3_BUCKET" \
        --versioning-configuration Status=Enabled
    aws s3api put-public-access-block --bucket "$S3_BUCKET" \
        --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
    echo "  created: s3://$S3_BUCKET"
fi

# ── 2. ECR ───────────────────────────────────────────────────────────────────
echo "[2/6] ECR repository..."
if aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" &>/dev/null; then
    echo "  already exists"
else
    aws ecr create-repository --repository-name "$ECR_REPO" --region "$REGION" \
        --image-scanning-configuration scanOnPush=true \
        --image-tag-mutability MUTABLE
    echo "  created: $ECR_URI"
fi

# ── 3. IAM roles ─────────────────────────────────────────────────────────────
echo "[3/6] IAM roles..."

BATCH_TRUST='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": ["batch.amazonaws.com", "ecs-tasks.amazonaws.com"]},
    "Action": "sts:AssumeRole"
  }]
}'

if ! aws iam get-role --role-name "$BATCH_ROLE_NAME" &>/dev/null; then
    aws iam create-role --role-name "$BATCH_ROLE_NAME" \
        --assume-role-policy-document "$BATCH_TRUST"
    aws iam attach-role-policy --role-name "$BATCH_ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
    aws iam attach-role-policy --role-name "$BATCH_ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
    aws iam attach-role-policy --role-name "$BATCH_ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/CloudWatchLogsFullAccess
    echo "  created role: $BATCH_ROLE_NAME"
else
    echo "  role $BATCH_ROLE_NAME already exists"
fi
BATCH_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${BATCH_ROLE_NAME}"

SF_TRUST='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "states.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

if ! aws iam get-role --role-name "$SF_ROLE_NAME" &>/dev/null; then
    aws iam create-role --role-name "$SF_ROLE_NAME" \
        --assume-role-policy-document "$SF_TRUST"
    aws iam attach-role-policy --role-name "$SF_ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/AWSBatchFullAccess
    aws iam attach-role-policy --role-name "$SF_ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/CloudWatchEventsFullAccess
    echo "  created role: $SF_ROLE_NAME"
else
    echo "  role $SF_ROLE_NAME already exists"
fi
SF_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${SF_ROLE_NAME}"

# ── 4. Batch compute environment + queue ─────────────────────────────────────
echo "[4/6] Batch compute environment + queue..."

DEFAULT_SUBNET=$(aws ec2 describe-subnets \
    --query 'Subnets[0].SubnetId' --output text)
DEFAULT_SG=$(aws ec2 describe-security-groups \
    --filters Name=group-name,Values=default \
    --query 'SecurityGroups[0].GroupId' --output text)

CE_EXISTS=$(aws batch describe-compute-environments \
    --compute-environments "$BATCH_CE" \
    --query 'computeEnvironments[0].status' --output text 2>/dev/null || echo "NONE")

if [ "$CE_EXISTS" = "NONE" ] || [ "$CE_EXISTS" = "None" ]; then
    aws batch create-compute-environment \
        --compute-environment-name "$BATCH_CE" \
        --type MANAGED \
        --state ENABLED \
        --compute-resources "{
            \"type\": \"FARGATE\",
            \"maxvCpus\": 256,
            \"subnets\": [\"${DEFAULT_SUBNET}\"],
            \"securityGroupIds\": [\"${DEFAULT_SG}\"],
            \"executionRoleArn\": \"${BATCH_ROLE_ARN}\"
        }"
    echo "  compute environment created (waiting for VALID...)"
    sleep 30
else
    echo "  compute environment already exists ($CE_EXISTS)"
fi

QUEUE_EXISTS=$(aws batch describe-job-queues \
    --job-queues "$BATCH_QUEUE" \
    --query 'jobQueues[0].status' --output text 2>/dev/null || echo "NONE")

if [ "$QUEUE_EXISTS" = "NONE" ] || [ "$QUEUE_EXISTS" = "None" ]; then
    aws batch create-job-queue \
        --job-queue-name "$BATCH_QUEUE" \
        --state ENABLED \
        --priority 100 \
        --compute-environment-order "[{\"order\": 1, \"computeEnvironment\": \"${BATCH_CE}\"}]"
    echo "  job queue created"
else
    echo "  job queue already exists ($QUEUE_EXISTS)"
fi

# ── 5. Batch job definitions ──────────────────────────────────────────────────
echo "[5/6] Registering Batch job definitions..."

LOG_GROUP="/aws/batch/tokenizer"
aws logs create-log-group --log-group-name "$LOG_GROUP" 2>/dev/null || true

declare -A STAGE_SCRIPTS=(
    ["01_ingest"]="src/01_ingest/download.py"
    ["02_filter"]="src/02_filter/content_filter.py"
    ["03_extract"]="src/03_extract/text_extract.py"
    ["04_encoding"]="src/04_encoding/encoding_recovery.py"
    ["05_language"]="src/05_language/lang_detect.py"
    ["06_deduplicate"]="src/06_deduplicate/dedup.py"
    ["07_rebalance"]="src/07_rebalance/rebalance.py"
    ["08_train"]="src/08_train/train.py"
    ["08_validate"]="src/08_train/validate.py"
)

for stage in 01_ingest 02_filter 03_extract 04_encoding 05_language 06_deduplicate 07_rebalance 08_train 08_validate; do
    script="${STAGE_SCRIPTS[$stage]}"
    job_name="${JOB_DEF_PREFIX}-${stage}"
    aws batch register-job-definition \
        --job-definition-name "$job_name" \
        --type container \
        --platform-capabilities FARGATE \
        --container-properties "{
            \"image\": \"${ECR_URI}:latest\",
            \"command\": [\"${script}\"],
            \"executionRoleArn\": \"${BATCH_ROLE_ARN}\",
            \"jobRoleArn\": \"${BATCH_ROLE_ARN}\",
            \"resourceRequirements\": [
                {\"type\": \"VCPU\", \"value\": \"4\"},
                {\"type\": \"MEMORY\", \"value\": \"16384\"}
            ],
            \"environment\": [
                {\"name\": \"S3_BUCKET\", \"value\": \"${S3_BUCKET}\"}
            ],
            \"logConfiguration\": {
                \"logDriver\": \"awslogs\",
                \"options\": {
                    \"awslogs-group\": \"${LOG_GROUP}\",
                    \"awslogs-region\": \"${REGION}\",
                    \"awslogs-stream-prefix\": \"${stage}\"
                }
            },
            \"networkConfiguration\": {
                \"assignPublicIp\": \"ENABLED\"
            }
        }" \
        --query 'jobDefinitionArn' --output text
    echo "  registered: $job_name"
done

# ── 6. Step Functions state machine ──────────────────────────────────────────
echo "[6/6] Step Functions state machine..."

STATE_DEF=$(sed \
    -e "s|__ACCOUNT_ID__|${ACCOUNT_ID}|g" \
    -e "s|__REGION__|${REGION}|g" \
    -e "s|__S3_BUCKET__|${S3_BUCKET}|g" \
    -e "s|__BATCH_QUEUE__|${BATCH_QUEUE}|g" \
    -e "s|__JOB_DEF_PREFIX__|${JOB_DEF_PREFIX}|g" \
    infra/stepfunctions/state_machine.json)

EXISTING_ARN=$(aws stepfunctions list-state-machines \
    --query "stateMachines[?name=='${STATE_MACHINE_NAME}'].stateMachineArn | [0]" \
    --output text 2>/dev/null || echo "None")

if [ "$EXISTING_ARN" = "None" ] || [ -z "$EXISTING_ARN" ]; then
    STATE_MACHINE_ARN=$(aws stepfunctions create-state-machine \
        --name "$STATE_MACHINE_NAME" \
        --definition "$STATE_DEF" \
        --role-arn "$SF_ROLE_ARN" \
        --query 'stateMachineArn' --output text)
    echo "  state machine created"
else
    aws stepfunctions update-state-machine \
        --state-machine-arn "$EXISTING_ARN" \
        --definition "$STATE_DEF" \
        --role-arn "$SF_ROLE_ARN"
    STATE_MACHINE_ARN="$EXISTING_ARN"
    echo "  state machine updated"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=== Setup complete ==="
echo "  ECR URI:       $ECR_URI"
echo "  S3 Bucket:     s3://$S3_BUCKET"
echo "  Batch Queue:   $BATCH_QUEUE"
echo "  State Machine: $STATE_MACHINE_ARN"
echo ""
echo "Next: build and push the Docker image"
echo "  aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR_URI"
echo "  docker build -t tokenizer ."
echo "  docker tag tokenizer:latest $ECR_URI:latest"
echo "  docker push $ECR_URI:latest"
echo ""
echo "Then start a pipeline run:"
echo "  aws stepfunctions start-execution \\"
echo "    --state-machine-arn $STATE_MACHINE_ARN \\"
echo "    --input '{\"bucket\": \"$S3_BUCKET\", \"run_id\": \"run_001\", \"vocab_size\": \"32000\"}'"
