# ChatOpsBot

<img width="307" height="236" alt="image" src="https://github.com/user-attachments/assets/5b969cf8-5825-4f0e-8023-6488b3dd724e" />

# 💰 Cost Sheriff Bot

> A ChatOpsBot automation that hunts idle AWS resources, estimates monthly waste, and posts a detailed report to Slack — on demand or on a schedule.

Part of the [ChatOpsBot](../README.md) project: a Slack-native operations platform built on Amazon Q Developer, Lambda, CloudWatch, SNS, and SSM Automation.

---

## What it does

Cost Sheriff scans your AWS account for resources that are running but unused, calculates their monthly cost, and posts a formatted report to Slack. Optionally, it can auto-remediate (delete/release) idle resources when you're ready to pull the trigger.

| Resource | How "idle" is defined | Est. monthly cost |
|---|---|---|
| **EBS Volume** | Status = `available` (no instance attached) | `size_GB × $0.10` |
| **Elastic IP** | No `AssociationId` (not attached to anything) | `~$3.60` flat |
| **NAT Gateway** | State = `available` + 0 bytes processed in last 24h | `~$32.40` flat |
| **EBS Snapshot** | Older than `SNAPSHOT_AGE_DAYS` (default 90 days) | `size_GB × $0.05` |

---

## Architecture

```
Slack slash command
      │
      ▼
Amazon Q Developer          (routes /cost-sheriff commands)
      │
      ▼
AWS Lambda                  (cost_sheriff.py — scanner + formatter)
      │
      ├──► EC2 APIs         (DescribeVolumes, DescribeAddresses, DescribeNatGateways, DescribeSnapshots)
      ├──► CloudWatch       (GetMetricStatistics — NAT Gateway bytes)
      │
      ├──► Slack Webhook    (Block Kit report)
      └──► SNS Topic        (cost-sheriff-alerts — feeds CloudFront dashboard)

SSM Automation Document     (CostSheriff-IdleResourceScan)
      │
      └──► Lambda           (scheduled or on-demand audit trail)
```

---

## Slack commands

| Command | Action |
|---|---|
| `/cost-sheriff scan` | Scan all regions, post report — no changes made |
| `/cost-sheriff remediate` | Scan then delete/release idle resources (`DRY_RUN=false` required) |

### Example Slack report

```
💰 Cost Sheriff Report
Scanned: 2024-11-15 08:00 UTC   Mode: 🔍 Dry Run
Regions: us-east-1, us-west-2   Est. Monthly Waste: $214.40

📍 Region: us-east-1
💾 EBS Volume — 4 found — $62.00/mo
  • vol-0a1b2c3d  data-backup   500 GiB gp3 — $50.00/mo
  • vol-0e4f5a6b  —             120 GiB gp2 — $12.00/mo

🌐 Elastic IP — 3 found — $10.80/mo
  • eipalloc-abc  3.14.159.26  — $3.60/mo
  ...

Run /cost-sheriff remediate to clean up • Cost Sheriff Bot v1.0
```

---

## Project structure

```
cost-sheriff-bot/
├── lambda/
│   └── cost_sheriff.py          # Lambda handler — scanner, formatter, remediator
├── ssm/
│   └── CostSheriff-IdleResourceScan.yaml   # SSM Automation document
├── cloudformation/
│   └── template.yaml            # Full stack deployment
├── iam/
│   └── lambda-policy.json       # Least-privilege IAM policy
└── tests/
    └── test_cost_sheriff.py     # Unit tests (pytest)
```

---

## Deployment

### Prerequisites

- AWS CLI configured with appropriate permissions
- Python 3.12+
- An incoming Slack webhook URL ([create one here](https://api.slack.com/messaging/webhooks))

### 1. Deploy via CloudFormation

```bash
aws cloudformation deploy \
  --template-file cloudformation/template.yaml \
  --stack-name cost-sheriff-bot \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      SlackWebhookUrl=https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
      Regions="us-east-1,us-west-2" \
      DryRun=true \
      ScheduleExpression="cron(0 8 * * ? *)"
```

### 2. Deploy the Lambda code

```bash
cd lambda
zip -r ../cost-sheriff.zip cost_sheriff.py

aws lambda update-function-code \
  --function-name cost-sheriff-bot \
  --zip-file fileb://../cost-sheriff.zip
```

### 3. Register the SSM Automation document

```bash
aws ssm create-document \
  --name CostSheriff-IdleResourceScan \
  --document-type Automation \
  --document-format YAML \
  --content file://ssm/CostSheriff-IdleResourceScan.yaml
```

### 4. Test a scan

```bash
# Dry run via Lambda invoke
aws lambda invoke \
  --function-name cost-sheriff-bot \
  --payload '{"command": "scan"}' \
  --cli-binary-format raw-in-base64-out \
  response.json && cat response.json

# Via SSM Automation
aws ssm start-automation-execution \
  --document-name CostSheriff-IdleResourceScan \
  --parameters "LambdaFunctionName=cost-sheriff-bot,DryRun=true,Command=scan"
```

---

## Configuration

All settings are Lambda environment variables. Override at deploy time or update in the AWS console.

| Variable | Default | Description |
|---|---|---|
| `SLACK_WEBHOOK_URL` | _(required)_ | Incoming webhook for your Slack channel |
| `REGIONS` | `us-east-1` | Comma-separated regions to scan |
| `DRY_RUN` | `true` | `false` enables actual deletion of resources |
| `SNAPSHOT_AGE_DAYS` | `90` | Snapshots older than this are flagged |
| `SNS_TOPIC_ARN` | _(optional)_ | Publishes JSON summary to SNS after each scan |

---

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

---

## IAM permissions

The Lambda role uses least-privilege permissions. Read operations (`Describe*`) are always allowed. Write/delete operations (`DeleteVolume`, `ReleaseAddress`, etc.) are scoped to specific regions via a condition key and are only exercised when `DRY_RUN=false` and `command=remediate`.

See [`iam/lambda-policy.json`](iam/lambda-policy.json) for the full policy.

---

## Extending the bot

Cost Sheriff is designed to be extended. To add a new resource type:

1. Add a `find_*` function in `cost_sheriff.py` following the existing pattern — return a list of dicts with `resource_type`, `resource_id`, `detail`, `monthly_cost_usd`, and `tags`.
2. Call it inside `lambda_handler` alongside the existing finders.
3. Add a corresponding branch in `remediate()` if deletion makes sense.
4. Write a unit test in `tests/test_cost_sheriff.py`.

Good candidates to add next: unused Load Balancers, idle RDS instances, orphaned AMIs.

---

## License

MIT

