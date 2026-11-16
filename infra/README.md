# weekcalendar on AWS

This replaces the Raspberry Pi. Two small Lambda functions in **eu-west-1 (Ireland)**:

| Piece | What it does |
|---|---|
| **Render** function (container image) | Runs every night at **03:30 Europe/Oslo** (before the frame's ~04:00 fetch). Fetches calendar, waste pickup and weather data, renders the 800x480 image with the same code as `main.py`, writes `latest/output.png`, `latest/output.jpg` and `latest/meta.json` to a private S3 bucket. |
| **Serve** function (small zip) with a public **Function URL** | Gives the frame the image. Every request needs the shared secret `FRAME_TOKEN`. |
| SSM Parameter Store `/weekcalendar/*` | All config and API keys (replaces `.env`). |
| S3 bucket | `latest/` (images + meta) and `cache/` (AI icon cache, Google Sheet mappings cache, downloaded icons). |

Endpoints (`<url>` is the `FunctionUrl` output, it ends with `/`):

| Request | Result |
|---|---|
| `GET <url>image.png?token=…` | Latest PNG (5–15 KB). Instant. **This is what the frame should fetch.** |
| `GET <url>image.jpg?token=…` | Latest JPEG (120–330 KB). |
| `GET <url>image.png?token=…&fresh=1` | Renders now, then returns the new image (for the frame's refresh button). Takes ~5–20 s, worst case ~70 s. If the render fails or is too slow you get the previous image with header `X-Render-Status: stale`. |
| `GET <url>status?token=…` | `meta.json`: when it last rendered, event count, errors, missing parameters. |
| `POST <url>render` with header `X-Run-Token: …` | Starts a render in the background, returns 202 at once. |

Wrong or missing token gives `401`.

> **Frame HTTP timeout:** for `fresh=1` the frame must wait up to ~60–75 s for the response. Set the HTTP/socket timeout in the frame's MicroPython code to at least 60 s for that request. Normal fetches (without `fresh=1`) return in well under a second.

The Pi setup (`main.py` + `server.py`) still works unchanged.

---

## One-time setup

You need: an AWS account, admin access to the GitHub repo. All `aws` commands below can be run in **AWS CloudShell** (the `>_` icon in the AWS console top bar, no install needed). Make sure the region selector in the console says **Europe (Ireland) eu-west-1**.

### 1. AWS account and a budget alarm

1. Create an AWS account at <https://aws.amazon.com> (needs a card).
2. Turn on MFA for the root user (IAM -> Security recommendations).
3. **Billing and Cost Management -> Budgets -> Create budget -> "Zero spend" or "Monthly cost budget"**. Choose a monthly budget of **$5** with an email alert at 80 %. Expected cost is a few cents a month, so any alert means something is wrong.

### 2. Let GitHub deploy (bootstrap.yaml)

1. Console -> **CloudFormation -> Create stack -> With new resources**.
2. **Upload a template file**: `infra/bootstrap.yaml` from this repo.
3. Stack name: `weekcalendar-bootstrap`. Keep the defaults:
   - `GitHubRepo` = `iamjorgensen/weekcalendar`
   - `AllowedRef` = `refs/heads/main` (only the `main` branch may deploy; set `*` temporarily if you want to deploy from another branch)
   - `CreateOidcProvider` = `true` (set it to `false` only if this AWS account already has a GitHub OIDC provider; otherwise the stack fails with "already exists")
4. Tick "I acknowledge that AWS CloudFormation might create IAM resources" -> Submit.
5. When it says `CREATE_COMPLETE`, open **Outputs** and copy `DeployRoleArn`.

### 3. GitHub repository variable

GitHub repo -> **Settings -> Secrets and variables -> Actions -> Variables -> New repository variable**:

- Name: `AWS_DEPLOY_ROLE_ARN`
- Value: the `DeployRoleArn` from step 2 (`arn:aws:iam::123456789012:role/weekcalendar-bootstrap-DeployRole-…`)

It is a variable, not a secret: the ARN is not sensitive, and no AWS keys are stored in GitHub at all.

### 4. Config and secrets in SSM Parameter Store

Create a frame token first (any long random string):

```bash
openssl rand -hex 24
```

Then, in CloudShell (replace every `<...>`; skip any line you don't use, all parameters except `FRAME_TOKEN` are optional):

```bash
R=eu-west-1
P=/weekcalendar

# required: shared secret the frame sends as ?token=
aws ssm put-parameter --region $R --overwrite --type SecureString --name $P/FRAME_TOKEN          --value '<random-token-from-openssl>'

# Google Calendar
aws ssm put-parameter --region $R --overwrite --type SecureString --name $P/API_KEY_GOOGLE       --value '<google-api-key>'
aws ssm put-parameter --region $R --overwrite --type SecureString --name $P/CALENDAR_ID          --value '<calendar-id>@group.calendar.google.com'
aws ssm put-parameter --region $R --overwrite --type String       --name $P/HOLIDAYS_CALENDAR_ID --value '<holidays-calendar-id>'

# Waste pickup (Movar)
aws ssm put-parameter --region $R --overwrite --type SecureString --name $P/MOVAR_API_TOKEN      --value '<movar-token>'
aws ssm put-parameter --region $R --overwrite --type String       --name $P/MOVAR_BASE           --value '<movar-base-url>'
aws ssm put-parameter --region $R --overwrite --type String       --name $P/KOMMUNENR            --value '<kommunenummer>'
aws ssm put-parameter --region $R --overwrite --type SecureString --name $P/MOVAR_GATENAVN       --value '<street-name>'
aws ssm put-parameter --region $R --overwrite --type SecureString --name $P/MOVAR_HUSNR          --value '<house-number>'

# Weather location
aws ssm put-parameter --region $R --overwrite --type String       --name $P/LAT                  --value '<latitude e.g. 59.91>'
aws ssm put-parameter --region $R --overwrite --type String       --name $P/LON                  --value '<longitude e.g. 10.75>'

# AI icon suggestions (optional)
aws ssm put-parameter --region $R --overwrite --type SecureString --name $P/OPENAI_API_KEY       --value '<openai-api-key>'
```

The values are the same as in the Pi's `.env`. Parameter Store standard parameters are free. SSM does not accept empty values: if you don't use something, just don't create it.

Changing a parameter later: run the same command again. The render function reads parameters on start-up; a container that is still warm keeps the old values for a while, so if you need it immediately, redeploy (step 5).

### 5. Deploy

GitHub -> **Actions -> Deploy to AWS -> Run workflow** (branch `main`).

It runs the tests, `sam build` (builds the Render container image) and `sam deploy` (stack `weekcalendar`, plus SAM's helper stacks for the artifact bucket and the image repository). The first run takes ~5 minutes. The last step prints the stack outputs:

- `FunctionUrl` – e.g. `https://abc123xyz.lambda-url.eu-west-1.on.aws/`
- `BucketName`

You can also find them later in CloudFormation -> `weekcalendar` -> Outputs.

### 6. Test

```bash
URL='https://<id>.lambda-url.eu-west-1.on.aws/'   # FunctionUrl output, with the trailing /
TOKEN='<FRAME_TOKEN>'

# render once now (otherwise the first image appears at 03:30)
curl -i -X POST -H "X-Run-Token: $TOKEN" "${URL}render"          # -> 202
sleep 30
curl -s "${URL}status?token=$TOKEN"                               # -> meta.json
curl -s -o calendar.png -D - "${URL}image.png?token=$TOKEN"        # -> 200, image/png
curl -s -o calendar.png -D - "${URL}image.png?token=$TOKEN&fresh=1"   # X-Render-Status: fresh
curl -i "${URL}image.png?token=wrong"                             # -> 401
```

Open `calendar.png` and check it. `status` lists `missing_params` and `errors` if something is not configured. Logs: CloudWatch -> Log groups -> `/aws/lambda/weekcalendar-render` (kept 14 days).

### 7. Point the frame at AWS

In the frame's config, replace the Pi URL with:

```
https://<id>.lambda-url.eu-west-1.on.aws/image.png?token=<FRAME_TOKEN>
```

and for the refresh button:

```
https://<id>.lambda-url.eu-west-1.on.aws/image.png?token=<FRAME_TOKEN>&fresh=1
```

with an HTTP timeout of at least 60 s for the refresh request. Once that works, the Pi can be switched off.

---

## Changing things

- **Render time:** template parameters `RenderHour` (default 3) and `RenderMinute` (default 30), Europe/Oslo time (summer time handled). Change the defaults in `infra/template.yaml`, or add `--parameter-overrides RenderHour=4 RenderMinute=0` to `sam deploy` in the workflow.
- **Days shown:** parameter `RenderDays` (default 7).
- **Rotate the frame token:** update `/weekcalendar/FRAME_TOKEN`, then update the frame. The serve function picks up the new value within 5 minutes.
- **Local test without AWS:** `pip install -r infra/requirements-lambda.txt boto3 "moto[s3,ssm]" pytest && pytest tests/test_aws_handlers.py`.
- **Remove everything:** delete the CloudFormation stacks `weekcalendar` (and its `…-CompanionStack`), then empty and delete the S3 bucket (it is kept on stack deletion on purpose) and the `aws-sam-cli-managed-default` stack, then `weekcalendar-bootstrap`.

## Cost

eu-west-1 prices, 1 render per day plus a few frame fetches. Most of this is inside the AWS free tier anyway.

| Service | Usage per month | Approx. cost |
|---|---|---|
| Lambda (render, 1 GB, ~15 s x 30) | ~450 GB-s | $0.01 (free tier: 400 000 GB-s) |
| Lambda (serve, 256 MB, ~100 requests) | negligible | $0.00 |
| Function URL | included in Lambda | $0.00 |
| ECR (render image, ~200–300 MB) | per stored image | ~$0.03 (old images from earlier deploys add ~$0.03 each; delete old ones in ECR occasionally) |
| S3 (< 1 MB, a few hundred requests) | | < $0.01 |
| SSM Parameter Store (standard) + KMS `aws/ssm` key | | $0.00 |
| EventBridge Scheduler (30 runs) | | $0.00 |
| CloudWatch Logs (14-day retention) | a few MB | $0.00 |
| Data transfer out (~15 KB x 100) | | $0.00 |
| **Total** | | **≈ $0.05 / month** |

## Security notes

- The bucket is private (public access blocked, TLS only). Only the two functions can touch it: the render function writes `latest/` and `cache/`, the serve function can only read `latest/`.
- Each function has its own minimal IAM role (render: S3 `latest/` + `cache/`, all `/weekcalendar/*` parameters; serve: read `latest/`, only the `FRAME_TOKEN` parameter, invoke the render function).
- The Function URL is public, but every route checks the token (constant-time compare). Treat the full image URL as a password: it contains the token.
- GitHub gets short-lived credentials through OIDC; no AWS keys are stored in GitHub. The deploy role can only be assumed from `iamjorgensen/weekcalendar` on `main` and only manages resources named `weekcalendar-*`. It can create IAM roles with that prefix (CloudFormation needs that for the function roles), so anyone who can push to `main` can effectively control those resources: keep branch protection on `main`.

---

## Phase 2 (design only, not built)

### A. Configurable sources

- **DynamoDB table `sources`** (on-demand, ~free): one item per source, e.g. `{id, type: "google_calendar" | "ics" | "movar" | "school_plan", name, config: {...}, enabled, color, child}`. Secrets stay in SSM; items reference them by parameter name.
- The render function reads enabled sources from the table instead of fixed env vars, with the current SSM parameters as the default when the table is empty.
- **Small admin web page**: a static page served by the serve function (`GET /admin`) plus JSON endpoints (`/api/sources`, `/api/events`). Auth: a separate `ADMIN_TOKEN`, or Cognito if more people need access. Lets you add/enable/disable sources and press "render now".

### B. School weekly letters ("ukebrev") -> events

The letters come from the school app, so ingestion starts on the phone:

1. **iPhone Shortcut in the Share Sheet** ("Send to calendar"): in the school app, share the PDF / screenshot / text -> the Shortcut `POST`s it to `<url>upload` with header `X-Run-Token` (body = file, `Content-Type` from the file). The serve function checks the token and stores it in S3 under `inbox/<timestamp>-<id>.<ext>`, returns 202.
2. **S3 event on `inbox/`** triggers a new **extraction Lambda**: PDF -> text (or the image directly), sent to an LLM with vision and a strict JSON schema. Output: a list of events
   `{date, time, title, kind: closed | early_finish | trip | gym | bring | special, child, notes}`,
   saved as `extracted/<id>.json` with status `pending_review`.
3. **Which child:** the letter names the grade ("6. trinn"). A small config (SSM parameter or DynamoDB item) maps each child to their grade **as of a school year**, e.g. `{"name": "<child>", "grade_2025": 5}`; the current grade is computed from the date and advances every August, so nobody has to edit it yearly. Letters for a grade with no matching child are flagged in review.
4. **Review in the admin page:** pending extractions are listed with the original file next to them; edit/approve/reject. Approved events go into a DynamoDB `events` table that the render function merges with the calendar (source type `school_plan`).
5. Cost: a few letters a week -> pennies of LLM usage; Lambda/S3/DynamoDB stay in the free tier.

**Optional later alternative:** SES email receiving (that is why the region is eu-west-1) writing to the same `inbox/` prefix, for schools that send the letters by email. The extraction and review steps stay the same.
