# MediMate AI — Personal Medication Companion

MediMate AI is a hackathon prototype intended to help people follow an existing prescribed medication schedule. It is not a medical device and does not provide medical advice.

## Project structure

- `frontend/` — React, Vite, and React Router web client.
- `backend/` — FastAPI service, SQLAlchemy database foundation, and tests.
- `.env.example` — names of environment variables used by the project. Copy it to `.env` for local configuration; never commit real credentials.

## Requirements

- Python 3.11 or newer (the backend dependencies have been installed with Python 3.14.7).
- Node.js LTS and npm.
- PowerShell.

## Start the backend

From the project root, activate the existing virtual environment and run the API:

```powershell
.\.venv\Scripts\Activate.ps1
cd backend
python -m uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000`. Interactive API documentation is at `http://localhost:8000/docs`, and the health check is `http://localhost:8000/api/health`.

For stable local sign-in sessions, make a private `.env` file and set a secret key. From the project root:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value after `SECRET_KEY=` in `.env` using a local editor. Never share or commit that value. If it is omitted, the backend creates a temporary key on each start and existing sign-in tokens will expire when the server restarts.

## Start the frontend

Open a second PowerShell terminal at the project root. If `node` and `npm` are not on PATH in that terminal yet, add the standard Node.js install directory for this terminal session:

```powershell
$env:Path += ";C:\Program Files\nodejs"
cd frontend
npm.cmd install
npm.cmd run dev
```

Open the URL printed by Vite (normally `http://localhost:5173`). The home page includes a button to check the backend connection.

## Tests

With the virtual environment activated, from the project root run:

```powershell
python -m pytest backend\tests
```

## Phase 2 core workflows

- Create patient or caregiver accounts from the Sign in page. Passwords are stored as Argon2 hashes and API access uses short-lived signed bearer tokens.
- A patient can create schedules and share the invitation code from their dashboard. A caregiver must provide the patient's email and code to link; the code rotates after successful use. Unlinked caregivers cannot read or manage the patient's data.
- A patient explicitly confirms a dose. Dashboard visits and caregiver actions never confirm a dose.
- The backend creates unique dose occurrences, backfills up to 30 days of schedule events on restart, records repeated reminders, and records a simulated caregiver escalation after the configured delay.
- The API uses per-process in-memory login and registration rate limits. The APScheduler process must remain running; this local setup does not guarantee alerts when a browser is closed or a device is offline.
- Run one backend scheduler process for this prototype. Multiple backend workers/instances need a shared scheduler or distributed job lock to prevent duplicate reminders.

## Twilio reminder calls

The backend loads the root .env file. It accepts TWILIO_FROM_NUMBER or
TWILIO_PHONE_NUMBER for the Twilio-authorized caller ID. Keep the account SID,
auth token, and caller ID in that backend file only. ENABLE_VOICE_CALLS can be
set to false to disable live calls. A patient's explicit consent and an E.164
destination number are also required.

For a Twilio trial account, keep the approved template URL in the root `.env`
and set `TWILIO_TRIAL_CUSTOM_TWIML=true`. MediMate first attempts to speak a
message that includes the medication name and asks the patient to visit the
MediMate webpage and click its confirmation button after taking the dose. If
Twilio rejects custom TwiML, MediMate falls back to the approved template so
the trial account can still place a call; that fallback may not include the
medication name or confirmation instructions. Twilio documents restricted
custom TwiML and supports `<Say>` for text-to-speech, but its trial Calls API
limits outbound instructions to approved template URLs. For guaranteed
personalized speech, upgrade the account or configure a compatible
Twilio-hosted custom flow. After upgrading, clear `TWILIO_TRIAL_CUSTOM_TWIML`
and the trial template URL to use
the configured caller ID with MediMate's normal inline TwiML.

You can run this trial flow locally: the backend sends an outbound request to
Twilio. The backend must stay running at the scheduled time. A public HTTPS
backend is needed for status callbacks and for calls using your own TwiML URL;
it is not needed for direct TwiML call requests or Twilio-hosted trial templates.
`TWILIO_STATUS_CALLBACK_URL` is optional for call creation, but set it to
https://<public-host>/api/calls/webhook/status to receive signed outcome
updates. Those updates are needed to distinguish completed, busy, no-answer,
and failed, and to make the one retry after five minutes. Without a callback,
the call request can still be created, but the call log cannot learn its final
outcome and will not retry a call left queued.

For local status tracking, expose the backend through an HTTPS tunnel (for
example, run ngrok http 8000 and use its HTTPS forwarding address for
TWILIO_STATUS_CALLBACK_URL), restart the backend, and confirm the callback
route is reachable from the public internet. Twilio must be able to reach the
callback; localhost is not reachable from Twilio. The scheduler only places
the first call within two minutes of the scheduled time after a restart, so it
does not call for a backlog of old doses. A failed, busy, or unanswered call
can be retried once after five minutes, and no call response confirms a dose.

### Manual test for one real call

1. Confirm the account SID/auth token and `ENABLE_VOICE_CALLS=true`. On a trial
   account, set `TWILIO_VOICE_TEMPLATE_URL` to the approved template and
   `TWILIO_TRIAL_CUSTOM_TWIML=true`; a caller ID is not needed in this mode. A public HTTPS callback ending in
   /api/calls/webhook/status is optional. Keep secrets out of chat.
2. Start one backend scheduler and the frontend. Sign in as the patient,
   enter an authorized phone number in international E.164 format, and
   explicitly consent to calls.
3. Create a test schedule for a time about one minute ahead. Keep the backend
   running and inspect the voice reminder history after the scheduled time.
   queued means Twilio accepted the request; it does not mean the patient
   answered. The callback should later update the status. Confirm the dose
   separately with the dashboard button.
4. If the call does not appear, inspect the backend log for the scheduler or
   Twilio error and provide only sanitized lines (remove phone numbers,
   account identifiers, and credentials).

## Phase 3 AI and voice

- An authenticated **AI assistant** page and patient dashboard chat use `backend/app/services/ai_service.py`. When `NEBIUS_API_KEY` is empty, chat and the AI test button use local mock mode; no network request to Nebius is made.
- To enable hosted inference, set `NEBIUS_API_KEY` privately in root `.env`. `NEBIUS_MODEL` defaults to `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, which is listed in the [live Nebius Token Factory model catalog](https://tokenfactory.nebius.com/endpoints?modality=chat). The [Nebius quickstart](https://docs.tokenfactory.nebius.com/quickstart) documents the OpenAI-compatible `https://api.tokenfactory.nebius.com/v1/` endpoint. The key stays on the backend. The UI identifies live mode and warns that chat text is sent to Nebius; the app does not attach medication schedules to those requests.
- The assistant is limited to app navigation and general, non-diagnostic help. It cannot confirm doses or modify schedules. Backend safety rules short-circuit emergency and dose-change requests with a safe response; this is not a substitute for clinician guidance.
- Browser speech recognition is started only when the user presses **Start microphone**. The recognized words are placed in the chat box for review and are not sent until the user presses **Send**. Speech recognition and spoken playback vary by browser and may use browser/provider services; this app does not record or store audio.
- **Run demo call test** never places a call. Scheduled reminders require the patient's explicit opt-in, a valid E.164 phone number, and Twilio credentials. When `TWILIO_TRIAL_CUSTOM_TWIML=true`, reminders attempt to speak the medication name and confirmation instructions, then fall back to the approved template if Twilio rejects custom TwiML. The fallback places a call but may not include personalized speech. With the setting off, calls use the selected Twilio-hosted template; on a paid account, clear the trial template setting to use inline TwiML and the configured caller ID. A public HTTPS status callback is optional for call creation but required to track final call outcomes and trigger a bounded retry. Calls are attempted close to scheduled time, skipped when more than two minutes late after downtime, and retried at most once after five minutes when Twilio reports a failure, busy, or no-answer status. Answering never confirms a dose. Callback signatures are verified.

### AI and voice test

1. Sign in and open **AI assistant**.
2. Check the integration status and model ID. Without `NEBIUS_API_KEY`, the expected status is **AI mock mode**.
3. Choose **Test Nebius AI**. Mock mode should report that the local assistant is ready.
4. Ask “What does due mean?” in typed chat. Try **Start microphone** only if supported; inspect the recognized words before pressing **Send**.
5. Choose **Run demo call test**. The result must state that no phone was called.
6. To test a real Nebius request, enter the key locally in `.env`, restart the backend, and choose **Test Nebius AI**. Do not paste the key into chat or frontend configuration.
7. In a patient account, automated call consent is off by default. The patient can add a number and explicitly opt in; withdrawing consent removes the stored number. With credentials missing, no real call is made.

### Manual smoke test

1. Start the backend and frontend in separate terminals using the commands above.
2. Open `http://localhost:5173`, choose **Sign in or create an account**, and create a patient account.
3. On the patient dashboard, create a schedule using a fictional medication name and an existing prescribed time. Confirm that it appears under schedules and today's events.
4. Use **I have taken it** only after the fictional dose is due; check that it disappears from today's active list and the next scheduled occurrence is shown. Confirmed records remain available through the history API; repeating schedules create the next day's occurrence at the configured local time.
5. Create a separate caregiver account. Share the patient's invitation code locally, then link the patient from the caregiver dashboard. Verify the caregiver can see that patient's schedule only after linking.
6. Open `http://localhost:8000/docs` to try the protected API after registering.

### Prototype security limitations

This is not suitable for real patient data or production deployment. It has no account recovery, email verification, MFA, refresh-token rotation, administrative audit workflow, or distributed rate-limit store. Signed access credentials are held in browser session storage, so an XSS flaw could expose them. The local SQLite database is not encrypted, and table creation is not a production migration system. Production requires security review, HTTPS, secure managed secrets and key rotation, a persistent protected database with migrations/backups, robust consent/revocation and audit controls, and clinical/privacy/legal review. Do not enter real patient details.

## Configuration and safety

The backend reads environment variables from the process environment and from a root `.env` file. `.env.example` documents blank placeholders; the scheduler checks every ten seconds by default (`SCHEDULER_INTERVAL_SECONDS`). On a deployed backend, configure secrets in the host's secret environment or the private root `.env` actually read by the service, never in `.env.example` or frontend variables. Scheduler recovery materializes recent dose events, but a call is made only within the two-minute catch-up window. Older missed doses are not called in a burst after restart.

Medication reminders must follow a clinician-prescribed plan. This prototype is not a substitute for professional medical care. In an emergency, contact local emergency services.

## Install the phone app

The React app is installable as a PWA from the production HTTPS site. On Android,
use the browser's **Install app** prompt or menu item. On iPhone, open the site in
Safari, tap **Share**, then **Add to Home Screen**. The service worker does not
cache API responses, tokens, schedules, or patient history. The app needs a
network connection to load medication status and submit confirmations; a PWA
does not provide reliable offline or suspended-phone alarms.

After sign-in, **Keep me signed in on this device** stores a revocable, signed
session in an HttpOnly cookie for the configured period (30 days by default).
The password is never stored by the frontend. Keep this option off on a shared
device and use **Sign out** when finished. Production must set
`SESSION_COOKIE_SECURE=true`; the browser sends the cookie only over HTTPS.

## Production deployment (manual account setup required)

The repository now includes a Dockerfile that builds the existing Vite frontend
and serves it from the FastAPI app at the same origin. This keeps the browser
session first-party and makes React routes work when refreshed. A simple hosted
prototype path is one Render Docker web service plus Render Postgres, with the
service kept at exactly one instance so the in-process APScheduler is not run
twice. Render provides a public `onrender.com` URL and managed HTTPS; a custom
domain is optional. Do not use the free web service for scheduled calls: it can
spin down, and the free Postgres database expires after 30 days. The API needs a
continuously running paid web instance and a persistent paid database for
reminders and patient records. Check the provider's current price before
creating paid resources. See Render's [web service deployment guide](https://render.com/docs/web-services),
[Postgres guide](https://render.com/docs/postgresql), and
[free tier limits](https://render.com/docs/free).

### Prepare the existing data

If you need to move existing patient records, first create the Render Blueprint
below so Render provisions Postgres. Before using the deployed service with real
patients, back up `backend/medimate.db` while the local backend is stopped. Keep
the backup private; it may contain patient records. The database file and
backups are ignored by Git and must never be uploaded to a public repository.

Use the Postgres **external** connection URL temporarily from your trusted
migration machine; the app receives the internal connection URL from the
Blueprint. The app accepts `postgres://`, `postgresql://`, or
`postgresql+psycopg://` URLs. Set `DATABASE_URL` in the trusted terminal to the
external destination URL, then run from the project root:

```powershell
$env:APP_ENV = "development"
$env:DATABASE_URL = "<private PostgreSQL destination URL>"
Set-Location backend
..\.venv\Scripts\python.exe -m scripts.migrate_sqlite_to_postgres .\medimate.db
```

The script refuses a non-empty destination and prints table row counts, not
patient data. Keep the SQLite backup until you have verified the copied counts
and application records. This is a one-time data copy; back up the PostgreSQL
database before each future schema change. The project does not yet include a
versioned migration framework for later schema evolution.

### Create the public service

The root `render.yaml` is a Render Blueprint for this full-stack deployment.
The Docker image builds the frontend and serves it from FastAPI, so the browser
uses one public URL for both the website and `/api` endpoints.

1. In the Render dashboard, choose **New > Blueprint**, connect the GitHub
   repository containing this project, and select the branch with `render.yaml`.
   Render will show the services and current charges before creating them. The
   Blueprint defines one always-on web instance and one persistent Postgres
   database in Singapore. Review the current plan prices before accepting.
2. When prompted, enter the Twilio Account SID, Auth Token, and authorized
   Twilio phone number in Render's private environment-variable form. Do not
   put these values in GitHub or paste them into chat. The Blueprint leaves
   `ENABLE_VOICE_CALLS=true`; calls work after valid Twilio credentials and an
   eligible, opted-in recipient are configured. The status callback URL is
   derived from Render's HTTPS service URL automatically. For a custom domain,
   set `TWILIO_STATUS_CALLBACK_URL` to
   `https://<your-domain>/api/calls/webhook/status`.
3. Click **Apply** to create the services and wait for the first deployment.
   Render assigns the service a public `https://<service>.onrender.com` URL.
   Open that URL in a browser and check that `<service-url>/api/health` reports
   `ok`. The same URL serves the frontend and backend.
4. If you have existing local patient records, follow [Prepare the existing
   data](#prepare-the-existing-data) to copy them into Postgres before using the
   deployed service. Keep local database backups private.
5. Register accounts and verify the app using synthetic data first. Configure
   an optional custom domain in Render if desired. The frontend and API remain
   on the same host.

The Blueprint enables voice calls and keeps one web instance because the call
scheduler runs in that API process. Do not scale the service to multiple
instances without moving scheduled work to a shared worker. Reminder and call
records are stored in Postgres.

### Local production build and commands

From the project root:

```powershell
# Backend
.\.venv\Scripts\Activate.ps1
Set-Location backend
python -m uvicorn app.main:app --reload

# Frontend, in another terminal from the project root
Set-Location frontend
npm.cmd ci
npm.cmd run dev

# Production frontend build
npm.cmd run build

# Full container build, matching the hosted deployment
docker build -t medimate-ai .
```

Local dev uses Vite's `/api` proxy to `http://localhost:8000`. The hosted build
also uses `/api`, served by the same FastAPI origin; no localhost API URL is
embedded in production assets. The scheduler runs in the backend process, even
when no browser is open. Twilio calls and background web reminders still need
the hosted process and database to be available.

### Deployment limits to resolve before real patient use

This remains a prototype, not a clinically or privacy reviewed medical
service. The project has no versioned database migrations, account recovery,
email verification, MFA, caregiver-controlled session revocation, or durable
distributed login rate limiter. The 30-day cookie is revocable on sign-out but
there is no per-device session management screen. Do not put real health
information into a public demo until those controls and applicable privacy,
security, and regulatory obligations have been reviewed.

## License

This project is licensed under the MIT License; see [LICENSE](LICENSE).
