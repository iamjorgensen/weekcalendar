# weekcalendar on AWS

The backend: small Lambda functions in **eu-west-1 (Ireland)**:

| Piece | What it does |
|---|---|
| **Render** function (container image) | Runs **when the frame asks for it** (`image.png?fresh=1`, at the frame's ~04:00 wake-up and on its refresh button). Optionally also on a nightly schedule (off by default, see *Changing things*). Fetches calendar, waste pickup and weather data, renders the 800x480 image with the same code as `main.py`, writes `latest/output.png`, `latest/output.jpg` and `latest/meta.json` to a private S3 bucket. |
| **Serve** function (small zip) with a public **Function URL** | Gives the frame the image. Every request needs the shared secret `FRAME_TOKEN`. |
| SSM Parameter Store `/weekcalendar/*` | All config and API keys. |
| S3 bucket | `latest/` (images + meta) and `cache/` (AI icon cache, Google Sheet mappings cache, downloaded icons). |

Endpoints (`<url>` is the `FunctionUrl` output, it ends with `/`):

| Request | Result |
|---|---|
| `GET <url>image.png?token=…` | Latest PNG (5–15 KB), no new render. Instant. |
| `GET <url>image.jpg?token=…` | Latest JPEG (120–330 KB). |
| `GET <url>image.png?token=…&fresh=1` | Renders now, then returns the new image. **This is what the frame should request** (at wake-up and on the refresh button). Takes ~5–20 s, worst case ~70 s. If the render fails or is too slow you get the previous image with header `X-Render-Status: stale`. |
| `GET <url>status?token=…` | `meta.json`: when it last rendered, event count, errors, missing parameters. |
| `POST <url>render` with header `X-Run-Token: …` | Starts a render in the background, returns 202 at once. |

Wrong or missing token gives `401`.

> **Frame HTTP timeout:** for `fresh=1` the frame must wait up to ~60–75 s for the response. Set the HTTP/socket timeout in the frame's MicroPython code to at least 60 s for that request. Normal fetches (without `fresh=1`) return in well under a second.


---

## One-time setup

**Shortcut:** steps 2 and 4 below can be done in one go. Open AWS CloudShell in eu-west-1 and run
`bash <(curl -fsSL https://raw.githubusercontent.com/iamjorgensen/weekcalendar/feat/aws-lambda/infra/setup.sh)`,
then paste your settings as `KEY=value` lines when asked. It creates the deploy role, stores the settings in SSM and makes a FRAME_TOKEN.

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

Parameter Store standard parameters are free. SSM does not accept empty values: if you don't use something, just don't create it.

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

# render once now (otherwise the first image appears on the frame's first fresh=1 request)
curl -i -X POST -H "X-Run-Token: $TOKEN" "${URL}render"          # -> 202
sleep 30
curl -s "${URL}status?token=$TOKEN"                               # -> meta.json
curl -s -o calendar.png -D - "${URL}image.png?token=$TOKEN"        # -> 200, image/png
curl -s -o calendar.png -D - "${URL}image.png?token=$TOKEN&fresh=1"   # X-Render-Status: fresh
curl -i "${URL}image.png?token=wrong"                             # -> 401
```

Open `calendar.png` and check it. `status` lists `missing_params` and `errors` if something is not configured. Logs: CloudWatch -> Log groups -> `/aws/lambda/weekcalendar-render` (kept 14 days).

### 7. Point the frame at AWS

In the frame's `secrets.py`, set `CALENDAR_URL` to this (used both at wake-up and for the refresh button; the frame triggers the render itself):

```
https://<id>.lambda-url.eu-west-1.on.aws/image.png?token=<FRAME_TOKEN>&fresh=1
```

with an HTTP timeout of at least 60 s for the refresh request.

---

## Changing things

- **When it renders:** normally only when the frame requests `image.png?fresh=1`, so the frame decides the time. To also pre-render on a fixed schedule as a backup, set the template parameter `EnableSchedule` to `true` (time via `RenderHour` / `RenderMinute`, Europe/Oslo, summer time handled), e.g. `--parameter-overrides EnableSchedule=true RenderHour=3 RenderMinute=30` on `sam deploy` in the workflow.
- **Days shown:** parameter `RenderDays` (default 7).
- **Rotate the frame token:** update `/weekcalendar/FRAME_TOKEN`, then update the frame. The serve function picks up the new value within 5 minutes.
- **Local test without AWS:** `pip install -r infra/requirements-lambda.txt boto3 "moto[s3,ssm]" pytest && pytest tests/test_aws_handlers.py`.
- **Remove everything:** delete the CloudFormation stacks `weekcalendar` (and its `…-CompanionStack`), then empty and delete the S3 bucket (it is kept on stack deletion on purpose) and the `aws-sam-cli-managed-default` stack, then `weekcalendar-bootstrap`.

## Cost

eu-west-1 prices, about 1 render per day (frame wake-up) plus refresh-button presses. Most of this is inside the AWS free tier anyway.

| Service | Usage per month | Approx. cost |
|---|---|---|
| Lambda (render, 1 GB, ~15 s x 30) | ~450 GB-s | $0.01 (free tier: 400 000 GB-s) |
| Lambda (serve, 256 MB, ~100 requests) | negligible | $0.00 |
| Function URL | included in Lambda | $0.00 |
| ECR (render image, ~200–300 MB) | per stored image | ~$0.03 (the deploy sets a lifecycle rule that keeps the 5 newest images) |
| S3 (< 1 MB, a few hundred requests) | | < $0.01 |
| SSM Parameter Store (standard) + KMS `aws/ssm` key | | $0.00 |
| EventBridge Scheduler (only if `EnableSchedule=true`) | | $0.00 |
| CloudWatch Logs (14-day retention) | a few MB | $0.00 |
| Data transfer out (~15 KB x 100) | | $0.00 |
| **Total** | | **≈ $0.05 / month** |

## Security notes

- The bucket is private (public access blocked, TLS only). Only the two functions can touch it: the render function writes `latest/` and `cache/`, the serve function can only read `latest/`.
- Each function has its own minimal IAM role (render: S3 `latest/` + `cache/`, all `/weekcalendar/*` parameters; serve: read `latest/`, only the `FRAME_TOKEN` parameter, invoke the render function).
- The Function URL is public, but every route checks the token (constant-time compare). Treat the full image URL as a password: it contains the token.
- GitHub gets short-lived credentials through OIDC; no AWS keys are stored in GitHub. The deploy role can only be assumed from `iamjorgensen/weekcalendar` on `main` and only manages resources named `weekcalendar-*`. It can create IAM roles with that prefix (CloudFormation needs that for the function roles), so anyone who can push to `main` can effectively control those resources: keep branch protection on `main`.

---

## Admin page, school letters, feeds and Spond

These are built and described in the main [README](../README.md): the admin page (`/admin`), school letters from the phone (`/upload`, read by Claude in the ingest function), calendar feeds and Spond. They add three parameters here: `ADMIN_TOKEN`, `GOOGLE_SA_JSON` and `ANTHROPIC_API_KEY` (plus `SPOND_EMAIL` / `SPOND_PASSWORD` if you use Spond).
