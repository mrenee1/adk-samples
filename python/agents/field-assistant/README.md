# Field Assistant

A phone app for door-to-door business sales reps. Plan the day, log every
knock in a few taps, submit a daily report at night, and let the app handle
the time-wasters:

| Time-waster | What the app does |
|---|---|
| **Business cards** | Snap a photo → Gemini reads it → check the fields → saved as a contact on that business. |
| **Site surveys** | One tap → request pre-filled with business, address and contact → sent as an email or opened as your survey form. The business moves to *Site Survey*. |
| **ROEs** | One tap → owner of record pulled from the **county property appraiser** (Duval and Nassau today), with mailing address, parcel and a Sunbiz link for LLCs → an email to David (or whoever) is drafted with everything in it. |
| **Daily report** | Knocks vs. goal, decision-maker talks, follow-ups, sales, surveys and ROEs, counted automatically and emailed to your manager. |
| **Zoho, later** | *Settings → Download for Zoho* gives import-ready CSVs (Leads, Accounts, Contacts, Deals, Tasks, Visits) plus step-by-step import instructions. |

It is built with **ADK** (the "Ask" tab agent), **AG-UI** (how the agent
streams to the app) and **A2UI** (the review cards for card scans, surveys,
ROEs and emails). Reps never have to type to the agent: every screen works
with plain buttons, and the buttons show the same A2UI cards the agent does.

```
Phone (web app, installable)          Cloud Run (one service)
 Plan · Knock · Submit · Ask  ───────► FastAPI
                                        ├─ /api/*        plan, knocks, report, import/export
                                        ├─ /api/agent    ADK agent over AG-UI (streams A2UI cards)
                                        └─ /             the web app
                                       Firestore (data) · Gemini (card reading, Ask)
                                       County map services (owner lookups)
```

## The rep's day

1. **Plan** (morning): add suggested stops (follow-ups due come first, then
   open surveys/ROEs, then businesses not visited yet), reorder, *Open route*
   in Google Maps.
2. **Knock** (all day): tap a stop → tap an outcome → *Save knock*. The
   follow-up date fills itself (weekdays only). No signal? It saves on the
   phone and sends later. Each stop has **📇 Card · 📋 Survey · 🏢 ROE ·
   ✉️ Email · 📞 Call**. *+ Walk-in* for anything not on the plan.
3. **Submit** (night): review the numbers, add wins/blockers, *Submit my
   day* → email to the manager.

## Try it on your computer (10 minutes)

You need Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
cd python/agents/field-assistant
uv sync
cp .env.example .env              # paste a Gemini key from https://aistudio.google.com/apikey
uv run python -m field_assistant.seed          # 8 fake businesses on real streets
uv run --env-file .env uvicorn field_assistant.server:app --reload --port 8080
```

Open http://localhost:8080. To see it as a phone, use your browser's
device toolbar (Chrome: F12 → phone icon). Without a Gemini key everything
works except card reading and the Ask tab.

**Load your own tracker:** ⚙ Settings → *Bring in your tracker* → pick your
`.xlsx`/`.csv` (needs a column called Business, Company or Account Name;
Address, City, ZIP, Phone, Email, Contact, Status, Next follow-up and Notes
are picked up too). The earlier Fieldnote app's `data.json` works as well.
Importing again updates instead of duplicating. Your data stays in `data/`,
which git ignores.

## Put it on Google Cloud

One time, in the [Google Cloud console](https://console.cloud.google.com/):

1. Create a project (or use one) and turn on billing. Set a budget alert
   (Billing → Budgets) at about $10/month; one or two reps should cost a
   few dollars at most.
2. Add Firebase to the same project at https://console.firebase.google.com
   → *Add project* → pick your Google Cloud project.
   - **Build → Authentication → Get started → Google** → Enable.
   - **Build → Firestore Database → Create database** (production mode,
     same region as below, e.g. `us-east1`).
   - **Project settings → Your apps → Web (`</>`)** → register an app →
     copy the `firebaseConfig` values.
3. In a terminal with the [gcloud CLI](https://cloud.google.com/sdk/docs/install):

```bash
gcloud config set project YOUR-PROJECT
gcloud services enable run.googleapis.com aiplatform.googleapis.com \
    firestore.googleapis.com cloudbuild.googleapis.com

# Let the service read/write Firestore and call Gemini
PROJECT_NUMBER=$(gcloud projects describe YOUR-PROJECT --format='value(projectNumber)')
SA=$PROJECT_NUMBER-compute@developer.gserviceaccount.com
gcloud projects add-iam-policy-binding YOUR-PROJECT --member=serviceAccount:$SA --role=roles/datastore.user
gcloud projects add-iam-policy-binding YOUR-PROJECT --member=serviceAccount:$SA --role=roles/aiplatform.user

cp env.yaml.example env.yaml      # fill in ALLOWED_EMAILS and FIREBASE_WEB_CONFIG
gcloud run deploy field-assistant --source . --region us-east1 \
    --allow-unauthenticated --env-vars-file env.yaml \
    --min-instances 0 --max-instances 2
```

4. Copy the `https://field-assistant-….run.app` address it prints, then in
   Firebase → Authentication → **Settings → Authorized domains** → add
   that domain.
5. On the phone, open the address → *Sign in with Google* → Share → **Add
   to Home Screen**. It now opens like an app.

"Allow unauthenticated" only means the page loads for anyone; every API call
checks the Google sign-in **and** the `ALLOWED_EMAILS` list, and each rep
only ever sees their own records.

**Email drafts:** signing in asks for permission to *create Gmail drafts*
(not to read or send mail). With it, *Save to Gmail drafts* puts the ROE,
survey or report straight into Drafts. Without it (or after an hour),
*Open in email app* opens the phone's mail app with everything filled in.
If the rep uses a personal Gmail, Google will warn that the app is
unverified until you publish the consent screen; for a few users in
"Testing" mode, add them as test users under *APIs & Services → OAuth
consent screen*.

To update after a change: run the same `gcloud run deploy` command.

## Tweak it

| You want to change… | Where |
|---|---|
| Knock buttons, follow-up days, pipeline stages | `field_assistant/field.py` (`OUTCOMES`, `STAGES`) |
| ROE / survey / follow-up email wording | ⚙ Settings → *Email templates* (no code), defaults in `config.py` |
| How a survey is ordered (email, form link, just record) | ⚙ Settings → *Site survey* |
| Daily goal, manager email, who gets ROEs | ⚙ Settings |
| Add a county for ROE lookups | `field_assistant/property_lookup.py`: write `_lookup_<county>()`, list its ZIPs |
| What the ROE/survey/card review cards show | `field_assistant/a2ui.py` |
| What the Ask agent can do | `field_assistant/agent.py` (add a function to `tools=`) |
| Screens and colors | `web/app.js`, `web/app.css` |
| Zoho column names | `field_assistant/zoho_export.py` |

Run the checks after a change: `uv run pytest` (no network or keys needed)
and `uv run ruff check .`.

You can also chat with the agent in ADK's dev UI: `uv run adk web .` from
this folder's parent.

## Data and privacy

- Territory and customer data belong to your company. Keep real files out of
  git (`data/`, `*.xlsx`, `*.csv` are ignored) and out of public web hosts.
  The demo seed uses invented names and numbers.
- County owner lookups use the counties' public map services. Always
  confirm the owner matches the building before sending an ROE.
- Card photos are stored with the contact so you can recheck them later.
  Delete them in Firestore (`uploads`) if your company prefers not to keep them.

## Files

```
field_assistant/
  agent.py            ADK agent + tools (Ask tab)
  server.py           FastAPI: REST API, AG-UI endpoint, static app
  field.py            plan, knocks, follow-ups, stats, submit
  workflows.py        card scan / survey / ROE: start and finish
  a2ui.py             A2UI review cards
  property_lookup.py  Duval + Nassau owner-of-record lookups
  card_scanner.py     Gemini vision → contact fields
  emails.py           template filling
  importer.py         tracker import (xlsx/csv/Fieldnote json)
  zoho_export.py      Zoho CRM import files
  store.py            JSON files locally, Firestore in the cloud
  auth.py             Firebase Google sign-in check
web/                  the phone app (no build step)
tests/                pytest, no network needed
```
