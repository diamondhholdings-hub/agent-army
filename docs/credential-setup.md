# Production Credential Provisioning Guide

Complete step-by-step guide to provision all production credentials for the Sales Agent platform. Follow sections in order -- GCP setup first (longest propagation time), then external services, then GitHub secrets.

## Table of Contents

1. [Overview](#1-overview)
2. [GCP Project Setup](#2-gcp-project-setup)
3. [Service Account Creation](#3-service-account-creation)
4. [Domain-Wide Delegation](#4-domain-wide-delegation-google-workspace)
5. [Agent Email Account](#5-agent-email-account)
6. [Notion CRM Integration](#6-notion-crm-integration)
7. [Qdrant Cloud](#7-qdrant-cloud)
8. [Workload Identity Federation](#8-workload-identity-federation-gcp--github-actions)
9. [GitHub Actions Secrets](#9-github-actions-secrets)
10. [Vercel Webapp](#10-vercel-webapp)
11. [Post-Setup Verification Checklist](#11-post-setup-verification-checklist)

---

## 1. Overview

### Services to configure

| Service | What it provides | Estimated time |
|---------|-----------------|----------------|
| GCP (Google Cloud Platform) | Cloud Run hosting, service account, WIF | 15-20 min |
| Google Workspace Admin | Domain-wide delegation, agent email | 5-10 min + propagation |
| Notion | CRM integration (deals pipeline) | 5 min |
| Qdrant Cloud | Production vector database | 5 min |
| Vercel | Meeting bot webapp hosting | 5 min |
| GitHub | Repository secrets for CI/CD | 10 min |

**Total estimated time:** 30-45 minutes of active work, plus up to 24 hours for Google Domain-Wide Delegation propagation (usually 5-15 minutes).

### Order of operations

1. **GCP Project + Service Account + DWD** -- start first because DWD has the longest propagation delay
2. **Agent Email Account** -- create the Google Workspace user the agent will impersonate
3. **Notion Integration** -- create integration and share database
4. **Qdrant Cloud** -- provision free-tier cluster
5. **Workload Identity Federation** -- connect GCP to GitHub Actions
6. **Vercel Webapp** -- verify or connect project
7. **GitHub Actions Secrets** -- add all 25 secrets to the repository (do this last since it requires values from all previous steps)

### Prerequisites

- Google Workspace admin access for your domain (e.g., `skyvera.com`)
- GCP project owner or editor access
- GitHub repository admin access
- Notion workspace admin access

---

## 2. GCP Project Setup

### 2.1 Verify or create GCP project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. In the top navigation bar, click the project selector dropdown
3. If you already have a project for Sales Agent, select it. Otherwise:
   - Click **New Project**
   - Name: `sales-agent` (or your preferred name)
   - Organization: your organization
   - Click **Create**
4. Once selected, note these values from the **Dashboard** page:
   - **Project ID** (e.g., `sales-agent-123456`) -- this becomes `GCP_PROJECT_ID`
   - **Project number** (e.g., `123456789012`) -- this becomes `GCP_PROJECT_NUMBER`

> The Project ID and Project number are displayed on the Dashboard home page in the "Project info" card. The project number is numeric-only.

### 2.2 Enable required APIs

1. Go to **APIs & Services > Library** in the left sidebar
2. Search for and enable each of these APIs:
   - **Gmail API** -- click Enable
   - **Google Calendar API** -- click Enable
   - **Google Chat API** -- click Enable
   - **IAM Service Account Credentials API** -- click Enable (required for Workload Identity Federation)
   - **Cloud Run Admin API** -- click Enable (if not already enabled)
   - **Cloud Build API** -- click Enable (if not already enabled)

Alternatively, use gcloud CLI:

```bash
gcloud services enable \
  gmail.googleapis.com \
  calendar-json.googleapis.com \
  chat.googleapis.com \
  iamcredentials.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  --project=YOUR_PROJECT_ID
```

---

## 3. Service Account Creation

This service account is used by the Sales Agent backend to access Gmail and Calendar on behalf of the agent email.

### Step by step

1. In GCP Console, go to **IAM & Admin > Service Accounts**
2. Click **Create Service Account**
3. Fill in:
   - **Service account name:** `sales-agent-service`
   - **Service account ID:** `sales-agent-service` (auto-filled)
   - **Description:** `Service account for Sales Agent Gmail/Calendar access via domain-wide delegation`
4. Click **Create and Continue**
5. **Grant this service account access to the project:** Skip this step (no additional roles needed -- domain-wide delegation handles access)
6. Click **Continue**, then **Done**

### Generate JSON key

7. In the service accounts list, click on `sales-agent-service@YOUR_PROJECT_ID.iam.gserviceaccount.com`
8. Go to the **Keys** tab
9. Click **Add Key > Create new key**
10. Select **JSON** and click **Create**
11. The JSON key file will be downloaded to your computer. Keep it safe.

### Note the Client ID

12. Go back to the **Details** tab of the service account
13. Find the **Unique ID** (also called Client ID) -- this is a long numeric value (e.g., `112233445566778899`)
14. Copy this number -- you will need it for Domain-Wide Delegation in Section 4

### Base64-encode the JSON key

This is needed because Cloud Run environment variables cannot contain multi-line JSON.

**macOS:**
```bash
cat /path/to/service-account.json | base64
```

**Linux:**
```bash
cat /path/to/service-account.json | base64 -w 0
```

15. Copy the entire base64 output (one long line, no line breaks)
16. This becomes the value for `PROD_GOOGLE_SERVICE_ACCOUNT_JSON_B64`

> **Security:** Delete the original JSON key file after base64-encoding and storing the value in GitHub secrets. Never commit the JSON file to version control.

---

## 4. Domain-Wide Delegation (Google Workspace)

Domain-wide delegation allows the service account to impersonate the agent email and access Gmail/Calendar on its behalf without OAuth consent screens.

### Prerequisites

- You must be a **Google Workspace Super Admin** to configure domain-wide delegation
- You need the **numeric Client ID** from Section 3, step 13

### Step by step

1. Go to [admin.google.com](https://admin.google.com)
2. Navigate to: **Security > Access and data control > API controls**
3. Scroll down to **Domain-wide Delegation** and click **Manage Domain Wide Delegation**
4. Click **Add new**
5. Fill in:
   - **Client ID:** paste the numeric Client ID from Section 3, step 13
   - **OAuth Scopes:** paste the following (comma-separated, no spaces between scopes):

```
https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/calendar.events.readonly
```

6. Click **Authorize**

### Propagation time

- **Typical:** 5-15 minutes
- **Maximum:** Up to 24 hours (rare)
- You can proceed with the remaining setup steps while waiting for propagation

### What these scopes allow

| Scope | Permission |
|-------|-----------|
| `gmail.send` | Send emails on behalf of the agent |
| `gmail.readonly` | Read emails in the agent's inbox |
| `gmail.modify` | Modify email labels and mark as read |
| `calendar.readonly` | Read calendar events |
| `calendar.events.readonly` | Read detailed event information |

---

## 5. Agent Email Account

The Sales Agent needs a dedicated Google Workspace email account to send/receive emails and monitor calendar events.

### Step by step

1. Go to [admin.google.com](https://admin.google.com)
2. Navigate to: **Directory > Users**
3. Click **Add new user**
4. Fill in:
   - **First name:** Sales
   - **Last name:** Agent
   - **Primary email:** `agent@skyvera.com` (or your chosen agent email)
5. Set a temporary password (you may not need to log in as this user)
6. Click **Add New User**
7. Ensure the user has a Google Workspace license that includes Gmail and Calendar

This email address becomes the value for `PROD_GOOGLE_DELEGATED_USER_EMAIL`.

> **Note:** The service account from Section 3 will impersonate this email address via domain-wide delegation. The agent user does not need to log in directly.

---

## 6. Notion CRM Integration

The Sales Agent syncs deal data with a Notion database that serves as the CRM pipeline.

### 6.1 Create the integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **New integration**
3. Fill in:
   - **Name:** `Sales Agent Production`
   - **Associated workspace:** select your production Notion workspace
   - **Type:** Internal integration
4. Under **Capabilities**, ensure these are enabled:
   - Read content
   - Update content
   - Insert content
5. Click **Save changes**
6. Click **Show** next to **Internal Integration Secret** and copy the token
   - This becomes the value for `PROD_NOTION_TOKEN`
   - The token starts with `ntn_`

### 6.2 Share database with integration

7. Open your deals pipeline database in Notion
8. Click the **...** menu (top right of the database page)
9. Click **Add connections**
10. Search for and select **Sales Agent Production**
11. Click **Confirm**

### 6.3 Get database ID

12. Open the deals pipeline database in Notion in your browser
13. Look at the URL: `https://www.notion.so/WORKSPACE_NAME/DATABASE_ID?v=VIEW_ID`
14. Copy the `DATABASE_ID` portion (the UUID before `?v=`)
   - Example: `https://www.notion.so/skyvera/a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4?v=...`
   - Database ID: `a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4`
15. This becomes the value for `PROD_NOTION_DATABASE_ID`

### 6.4 Verify database properties

The deals database must have these properties (columns). Create any that are missing:

| Property Name | Type | Required |
|--------------|------|----------|
| Deal Name | Title | Yes |
| Stage | Select | Yes |
| Value | Number | Yes |
| Close Date | Date | Yes |
| Product | Select | Yes |
| Probability | Number | Yes |
| Source | Select | Yes |
| Contact | Rich text | Yes |
| Email | Email | Yes |

**Stage select options** should include at minimum: `Discovery`, `Qualification`, `Proposal`, `Negotiation`, `Closed Won`, `Closed Lost`

---

## 7. Qdrant Cloud

Qdrant Cloud provides the production vector database for the Sales Agent's knowledge base. The free tier (1 GB) is sufficient for initial production use.

### Step by step

1. Go to [cloud.qdrant.io](https://cloud.qdrant.io) and create an account (or log in)
2. Click **Create Cluster**
3. Select:
   - **Plan:** Free tier
   - **Cloud provider:** any (AWS or GCP)
   - **Region:** choose closest to your Cloud Run region (e.g., `us-central` if Cloud Run is in `us-central1`)
4. Click **Create**
5. Wait for cluster to be provisioned (usually 1-2 minutes)
6. Once ready, copy the **Cluster URL** (e.g., `https://abc123-xyz.us-east4-0.gcp.cloud.qdrant.io:6333`)
   - This becomes `PROD_QDRANT_URL`
7. Click **API Keys** and generate a new API key
   - This becomes `PROD_QDRANT_API_KEY`

> **Note:** The application auto-creates required collections on first use. No manual collection setup is needed.

---

## 8. Workload Identity Federation (GCP -> GitHub Actions)

Workload Identity Federation (WIF) allows GitHub Actions to authenticate to GCP without storing service account keys. The `deploy.yml` workflow references a WIF pool named `github` with provider `github`.

### Check if WIF already exists

```bash
gcloud iam workload-identity-pools describe github \
  --project=YOUR_PROJECT_ID \
  --location=global 2>/dev/null && echo "WIF pool exists" || echo "WIF pool not found"
```

If the pool already exists, skip to **Step 5** (verify the provider and service account).

### Step 1: Enable required API

```bash
gcloud services enable iamcredentials.googleapis.com \
  --project=YOUR_PROJECT_ID
```

### Step 2: Create workload identity pool

```bash
gcloud iam workload-identity-pools create github \
  --project=YOUR_PROJECT_ID \
  --location=global \
  --display-name="GitHub Actions"
```

### Step 3: Create OIDC provider

```bash
gcloud iam workload-identity-pools providers create-oidc github \
  --workload-identity-pool=github \
  --project=YOUR_PROJECT_ID \
  --location=global \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository"
```

### Step 4: Create CI/CD service account

```bash
# Create the service account
gcloud iam service-accounts create github-actions \
  --project=YOUR_PROJECT_ID \
  --display-name="GitHub Actions CI/CD"

# Grant required roles
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:github-actions@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:github-actions@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/cloudbuild.builds.editor"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:github-actions@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:github-actions@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.admin"
```

### Step 5: Grant WIF access to the service account

Replace `YOUR_GITHUB_ORG/YOUR_REPO` with your actual GitHub repository path (e.g., `skyvera/sales-army`):

```bash
# Get the workload identity pool ID
WIF_POOL_ID=$(gcloud iam workload-identity-pools describe github \
  --project=YOUR_PROJECT_ID \
  --location=global \
  --format="value(name)")

# Grant the WIF pool permission to impersonate the service account
gcloud iam service-accounts add-iam-policy-binding \
  github-actions@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --project=YOUR_PROJECT_ID \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${WIF_POOL_ID}/attribute.repository/YOUR_GITHUB_ORG/YOUR_REPO"
```

### Values needed for GitHub secrets

After completing WIF setup, you need:

- **GCP_PROJECT_ID** -- your project ID (e.g., `sales-agent-123456`)
- **GCP_PROJECT_NUMBER** -- your project number (e.g., `123456789012`)
- **GCP_SERVICE_ACCOUNT** -- `github-actions@YOUR_PROJECT_ID.iam.gserviceaccount.com`
- **GCP_WORKLOAD_IDENTITY_PROVIDER** -- `projects/YOUR_PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github`

> **Note:** The deploy.yml constructs the WIF provider path from `GCP_PROJECT_NUMBER`, so you only need to set the project number as a secret.

---

## 9. GitHub Actions Secrets

All 25 secrets must be configured before the first production deployment. Go to your GitHub repository:

**Settings > Secrets and variables > Actions > New repository secret**

### Complete secrets table

| # | Secret Name | Description | Source | Format Example |
|---|------------|-------------|--------|----------------|
| 1 | `GCP_PROJECT_ID` | GCP project identifier | GCP Console > Dashboard > Project info | `sales-agent-123456` |
| 2 | `GCP_PROJECT_NUMBER` | GCP project number (numeric) | GCP Console > Dashboard > Project info | `123456789012` |
| 3 | `GCP_REGION` | Cloud Run deployment region | Developer choice | `us-central1` |
| 4 | `PROD_DATABASE_URL` | PostgreSQL connection string | Managed DB provider (Supabase, Neon, Cloud SQL, Railway) | `postgresql+asyncpg://user:pass@host:5432/dbname` |
| 5 | `PROD_REDIS_URL` | Redis connection string | Managed Redis provider (Upstash, Railway, Memorystore) | `redis://default:pass@host:6379` |
| 6 | `PROD_JWT_SECRET_KEY` | JWT signing secret for production | Generate locally | See below |
| 7 | `PROD_ANTHROPIC_API_KEY` | Anthropic Claude API key | [console.anthropic.com](https://console.anthropic.com) > API Keys | `sk-ant-api03-...` |
| 8 | `PROD_OPENAI_API_KEY` | OpenAI API key (GPT + embeddings) | [platform.openai.com](https://platform.openai.com) > API Keys | `sk-proj-...` |
| 9 | `PROD_GOOGLE_SERVICE_ACCOUNT_JSON_B64` | Base64-encoded GCP service account JSON | Section 3 (base64-encode the downloaded JSON) | Long base64 string |
| 10 | `PROD_GOOGLE_DELEGATED_USER_EMAIL` | Agent email for Gmail/Calendar | Section 5 | `agent@skyvera.com` |
| 11 | `PROD_NOTION_TOKEN` | Notion internal integration token | Section 6 | `ntn_...` |
| 12 | `PROD_NOTION_DATABASE_ID` | Notion deals database UUID | Section 6 | `a1b2c3d4-e5f6-...` |
| 13 | `PROD_QDRANT_URL` | Qdrant Cloud cluster URL | Section 7 | `https://abc123.us-east4-0.gcp.cloud.qdrant.io:6333` |
| 14 | `PROD_QDRANT_API_KEY` | Qdrant Cloud API key | Section 7 | `qdr_...` |
| 15 | `PROD_RECALL_AI_API_KEY` | Recall.ai bot management API key | [recall.ai](https://recall.ai) dashboard | API key string |
| 16 | `PROD_DEEPGRAM_API_KEY` | Deepgram speech-to-text API key | [console.deepgram.com](https://console.deepgram.com) | API key string |
| 17 | `PROD_ELEVENLABS_API_KEY` | ElevenLabs text-to-speech API key | [elevenlabs.io](https://elevenlabs.io) > Profile + API Key | `xi_...` |
| 18 | `PROD_ELEVENLABS_VOICE_ID` | ElevenLabs voice ID for agent | [elevenlabs.io](https://elevenlabs.io) > Voices > Select voice > Voice ID | UUID string |
| 19 | `PROD_HEYGEN_API_KEY` | HeyGen avatar rendering API key | [heygen.com](https://heygen.com) > Settings > API | API key string |
| 20 | `PROD_HEYGEN_AVATAR_ID` | HeyGen avatar ID | [heygen.com](https://heygen.com) > Avatars > Select avatar | Avatar ID string |
| 21 | `PROD_MEETING_BOT_WEBAPP_URL` | Vercel webapp production URL | Section 10 (Vercel dashboard) | `https://your-app.vercel.app` |
| 22 | `PROD_LANGFUSE_PUBLIC_KEY` | Langfuse observability public key | [cloud.langfuse.com](https://cloud.langfuse.com) > Settings > API Keys | `pk-lf-...` |
| 23 | `PROD_LANGFUSE_SECRET_KEY` | Langfuse observability secret key | [cloud.langfuse.com](https://cloud.langfuse.com) > Settings > API Keys | `sk-lf-...` |
| 24 | `PROD_SENTRY_DSN` | Sentry error monitoring DSN | [sentry.io](https://sentry.io) > Project > Settings > Client Keys | `https://...@sentry.io/...` |
| 25 | `PROD_CORS_ALLOWED_ORIGINS` | Comma-separated allowed CORS origins | Developer choice | `https://your-app.vercel.app,https://yourdomain.com` |

### Generate JWT secret

Run this command locally to generate a secure JWT signing key:

```bash
openssl rand -hex 32
```

Copy the output as the value for `PROD_JWT_SECRET_KEY`.

### How deploy.yml uses these secrets

The `deploy.yml` workflow:
1. Uses `GCP_PROJECT_NUMBER` + `GCP_PROJECT_ID` to authenticate via Workload Identity Federation
2. Uses `GCP_REGION` and `GCP_PROJECT_ID` for Cloud Run deployment
3. Passes all `PROD_*` secrets as environment variables to Cloud Run via `env_vars`
4. `PROD_OPENAI_API_KEY` is used for both `OPENAI_API_KEY` and `KNOWLEDGE_OPENAI_API_KEY` (same key, two env vars)

---

## 10. Vercel Webapp

The meeting-bot-webapp (avatar frontend) is deployed to Vercel and auto-deploys on push to `main`.

### 10.1 Verify Vercel project connection

1. Go to [vercel.com](https://vercel.com) and log in
2. Check if the project already exists:
   - Look for a project linked to the `meeting-bot-webapp/` directory of this repository
   - If it exists and is connected to GitHub, you are done -- proceed to step 3

### 10.2 Connect project (if not already connected)

1. Click **Add New Project**
2. Click **Import Git Repository**
3. Select this GitHub repository
4. Configure:
   - **Framework Preset:** Next.js (auto-detected)
   - **Root Directory:** `meeting-bot-webapp`
   - **Build Command:** `npm run build` (default)
   - **Output Directory:** `.next` (default)
5. Click **Deploy**

### 10.3 Note the production URL

1. After deployment, go to the project's **Settings > Domains**
2. Copy the production domain URL (e.g., `https://your-meeting-bot.vercel.app`)
3. This becomes the value for `PROD_MEETING_BOT_WEBAPP_URL`

### 10.4 Set production branch

1. Go to project **Settings > Git**
2. Ensure **Production Branch** is set to `main`

---

## 11. Post-Setup Verification Checklist

Run through this checklist to confirm everything is properly configured before the first production deployment.

### GitHub Actions Secrets

- [ ] All 25 secrets are configured in **Settings > Secrets and variables > Actions**
- [ ] `GCP_PROJECT_ID` and `GCP_PROJECT_NUMBER` match your GCP project
- [ ] `GCP_REGION` is set (e.g., `us-central1`)
- [ ] `PROD_JWT_SECRET_KEY` was generated with `openssl rand -hex 32`
- [ ] `PROD_GOOGLE_SERVICE_ACCOUNT_JSON_B64` is base64-encoded (not raw JSON)
- [ ] `PROD_MEETING_BOT_WEBAPP_URL` points to the Vercel production domain

### Google Workspace

- [ ] Service account `sales-agent-service` exists in GCP IAM
- [ ] Domain-wide delegation is authorized in Google Admin Console (Security > API controls)
- [ ] OAuth scopes include: `gmail.send`, `gmail.readonly`, `gmail.modify`, `calendar.readonly`, `calendar.events.readonly`
- [ ] Agent email account `agent@skyvera.com` is created and has a Google Workspace license
- [ ] Client ID in DWD matches the service account's numeric Unique ID

### Notion CRM

- [ ] Integration "Sales Agent Production" is created at [notion.so/my-integrations](https://www.notion.so/my-integrations)
- [ ] Integration is connected to the deals pipeline database
- [ ] Database properties match expected schema (Deal Name, Stage, Value, Close Date, Product, Probability, Source, Contact, Email)
- [ ] Integration token stored as `PROD_NOTION_TOKEN`
- [ ] Database ID stored as `PROD_NOTION_DATABASE_ID`

### Qdrant Cloud

- [ ] Cluster is created and running on [cloud.qdrant.io](https://cloud.qdrant.io)
- [ ] Cluster URL stored as `PROD_QDRANT_URL`
- [ ] API key stored as `PROD_QDRANT_API_KEY`

### Workload Identity Federation

- [ ] WIF pool `github` exists in GCP
- [ ] OIDC provider `github` is configured with issuer `https://token.actions.githubusercontent.com`
- [ ] Service account `github-actions@PROJECT_ID.iam.gserviceaccount.com` has roles: Cloud Run Admin, Cloud Build Editor, Service Account User, Storage Admin
- [ ] WIF pool is bound to the correct GitHub repository

### Vercel

- [ ] Vercel project is connected to the GitHub repository
- [ ] Root directory is set to `meeting-bot-webapp`
- [ ] Production branch is `main`
- [ ] Production URL is noted and stored as `PROD_MEETING_BOT_WEBAPP_URL`

### External API Keys

- [ ] Anthropic API key is active (`PROD_ANTHROPIC_API_KEY`)
- [ ] OpenAI API key is active (`PROD_OPENAI_API_KEY`)
- [ ] Recall.ai API key is active (`PROD_RECALL_AI_API_KEY`)
- [ ] Deepgram API key is active (`PROD_DEEPGRAM_API_KEY`)
- [ ] ElevenLabs API key and voice ID are set (`PROD_ELEVENLABS_API_KEY`, `PROD_ELEVENLABS_VOICE_ID`)
- [ ] HeyGen API key and avatar ID are set (`PROD_HEYGEN_API_KEY`, `PROD_HEYGEN_AVATAR_ID`)
- [ ] Langfuse public and secret keys are set (`PROD_LANGFUSE_PUBLIC_KEY`, `PROD_LANGFUSE_SECRET_KEY`)
- [ ] Sentry DSN is set (`PROD_SENTRY_DSN`)

### Production Database and Redis

- [ ] PostgreSQL database is provisioned and connection string is in `PROD_DATABASE_URL`
- [ ] Redis instance is provisioned and connection string is in `PROD_REDIS_URL`
- [ ] Database migrations are ready to run (Alembic `upgrade head` should be run as part of first deployment)

---

## Troubleshooting

### Domain-Wide Delegation not working

- **Symptom:** API calls return `403 Forbidden` or `401 Unauthorized` when trying to access Gmail/Calendar
- **Fix:** Verify the Client ID in DWD matches the service account's numeric Unique ID (not the email). Wait up to 24 hours for propagation. Double-check scopes are comma-separated with no spaces.

### WIF authentication fails in GitHub Actions

- **Symptom:** Auth step fails with "unable to generate access token" or "workload identity pool not found"
- **Fix:** Verify `GCP_PROJECT_NUMBER` (not ID) is correct. Verify the WIF pool and provider names are both `github`. Verify the service account IAM binding includes the correct repository path.

### Cloud Run deployment returns 403

- **Symptom:** All HTTP requests to Cloud Run URL return 403 Forbidden
- **Fix:** Ensure `--allow-unauthenticated` flag is included in the deploy configuration. The `deploy.yml` already includes this flag.

### Notion API returns 404

- **Symptom:** Notion API calls fail with "Object not found"
- **Fix:** Ensure the integration is connected to the database (not just created). Open the database page, click "...", and verify the integration appears under "Connections".

### Base64 encoding issues

- **Symptom:** App starts but Google services fail to initialize
- **Fix:** Verify the base64 string has no line breaks. On Linux, use `base64 -w 0` to produce a single-line output. On macOS, `base64` produces single-line by default.

---

*Last updated: 2026-02-22*
*Covers: deploy.yml secrets, Google Workspace DWD, Notion CRM, Qdrant Cloud, WIF, Vercel*
