# Predictive Flood Mobility handoff

## 1. What the feature does

- Estimates **relative** flood-related travel risk using hourly weather forecasts, reported flooding, and known hotspots.
- Compares supported vehicles and departure times: now, +15, +30, +45, and +60 minutes.
- Explains risk factors and reports when weather or flood data is unavailable. Missing data is not evidence that a route is safe or dry.
- Uses no Bedrock calls for predictive risk calculations.

## 2. How to deploy it

1. Pull the reviewed feature branch and check its changes before deployment.
2. Verify the AWS account, existing `scooter-cross` CloudFormation stack, and `ap-south-1` region with the stack owner. Treat those names as details to confirm, not assumptions.
3. From the repository root, build and validate the template:

   ```powershell
   sam validate --lint --template-file template.yaml
   sam build --template-file template.yaml --use-container
   ```

4. Prepare an update for the **existing** CloudFormation stack only. Review its change set before applying it. Preserve existing resources and parameter values; stop if it proposes unexpected replacements or changes. Do not create a new stack or deploy with guessed defaults.
5. After the approved backend update, verify that `POST /predictive-route` responds correctly through the existing API.
6. Build the frontend with `VITE_PREDICTIVE_ROUTE_ENABLED=true` and the correct existing `VITE_API_URL`. Enable the frontend flag only after the backend endpoint is working.
7. Upload the frontend build from `frontend\dist` to the **existing** Amplify app using its current ZIP deployment process. A GitHub push alone does not update that app.

Verify the stack name, region, API URL, Amplify app, and deployment procedure with the owner before use. The backend flag is the SAM parameter `PredictiveRouteEnabled`; it defaults to `false`. The frontend flag `VITE_PREDICTIVE_ROUTE_ENABLED` also defaults to `false`.

## 3. Before finishing

- [ ] Existing `/route` still works.
- [ ] Predictive endpoint responds correctly.
- [ ] Missing weather or flood data is reported honestly.
- [ ] DrainReady still works.
- [ ] Frontend works in English and Hindi.
- [ ] Frontend flag is enabled only after the backend endpoint works.
