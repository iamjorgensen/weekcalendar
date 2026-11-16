#!/usr/bin/env bash
# One-time AWS setup for weekcalendar. Run in AWS CloudShell (region eu-west-1):
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/iamjorgensen/weekcalendar/feat/aws-lambda/infra/setup.sh)
#
# It:
#   1. creates the GitHub deploy role (stack "weekcalendar-bootstrap"),
#   2. stores your settings/keys in SSM Parameter Store (/weekcalendar/*),
#      read from your Pi's .env that you paste in - nothing leaves your AWS account,
#   3. creates a random FRAME_TOKEN for the frame (kept if one already exists).
# Safe to run again.
set -euo pipefail

REGION="${REGION:-eu-west-1}"
PREFIX="/weekcalendar"
BRANCH="${BRANCH:-feat/aws-lambda}"
RAW="https://raw.githubusercontent.com/iamjorgensen/weekcalendar/${BRANCH}/infra"
export AWS_DEFAULT_REGION="$REGION"

echo "== weekcalendar setup in $REGION =="
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "AWS account: $ACCOUNT"

# --- 1. GitHub deploy role -------------------------------------------------
if aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text \
     | grep -q 'token.actions.githubusercontent.com'; then
  CREATE_OIDC=false
  echo "GitHub OIDC provider already exists in this account - reusing it."
else
  CREATE_OIDC=true
fi

TMP=$(mktemp -d)
curl -fsSL "$RAW/bootstrap.yaml" -o "$TMP/bootstrap.yaml"
echo "Creating/updating stack weekcalendar-bootstrap (about 1 minute)..."
aws cloudformation deploy \
  --stack-name weekcalendar-bootstrap \
  --template-file "$TMP/bootstrap.yaml" \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameter-overrides CreateOidcProvider=$CREATE_OIDC \
  --no-fail-on-empty-changeset
ROLE_ARN=$(aws cloudformation describe-stacks --stack-name weekcalendar-bootstrap \
  --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" --output text)

# --- 2. Settings from the Pi's .env -----------------------------------------
SECRET_KEYS=" API_KEY_GOOGLE CALENDAR_ID MOVAR_API_TOKEN MOVAR_GATENAVN MOVAR_HUSNR OPENAI_API_KEY "
PLAIN_KEYS=" HOLIDAYS_CALENDAR_ID MOVAR_BASE KOMMUNENR LAT LON OPENAI_MODEL "

echo
echo "Paste the contents of your Pi's .env file (~/weekcalendar/.env)."
echo "When done, press Enter and then Ctrl-D. (Input is not shown on screen.)"
stty -echo 2>/dev/null || true
ENV_TEXT=$(cat)
stty echo 2>/dev/null || true
echo

stored=()
while IFS= read -r line; do
  line="${line%$'\r'}"
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  line="${line#export }"
  key="${line%%=*}"; val="${line#*=}"
  key="$(echo "$key" | tr -d '[:space:]')"
  val="${val#"${val%%[![:space:]]*}"}"; val="${val%"${val##*[![:space:]]}"}"
  val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
  [[ -z "$val" ]] && continue
  if [[ "$SECRET_KEYS" == *" $key "* ]]; then type=SecureString
  elif [[ "$PLAIN_KEYS" == *" $key "* ]]; then type=String
  else continue; fi
  aws ssm put-parameter --overwrite --type "$type" --name "$PREFIX/$key" --value "$val" >/dev/null
  stored+=("$key")
done <<< "$ENV_TEXT"
unset ENV_TEXT
echo "Stored ${#stored[@]} settings: ${stored[*]:-none}"

# --- 3. Frame token -----------------------------------------------------------
if TOKEN=$(aws ssm get-parameter --with-decryption --name "$PREFIX/FRAME_TOKEN" \
             --query Parameter.Value --output text 2>/dev/null); then
  echo "Keeping existing FRAME_TOKEN."
else
  TOKEN=$(openssl rand -hex 24)
  aws ssm put-parameter --type SecureString --name "$PREFIX/FRAME_TOKEN" --value "$TOKEN" >/dev/null
  echo "Created FRAME_TOKEN."
fi

missing=()
for k in API_KEY_GOOGLE CALENDAR_ID LAT LON; do
  aws ssm get-parameter --name "$PREFIX/$k" >/dev/null 2>&1 || missing+=("$k")
done

echo
echo "================================================================"
echo " Done."
echo
echo " 1) Send this to Claude (it is not a secret):"
echo "      $ROLE_ARN"
echo
echo " 2) Keep this frame token private (you'll put it in the frame/URL):"
echo "      $TOKEN"
[[ ${#missing[@]} -gt 0 ]] && echo && echo " Note: not set yet: ${missing[*]}"
echo "================================================================"
