# Deployment handoff

This project already has a deployed AWS SAM stack and a ZIP-deployed Amplify
frontend. These instructions are for preparing and reviewing an update to that
existing deployment only. Do **not** create another stack or Amplify app, run
`sam delete`, or deploy the template as a fresh stack.

The reported deployment uses stack `scooter-cross` in `ap-south-1` and the
existing Amplify `main` app. Verify those names, the AWS account, current stack
status, template, parameters, API URL, CORS origin, and the team's established
ZIP-upload procedure with the stack owner immediately before any deployment.
Those deployment details are supplied handoff information, not independently
verified here.

Predictive Flood Mobility is experimental and disabled by default. Its
`POST /predictive-route` API event is attached to the existing `RouteFunction`;
it adds no Lambda function, table, or bucket. SAM will update the existing HTTP
API and may create/update generated API integration or Lambda permission
resources for the new event. Existing `/route`, DrainReady, and other API
behaviors are intended to remain unchanged.

## 1. Code preparation (local; no AWS changes)

From the repository root, validate and build the template and run the relevant
application checks:

```powershell
sam validate --lint --template-file template.yaml
sam build --template-file template.yaml --use-container
python -B -m pytest -q -p no:cacheprovider .\backend\tests
Set-Location .\frontend
npm ci
npm run typecheck
npm run build
```

`npm ci` is for a clean dependency install from the checked-in lockfile; do not
change dependency manifests just to perform this check. A successful local
build does not verify AWS permissions, deployment, forecast-provider access, or
live application behavior.

Keep `PredictiveRouteEnabled=false` and
`VITE_PREDICTIVE_ROUTE_ENABLED=false` until backend and frontend rollout are
approved. The frontend build flag is compile-time configuration.

## 2. Backend update (existing stack only; requires separate approval)

Before preparing a CloudFormation change set:

1. Use an authorized AWS identity and confirm the account and region are the
   owner's intended `ap-south-1` account. Never put access keys, `AdminToken`,
   or other secret values in source control or shell history.
2. Inspect the live `scooter-cross` stack status, deployed template, parameter
   values, and outputs. Confirm it is the existing stack and is stable. Check
   its current API routes and `RouteFunction` configuration.
3. Compare the built template with the deployed template. Preserve existing
   stack parameters, resource names, API settings, CORS allow-origin, IAM
   configuration, and unrelated resources. Do not substitute defaults for
   existing values or copy the examples from an initial-deployment guide.
4. Create a change set for the existing stack only. Review every resource
   action and property difference before execution. Expected application
   changes are an additional `POST /predictive-route` API route, any generated
   integration/permission resources for it, and a `PREDICTIVE_ROUTE_ENABLED`
   environment setting on `RouteFunction`; reject unexpected
   replacements/deletions or changes to unrelated Lambda configuration,
   DrainReady, tables, buckets, CORS, or existing routes.
5. Keep the backend feature parameter false for the first update. If a change
   set proposes resource replacement or any unexpected change, do not execute
   it; ask the stack owner to investigate.

When (and only when) the stack owner has approved an update and supplied an
audited SAM deploy configuration containing the existing stack's parameter
values, the change-set-only command has this form:

```powershell
sam deploy --template-file .aws-sam\build\template.yaml `
  --stack-name scooter-cross --region ap-south-1 --capabilities CAPABILITY_IAM `
  --config-file <owner-approved-config-file> --config-env <verified-environment> `
  --no-execute-changeset
```

The placeholders must be replaced with the owner's verified configuration.
If no configuration that preserves the deployed parameter values is available,
stop and ask the owner to establish one; do not rely on template defaults or
guess values. Keep secret values out of the repository and shell history. The
command prepares a change set only: inspect it in CloudFormation and require
the owner's explicit approval before anyone executes it.

The template defaults `PredictiveRouteEnabled` to `false`. For a later,
separately approved enablement, set it to `true` through an update to the
existing stack only after reviewing that update's change set. Do not use
`sam deploy --guided` as a shortcut for this existing stack, and do not execute
a change set without the owner's approval.

Before an approved update, retain the deployed template and parameter
configuration and the currently hosted frontend ZIP as rollback references.
CloudFormation normally rolls back a failed stack update, but that does not
replace reviewing the change set or retaining recovery artifacts. If an update
fails or has an unexpected effect, stop further updates and follow the
owner-approved CloudFormation rollback/recovery procedure. Never delete the
stack as a rollback.

After backend approval and execution, verify in AWS that the stack update
completed, the existing API exposes `POST /predictive-route`, the route is
integrated with the existing `RouteFunction`, and the function has the intended
feature-gate value. Test the endpoint with a controlled request and inspect
logs. These checks require AWS access; local tests are not a substitute.

## 3. Frontend update (existing ZIP-deployed Amplify app only)

Use the existing Amplify app and its established ZIP upload procedure; do not
create an Amplify app, connect a new Git branch, or assume a Git push deploys
this frontend. Confirm the currently deployed API URL, Location key/region,
city, CORS origin, and the app's artifact/upload process with its owner.

Build from the reviewed feature revision with the existing frontend environment
values preserved. Set `VITE_PREDICTIVE_ROUTE_ENABLED=true` only after the
backend route is deployed and enabled; otherwise leave it `false`. Build output
is in `frontend\dist` after `npm run build`. Upload that artifact using the
owner's existing ZIP deployment workflow and retain the previously deployed
ZIP so the frontend can be rolled back independently.

For a coordinated enablement, deploy and verify the backend first, then publish
the frontend with the flag on. If the API is unavailable or backend enablement
is deferred, publish with the frontend flag off. After upload, verify the
existing hosted application, check browser/API errors, and confirm ordinary
route planning, reports, and DrainReady remain operational.

## Existing service operations (unchanged)

### WhatsApp

The existing Twilio sandbox webhook and credentials are separate from
predictive routing. Preserve their current configuration. Do not print or
commit credentials. Test the webhook only through the team's authorized
procedure.

### DrainReady

DrainReady remains part of the existing application and is not a target of this
feature update. Do not change its handlers, tables, S3 triggers, dispatcher
token, or environment settings. A deployment change set must be checked for
unintended DrainReady changes before execution.

### Troubleshooting

Use the existing stack's CloudWatch logs and operational runbooks. A missing
route graph, API/CORS errors, forecast-provider failure, or missing report data
should be diagnosed without changing unrelated AWS resources. The predictive
feature reports unavailable data explicitly and does not treat missing data as
evidence of safe or dry roads.

For example, inspect the existing analysis function logs with the stack owner's
approved AWS identity:

```powershell
sam logs --stack-name scooter-cross --region ap-south-1 -n AnalyzeFunction --tail
```

| Symptom | Check |
|---|---|
| Report stuck on "analysing", Bedrock `AccessDeniedException` | Verify model access, model ID, and region with the account owner. |
| CORS error in browser | Compare the live API CORS origin with the existing Amplify URL; do not broaden it as a workaround. |
| "Routing is not available for this city" | Confirm the required road graph exists in the existing data bucket. |
| WhatsApp silent / "bad Twilio signature" | Confirm the webhook URL and existing SSM credentials using the approved runbook. Never print credentials. |
| No social pins | Check the existing `SocialIngestFunction` schedule and logs; no posts may be available. |

## Existing demo and submission notes

These are separate from Predictive Flood Mobility and do not need changes for
its handoff:

- **Demo photos:** use only photos you're allowed to use; record source and
  licence information before loading demo data.
- **Demo social posts:** use public posts and retain their source information.
- **Accuracy numbers:** run the existing depth evaluation set and report its
  measured results; do not infer accuracy from mocked tests.
- **Hotspots:** retain citations and verification status for every seeded
  hotspot.
- **Demo video:** distinguish prototype behavior and local tests from verified
  live AWS behavior.

## Cost and teardown

Use the account owner's cost controls and operational procedure. Any teardown
is a separately approved destructive operation: confirm data backups, effects
on the existing app and users, and ownership of every resource first. Do not
use teardown or stack deletion as a rollback for this feature.
