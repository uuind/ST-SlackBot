# ST-SlackBot

> Feedback sender for Practice Performances and EOQM/EOYM messages.

---

## 📋 Prerequisites

1. **Slack Bot Token** in Streamlit secrets (`.streamlit/secrets.toml`):
   ```toml
   SLACK_BOT_TOKEN = "xoxb-xxxxxxxxxxxx"
   ```
   *(Or alternatively via `token.env` / environment variables)*
2. **Member Slack ID mapping** in `name_list.json`:
   ```json
   {
       "name1": "U0123456789",
       "name2": "U0987654321"
   }
   ```
3. **Slack Bot Permissions**:
   - `chat:write`: Send messages to channels
   - `im:write`: Send direct messages to members
   - `users:read`: Auto-fetch workspace members and Slack IDs into the roster table.

---

## 🔐 User Authentication (Username & Password)

The app restricts access to authorized users via matching username and password credentials:

- **Configuring Accounts**:
  In `.streamlit/secrets.toml` (locally) or Streamlit Cloud Secrets (**App Settings → Secrets**):
  ```toml
  [users]
  admin = "admin_password"
  pd_lead = "pd_team_password"
  ```
- **Local Fallback**:
  If no users are configured in secrets, the default fallback is username `admin` with password `taiko`.
- **Session Unlock**:
  Signing in unlocks the app for the duration of the browser session. Clicking **🚪 Log Out** locks the app again.

---

## 🚀 Running the Streamlit GUI

Launch the interactive web application:

```bash
streamlit run app.py
```

### 🌟 Streamlined 4-Step Workflow

```mermaid
flowchart LR
    A["📂 1. Setup & Spreadsheet<br/>(Roster, Upload & Auto-Detect)"] --> B["👥 2. Review Groups / Columns<br/>(Auto-detect & Assign Members)"]
    B --> C["💬 3. Review Comments<br/>(Authentic Slack DM Preview)"]
    C --> D["🚀 4. Send Comments<br/>(Test Send & Live Dispatch)"]
```

1. **📂 Step 1: Setup & Spreadsheet**:
   - **Member Roster (`name_list.json`)**: Click **"🏷️ Fetch Slack IDs (`users:read`)"** to pull active workspace members, **"📁 Import JSON"** to upload an existing directory, or **"📥 Export JSON"** to download the online copy. Expand **"View & Edit Member Names"** anytime to adjust spreadsheet names.
   - **Spreadsheet & Auto Mode Detection**: Select or upload an `.xlsx` form. ST-SlackBot automatically detects whether it's in **PD Mode** (performance/group songs) or **LC Mode** (committee feedback columns) and lets you customize the **Message Header Banner** at the top of each DM.
   - **Optional Settings**: Collapsible menu for Slack bot token test/save, dedicated **Group** and **Individual** column search keywords, and `config.json` import/export.
   - Click **"⚡ Parse Spreadsheet & Proceed to Review Groups ➡️"** to advance.

2. **👥 Step 2: Review Groups** (or **Review Member Columns** in LC mode):
   - Review detected groups and columns.
   - In PD mode, use **"🪄 Auto-Detect All from Comments"** to scan comments for member names, assign members via multi-selects (with custom name typing), and check unassigned member warnings.
   - Click **"💬 Generate Comments & Proceed to Preview ➡️"**.

3. **💬 Step 3: Review Comments**:
   - Inspect authentic Slack DM previews with simulated dark/light themes.
   - Cycle through members via dropdown or **"🎲 View Random Sample"**, inspect section breakdowns, and audit all recipients.

4. **🚀 Step 4: Send Comments to Slack**:
   - Filter or select recipients via the readiness checklist.
   - Use the **"Optional: Send Test Message First"** form to deliver a sample exclusively to your own test Slack ID.
   - Confirm and click **"🚀 Send Slack Messages"** with live progress tracking and delivery logs.

---

## 💻 Running via CLI

You can also run the command-line runner directly:

```bash
python main.py
```
