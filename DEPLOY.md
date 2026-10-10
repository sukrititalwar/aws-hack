# Deploy guide + what's left before submission

Everything runs in **ap-south-1 (Mumbai)**. Commands run from the repo root. First-time deploy takes about 45–60 min.

**Status (9 Oct 2026):** code complete and tested locally (67 backend tests pass, `sam build` succeeds, the frontend builds). **Not yet deployed to AWS.**

---

## 0. One-time setup on your laptop
```bash
brew install awscli aws-sam-cli          # macOS; see AWS docs for Windows/Linux
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
cd frontend && npm install && cd ..
```
Create an IAM user (`hackathon-deployer`, policy **AdministratorAccess**), create an **access key** for the CLI, then:
```bash
aws configure        # paste key + secret, region ap-south-1, output json
aws sts get-caller-identity
```

## 1. Console clicks (do these by hand)
1. **Bedrock** (region Mumbai): open *Anthropic Claude Sonnet 4* in the model catalog or playground and submit the one-time Anthropic use-case form. Then find the model ID:
   ```bash
   aws bedrock list-inference-profiles --region ap-south-1 --query "inferenceProfileSummaries[].inferenceProfileId" --output table
   ```
   Copy the `apac.anthropic.claude-sonnet-4-...` ID. If Claude isn't offered in Mumbai, use `us-east-1` with a `us.anthropic...` ID and `BedrockRegion=us-east-1`.
2. **Amazon Location** → *API keys* → Create. Allow **Maps** and **Places (Geocode)**. Copy the key for the frontend.

## 2. Backend (SAM)
```bash
sam build
sam deploy --guided
```
| Prompt | Answer |
|---|---|
| Stack name | `scooter-cross` |
| Region | `ap-south-1` |
| BedrockModelId / SocialModelId | ID from step 1 (a Haiku profile is fine for Social) |
| BedrockRegion | `ap-south-1` |
| AllowedOrigin | `*` for now |
| AlertEmail | team email (optional; confirm the SNS email) |
| AdminToken | a long random string; this is the **DrainReady dispatcher access code** (keep it private) |
| AppUrl, WhatsAppTopicArn, Reddit/X/YouTube keys | leave empty for now |
| "...may not have authorization defined, is this okay?" | `y` (public API) |
| Save to samconfig.toml | `Y` |

```bash
aws cloudformation describe-stacks --stack-name scooter-cross --query "Stacks[0].Outputs" --output table
```
Note **ApiUrl**, **PhotosBucketName**, **HotspotsTableName**, **ReportsTableName** and **WhatsAppTwilioWebhook**.

## 3. Data
```bash
export BUCKET=<PhotosBucketName> HOTSPOTS=<HotspotsTableName>
for c in delhi gurugram kochi; do .venv/bin/python scripts/build_graph.py --city $c --bucket $BUCKET; done
for c in delhi gurugram kochi; do .venv/bin/python scripts/seed_hotspots.py --city $c --table $HOTSPOTS; done
# optional, Delhi buses (DTC GTFS from https://mobilitydatabase.org/feeds/gtfs/mdb-3139):
.venv/bin/python scripts/import_gtfs.py --city delhi --gtfs ~/Downloads/delhi-bus.zip --bucket $BUCKET
# first live rain check now instead of waiting 15 min:
aws lambda invoke --function-name $(aws cloudformation describe-stack-resource --stack-name scooter-cross \
  --logical-resource-id RiskSchedulerFunction --query StackResourceDetail.PhysicalResourceId --output text) /dev/stdout
```
Smoke test:
```bash
curl "<ApiUrl>/hotspots?city=kochi"      # hotspots + "weather" with live rain
curl -X POST "<ApiUrl>/route" -d '{"from":[77.2205,28.632],"to":[77.2245,28.642],"vehicle":"scooter","city":"delhi","compare":true}'
```

## 4. Frontend on Amplify (from this GitHub repo)
Amplify console → **Create new app** → GitHub → `sukrititalwar/aws-hack`, branch `main` → tick **"My app is a monorepo"**, root `frontend` (it reads `amplify.yml`). Then set these environment variables:

| Variable | Value |
|---|---|
| `VITE_API_URL` | ApiUrl |
| `VITE_CITY` | `delhi` |
| `VITE_LOCATION_API_KEY` | key from step 1.2 |
| `VITE_LOCATION_REGION` | `ap-south-1` |
| `VITE_WHATSAPP_NUMBER` | `14155238886` (after step 6) |
| `VITE_WHATSAPP_JOIN` | `join <sandbox-code>` (after step 6) |

Deploy, then note the URL (`https://main.<id>.amplifyapp.com`). Every `git push` to `main` redeploys.

## 5. Lock CORS + WhatsApp links
`sam deploy --guided` again: set **AllowedOrigin** and **AppUrl** to the Amplify URL (no trailing `/`).

## 6. WhatsApp (Twilio sandbox, ~10 min)
1. twilio.com → sign up → *Messaging → Try it out → Send a WhatsApp message*. Each tester sends `join <code>` to **+1 415 523 8886**.
2. *Sandbox settings* → "When a message comes in" = **WhatsAppTwilioWebhook** output, **POST**.
3. Store credentials (Twilio console home):
   ```bash
   aws ssm put-parameter --name /scooter-cross/whatsapp/twilio_account_sid --type SecureString --value ACxxxxxxxx
   aws ssm put-parameter --name /scooter-cross/whatsapp/twilio_auth_token  --type SecureString --value <auth_token>
   aws ssm put-parameter --name /scooter-cross/whatsapp/twilio_from        --type String       --value whatsapp:+14155238886
   ```
4. WhatsApp "hi" to the number → instructions. Photo + location → verdict in ~15 s.

AWS-native alternative: AWS End User Messaging Social → link a WhatsApp Business account → choose an SNS topic → redeploy with `WhatsAppTopicArn=<topic>`.

## 7. DrainReady
Reporting needs no setup. Dispatchers open **🕳️ Blocked drains**, tap a blockage, expand **Dispatcher**, paste the **AdminToken**, then assign a worker and upload the after-photo. The drain is only marked cleared if the after-photo shows a clear drain. Check the numbers on the **Impact** tab. Local test: run `scripts/local_api.py` (access code `demo`).

## 8. Troubleshooting
```bash
sam logs --stack-name scooter-cross -n AnalyzeFunction --tail
```
| Symptom | Fix |
|---|---|
| Report stuck on "analysing", Bedrock `AccessDeniedException` | Model access form not done, or wrong model ID/region |
| CORS error in browser | `AllowedOrigin` must exactly equal the Amplify URL |
| "Routing is not available for this city" | Graph not uploaded (step 3) |
| WhatsApp silent / "bad Twilio signature" | Webhook URL must exactly match the output; check the auth token in SSM |
| No social pins | Normal when nobody is posting about waterlogging; check `SocialIngestFunction` logs |

---

## What's left before submission (11 Oct, 08:00 IST)
- [ ] **Demo photos**: 15–25 real past-monsoon photos you're allowed to use → `data/demo_photos/` + rows in `data/demo_photos.csv` (lat, lon, replay time, source, licence) → `scripts/seed_demo.py --bucket $BUCKET --table <ReportsTableName>`.
- [ ] **Demo social posts**: 40–80 real public posts from a past heavy-rain day → `data/social_demo_<city>.jsonl` → `scripts/seed_social.py --city delhi --demo --table <ReportsTableName>`.
- [ ] **Accuracy numbers**: 20–30 photos with known depth in `data/eval_set.csv` → `cd backend && ../.venv/bin/python -m tests.eval_depth` → paste the numbers into the README.
- [ ] **Hotspots**: add citations for Pragati Maidan tunnel, Moolchand and ITO (`verified: false` now), and verify Gurugram/Kochi police handles in `backend/common/social.py` (`OFFICIAL_HANDLES`).
- [ ] **Video (3 min)**: problem → photo verdict (EN + HI) → Kochi live rain banner → Delhi demo replay → "scooter detours, bus goes" comparison → WhatsApp report → AWS architecture + accuracy numbers.
- [ ] Optional: AWS Builder Center blog post.

## Cost + teardown
Mostly free tier. Bedrock is roughly ₹1 per photo, plus small social-extraction calls. Set a $10 budget alert. After the hackathon:
```bash
aws s3 rm s3://$BUCKET --recursive && sam delete --stack-name scooter-cross
```
