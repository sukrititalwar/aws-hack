# Deployment status: what is actually running on AWS

Verified with the AWS CLI on **11 Oct 2026, 11:47 IST**. See [How to re-check](#how-to-re-check) to refresh it.

**Summary:** the SAM stack is fully deployed and healthy. All 58 resources are in a `*_COMPLETE` state, with none failed or stuck.

| | |
|---|---|
| Live app (Amplify) | https://main.d5e2kevy286g7.amplifyapp.com |
| API | https://uuastysok5.execute-api.ap-south-1.amazonaws.com |
| Region | ap-south-1 (Mumbai) |

## Stack

| Item | Value |
|---|---|
| Stack | `scooter-cross` |
| Status | **UPDATE_COMPLETE** |
| Created / last updated | 10 Oct 23:12 IST / 11 Oct 00:56 IST |
| Resources | 12 Lambda functions, 1 HTTP API + stage, 6 DynamoDB tables, 1 S3 bucket, 2 Scheduler schedules, 1 SNS topic, 14 IAM roles, 20 Lambda permissions |

## Lambda functions (12)

All Python 3.12 on arm64, last deployed 00:56 IST.

| Function | Memory | Timeout | Triggered by |
|---|---|---|---|
| AnalyzeFunction | 1024 MB | 90 s | S3 `uploads/` |
| DrainAnalyzeFunction | 1024 MB | 90 s | S3 `drains/` and `drains-after/` |
| RouteFunction | 1769 MB | 29 s | API `POST /route`, `GET /bus-impact` |
| SocialIngestFunction | 512 MB | 300 s | Schedule, every 10 min |
| RiskSchedulerFunction | 512 MB | 60 s | Schedule, every 15 min |
| WhatsAppFunction | 512 MB | 20 s | API `POST /whatsapp/twilio` |
| Reports, Hotspots, Drains, UploadUrl, Vote, Subscribe | 512 MB | 15 s | API routes |

## API Gateway

- **HTTP API** `uuastysok5`, stage `$default` with auto-deploy on.
- **CORS** allows only `https://main.d5e2kevy286g7.amplifyapp.com`.
- **17 routes:**
  - `GET /hotspots`, `/spots`, `/reports`, `/reports/{id}`, `/demo/timeline`, `/bus-impact`, `/drains`, `/drains/{id}`, `/drains/metrics`
  - `POST /reports/upload-url`, `/reports/{id}/vote`, `/route`, `/subscriptions`, `/drains/upload-url`, `/drains/{id}/assign`, `/drains/{id}/after-url`, `/whatsapp/twilio`

## DynamoDB tables (6)

All ACTIVE, on-demand (pay-per-request) billing.

| Table | Indexes | TTL | Stream | Contents |
|---|---|---|---|---|
| Reports | 2 (byCell, byCity) | on | on, no consumer | 0 reports |
| Hotspots | 0 | off | — | 20 verified hotspots + weather records |
| Drains | 1 | off | — | empty |
| Subscriptions | 0 | off | — | empty |
| RateLimit | 0 | on | — | empty |
| WhatsAppSessions | 0 | on | — | empty |

- **Hotspot count:** AWS refreshes table item counts only every few hours, so treat counts from `describe-table` as approximate.
- **Reports stream:** it's turned on, but no Lambda reads from it. It's reserved for a planned escalation feature that hasn't been built. It's harmless and costs nothing.

## S3 bucket and triggers

**Bucket:** `scooter-cross-photos-011713309588`, with all public access blocked.

**Triggers (3), all on `s3:ObjectCreated:*`:**

| Prefix | Function |
|---|---|
| `uploads/` | AnalyzeFunction |
| `drains/` | DrainAnalyzeFunction |
| `drains-after/` | DrainAnalyzeFunction |

**Contents:**

| Prefix | What |
|---|---|
| `graphs/` | Road graphs for 4 cities. Delhi covers central Delhi plus north-west Delhi (DTU, Rohini, Samaypur Badli) |
| `bus/` | Bus routes for 3 cities (Gurugram, Kochi, Mumbai) |
| `social/raw/` | Raw posts archived by the social scan |
| `uploads/` | 1 test photo. Its analysis failed because Bedrock is blocked (see below) |

## EventBridge Scheduler (2 schedules)

| Schedule | Rate | State | Target |
|---|---|---|---|
| RiskSchedulerFunctionEvery15Min | `rate(15 minutes)` | ENABLED | RiskSchedulerFunction |
| SocialIngestFunctionEvery10Min | `rate(10 minutes)` | ENABLED | SocialIngestFunction |

Both ran most recently at 11:44 IST.

## SNS

- **Topic** `scooter-cross-AlertsTopic-…`, part of the stack. It has no subscriptions, because no `AlertEmail` was set at deploy time.

## Outside the SAM stack

These were created separately with the CLI, so `sam delete` won't remove them:

- **Amplify app** `d5e2kevy286g7`, branch `main`. This is deployed by uploading a zip, not linked to GitHub.
- **Amazon Location API key** `scooter-cross-web`. It only works from the Amplify site and `localhost:5173`.

## Known blocker: Bedrock

Every Amazon Bedrock on-demand quota on this new account is **0**, so every model call fails with `Operation not allowed`. This affects:

- **Photo → depth → verdict**
- **DrainReady photo checks**
- **Social post extraction**

Two quota increase requests are open with AWS (status `CASE_OPENED`): Claude Sonnet 5 tokens per minute and Claude Haiku 4.5 requests per minute. The deployed code needs no change; it starts working as soon as AWS raises the quotas.

## How to re-check

```bash
R="--region ap-south-1"
aws cloudformation describe-stacks $R --stack-name scooter-cross --query "Stacks[0].StackStatus"
aws cloudformation list-stack-resources $R --stack-name scooter-cross \
  --query "StackResourceSummaries[?!ends_with(ResourceStatus,'_COMPLETE')]"   # empty = all healthy
aws lambda list-functions $R --query "Functions[?starts_with(FunctionName,'scooter-cross')].FunctionName"
aws apigatewayv2 get-routes $R --api-id uuastysok5 --query "Items[].RouteKey"
aws s3api get-bucket-notification-configuration --bucket scooter-cross-photos-011713309588
aws scheduler list-schedules $R
aws service-quotas list-requested-service-quota-change-history $R --service-code bedrock \
  --query "RequestedQuotas[].[QuotaName,Status]"
```

On Windows Git Bash, run `export MSYS_NO_PATHCONV=1` first, so paths like `/aws/lambda/...` are not rewritten.
