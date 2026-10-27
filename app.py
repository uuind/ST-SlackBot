import os
import json
import time
import random
from collections import defaultdict
import streamlit as st
import pandas as pd
from pathlib import Path

import config
import bot_logic
import auth

# -----------------------------------------------------------------------------
# Streamlit Page Setup
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="ST SlackBot",
    page_icon="🥁",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for styling
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1f2937;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        color: #4b5563;
        font-size: 1.05rem;
        margin-bottom: 1.2rem;
    }
    .slack-preview-card {
        background-color: #1e1e24;
        color: #f3f4f6;
        border-radius: 8px;
        padding: 1.2rem;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        border-left: 4px solid #4a154b;
        margin-bottom: 1rem;
        white-space: pre-wrap;
    }
    .slack-preview-header {
        color: #9ca3af;
        font-size: 0.85rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    .badge-pd {
        background-color: #e0f2fe;
        color: #0369a1;
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-lc {
        background-color: #fef3c7;
        color: #92400e;
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .group-card {
        background-color: #f9fafb;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Session State Initialization
# -----------------------------------------------------------------------------
if "config_loaded" not in st.session_state:
    config.load_config()
    st.session_state["config_loaded"] = True

if "name_dict" not in st.session_state:
    st.session_state["name_dict"] = bot_logic.load_name_list(config.name_filepath)

if "group_configs" not in st.session_state:
    st.session_state["group_configs"] = []

if "parsed_comments" not in st.session_state:
    st.session_state["parsed_comments"] = {}

if "full_messages" not in st.session_state:
    st.session_state["full_messages"] = {}

if "active_spreadsheet_name" not in st.session_state:
    st.session_state["active_spreadsheet_name"] = config.form_file

if "selected_recipient_idx" not in st.session_state:
    st.session_state["selected_recipient_idx"] = 0

if "has_assigned_names" not in st.session_state:
    st.session_state["has_assigned_names"] = False

if "slack_token" not in st.session_state:
    st.session_state["slack_token"] = config.slack_token

if "name_list_source" not in st.session_state:
    st.session_state["name_list_source"] = config.name_filepath


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------
def get_active_token():
    """Get active Slack bot token from session state or config."""
    return st.session_state.get("slack_token") or config.slack_token


def refresh_name_list():
    st.session_state["name_dict"] = bot_logic.load_name_list(config.name_filepath)
    st.session_state["name_list_source"] = config.name_filepath


def clear_group_gui_state():
    """Clear all group and member GUI items and parsed feedback."""
    keys_to_clear = [
        k for k in list(st.session_state.keys())
        if any(k.startswith(prefix) for prefix in (
            "members_", "input_add_", "btn_add_", "multiselect_group_",
            "g_col_", "i_col_", "name_", "title_", "custom_name_",
            "btn_detect_", "del_group_", "btn_clr_", "add_miss_"
        ))
    ]
    for k in keys_to_clear:
        del st.session_state[k]
    st.session_state["group_configs"] = []
    st.session_state["parsed_comments"] = {}
    st.session_state["full_messages"] = {}
    st.session_state["selected_recipient_idx"] = 0
    st.session_state["has_assigned_names"] = False


def trigger_parse_comments(sheet):
    """Parse comments according to current mode and group/column config."""
    name_list = list(st.session_state["name_dict"].keys())
    if config.mode == "PD":
        if st.session_state["group_configs"]:
            # Sync members and columns from session state if present
            for g in st.session_state["group_configs"]:
                gid = g.get("id")
                if gid and f"members_{gid}" in st.session_state:
                    g["members"] = list(st.session_state[f"members_{gid}"])
                if gid and f"g_col_{gid}" in st.session_state:
                    g["group_col"] = st.session_state[f"g_col_{gid}"]
                if gid and f"i_col_{gid}" in st.session_state:
                    g["indiv_col"] = st.session_state[f"i_col_{gid}"]
                if gid and f"name_{gid}" in st.session_state:
                    g["group_name"] = st.session_state[f"name_{gid}"]
            comments, msgs = bot_logic.parse_pd_comments(sheet, st.session_state["group_configs"])
            st.session_state["parsed_comments"] = comments
            st.session_state["full_messages"] = msgs
            st.session_state["last_parsed_mode"] = "PD"
    elif config.mode == "LC":
        comments, msgs = bot_logic.parse_lc_comments(sheet, name_list)
        st.session_state["parsed_comments"] = comments
        st.session_state["full_messages"] = msgs
        st.session_state["last_parsed_mode"] = "LC"


# -----------------------------------------------------------------------------
# User Authentication Screen (Access Gate)
# -----------------------------------------------------------------------------
if not st.session_state.get("authenticated"):
    st.markdown('<div class="main-title">🥁 ST SlackBot</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Personal Feedback Dispatcher for Practice Performances & Committee Notes</div>', unsafe_allow_html=True)
    st.markdown("---")

    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        st.markdown("### 🔐 User Login")
        st.caption("Please sign in with your authorized username and password.")

        with st.form("login_form"):
            username_input = st.text_input("Username", placeholder="Enter username")
            password_input = st.text_input("Password", type="password", placeholder="Enter password")
            submit_login = st.form_submit_button("🚀 Sign In", type="primary", use_container_width=True)

            if submit_login:
                ok, err_msg = auth.verify_credentials(username_input, password_input)
                if ok:
                    st.session_state["authenticated"] = True
                    st.session_state["user_label"] = username_input.strip()
                    st.toast(f"Welcome, {st.session_state['user_label']}!", icon="👋")
                    st.rerun()
                else:
                    st.error(err_msg)

        with st.expander("ℹ️ Configuring user accounts on Streamlit Cloud", expanded=False):
            st.markdown("""
            In your Streamlit Cloud **App Settings → Secrets** (or `.streamlit/secrets.toml` locally):
            ```toml
            [users]
            admin = "admin_password"
            audrey = "audrey_password"
            pd_lead = "pd_team_password"
            ```
            *(Default local fallback: username `admin` / password `taiko`)*
            """)

    st.stop()


# -----------------------------------------------------------------------------
# Sidebar: User Info, Mode Switcher & Slack Status
# -----------------------------------------------------------------------------
with st.sidebar:
    u_label = st.session_state.get("user_label", "Admin")
    c_u1, c_u2 = st.columns([2, 1])
    with c_u1:
        st.markdown(f"**👤 User:** `{u_label}`")
    with c_u2:
        if st.button("🚪 Log Out", key="sidebar_logout", use_container_width=True):
            st.session_state["authenticated"] = False
            clear_group_gui_state()
            st.rerun()

    st.markdown("---")
    st.markdown("### 🎛️ Mode & Quick Controls")

    # Mode Selector
    current_mode = config.mode
    mode_options = ["PD", "LC"]
    mode_idx = mode_options.index(current_mode) if current_mode in mode_options else 0
    selected_mode = st.radio(
        "Application Mode",
        options=mode_options,
        index=mode_idx,
        help="PD = Performance Director (Group/Song & Individual notes)\nLC = Leadership Committee (EOQM/EOYM notes)"
    )

    if selected_mode != config.mode:
        config.mode = selected_mode
        # Update config.json
        cfg = config.load_config()
        cfg["mode"] = selected_mode
        config.save_config(cfg)
        st.session_state["parsed_comments"] = {}
        st.session_state["full_messages"] = {}
        st.session_state["selected_recipient_idx"] = 0
        st.rerun()

    if st.session_state.get("detected_mode"):
        det_m = st.session_state["detected_mode"]
        if config.mode == det_m:
            st.caption(f"🤖 Matches sheet detection (**{det_m} Mode**)")
        else:
            st.caption(f"⚠️ Manually overridden from sheet's detected **{det_m} Mode**")

    if config.mode == "PD":
        st.info("🎭 **PD Mode Active**\nParses practice feedback grouped by songs/ensembles and filters individual comments.")
    else:
        st.info("📋 **LC Mode Active**\nParses personal feedback columns directly mapped to individual member names.")

    st.markdown("---")
    st.markdown("### 🔌 Slack Bot Connection")
    active_tok = get_active_token()
    token_preview = f"...{active_tok[-8:]}" if len(active_tok) > 8 else (
        "Configured" if active_tok else "Missing"
    )
    st.write(f"**Token:** `{token_preview}`")
    st.write(f"**API URL:** `{config.slack_api_url}`")

    if st.button("🔍 Test Slack Auth", use_container_width=True):
        with st.spinner("Testing Slack connection..."):
            ok, res = bot_logic.test_slack_token(active_tok, config.slack_api_url)
            if ok:
                st.success(f"Connected to **{res.get('team')}** as bot **@{res.get('user')}**!")
            else:
                st.error(f"Connection test failed: {res}")

    st.markdown("---")
    st.markdown(f"**Members in Name List:** `{len(st.session_state['name_dict'])}`")
    st.caption("ST SlackBot v2.0 • Streamlit GUI")


# -----------------------------------------------------------------------------
# Main Header
# -----------------------------------------------------------------------------
col_title, col_badge = st.columns([3, 2])
with col_title:
    st.markdown('<div class="main-title">ST SlackBot v2</div>', unsafe_allow_html=True)
    u_label = st.session_state.get("user_label", "Admin")
    st.markdown(f'<div class="sub-title">Session: **@{u_label}** • Active: `{config.mode} Mode`</div>', unsafe_allow_html=True)

with col_badge:
    c_b1, c_b2 = st.columns([1, 1])
    with c_b1:
        mode_badge_html = f'<div style="text-align: right; margin-top: 15px;"><span class="{"badge-pd" if config.mode == "PD" else "badge-lc"}">{config.mode} MODE</span></div>'
        st.markdown(mode_badge_html, unsafe_allow_html=True)
    with c_b2:
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        if st.button("🚪 Log Out", key="header_logout", use_container_width=True):
            st.session_state["authenticated"] = False
            clear_group_gui_state()
            st.rerun()

# -----------------------------------------------------------------------------
# Main Navigation Tabs
# -----------------------------------------------------------------------------
tab_config, tab_upload, tab_groups, tab_preview, tab_send = st.tabs([
    "⚙️ 1. Configuration & Roster",
    "📁 2. Spreadsheet & Setup",
    "👥 3. Group & Member Management",
    "💬 4. Preview Sample Comments",
    "🚀 5. Review & Send"
])


# =============================================================================
# TAB 1: CONFIGURATION & ROSTER
# =============================================================================
with tab_config:
    st.subheader("⚙️ Step 1: Configuration & Member Roster")
    st.markdown(
        "Set up your bot parameters, search terms, Slack token, and member roster. "
        "You can upload existing `.json` files or adjust settings directly in the fields below."
    )

    # Top File Uploaders Row (config.json & member directory JSON)
    c_up_cfg, c_up_mem = st.columns(2)
    with c_up_cfg:
        st.markdown("##### 📄 Upload `config.json` (Optional)")
        uploaded_cfg_file = st.file_uploader(
            "Upload Configuration JSON (`config.json`)",
            type=["json"],
            key="upload_config_file",
            help="Upload a config.json file to update mode, search terms, and Slack settings."
        )
        if uploaded_cfg_file is not None:
            cfg_sig = f"{uploaded_cfg_file.name}_{uploaded_cfg_file.size}"
            if st.session_state.get("last_uploaded_cfg_sig") != cfg_sig:
                try:
                    cfg_data = json.loads(uploaded_cfg_file.getvalue().decode("utf-8"))
                    if isinstance(cfg_data, dict):
                        st.session_state["last_uploaded_cfg_sig"] = cfg_sig
                        config.save_config(cfg_data)
                        st.toast(f"Loaded configuration from {uploaded_cfg_file.name}!", icon="⚙️")
                        st.rerun()
                except Exception as e:
                    st.error(f"Error parsing config.json: {e}")

    with c_up_mem:
        st.markdown("##### 👥 Upload Member Roster (Optional)")
        uploaded_name_file = st.file_uploader(
            "Upload Member Roster (`name_list.json` / roster)",
            type=["json"],
            key="upload_name_file",
            help="Upload member names and Slack IDs. Flexible JSON formats supported."
        )
        if uploaded_name_file is not None:
            name_sig = f"{uploaded_name_file.name}_{uploaded_name_file.size}"
            if st.session_state.get("last_uploaded_name_sig") != name_sig:
                try:
                    parsed_dict = bot_logic.parse_name_list_json(uploaded_name_file.getvalue())
                    if parsed_dict:
                        st.session_state["name_dict"] = parsed_dict
                        st.session_state["name_list_source"] = uploaded_name_file.name
                        st.session_state["last_uploaded_name_sig"] = name_sig
                        bot_logic.save_name_list(parsed_dict, config.name_filepath)
                        st.toast(f"Imported {len(parsed_dict)} members from {uploaded_name_file.name}!", icon="📥")
                        st.rerun()
                    else:
                        st.error("Uploaded JSON was empty or did not contain recognizable member names.")
                except Exception as e:
                    st.error(f"Error parsing roster JSON: {e}")

    st.markdown("---")

    cfg = config.load_config()

    # Section 1: Mode & Settings
    c_cfg1, c_cfg2 = st.columns(2)

    with c_cfg1:
        st.markdown("##### 🎭 Mode Setting")
        mode_radio = st.radio(
            "Bot Mode",
            ["PD", "LC"],
            index=0 if config.mode == "PD" else 1,
            help="PD = Performance Director (Group/Song & Individual notes)\nLC = Leadership Committee (EOQM/EOYM individual notes)"
        )

        st.markdown("##### 📁 File & Folder Settings")
        cfg_name_file = st.text_input("Name List JSON File", value=config.name_filepath)
        cfg_folder = st.text_input("Spreadsheets Folder", value=config.spreadsheet_folder)
        cfg_form_file = st.text_input("Default Form File", value=config.form_file)

    with c_cfg2:
        st.markdown("##### 🔍 Search Terms (PD Mode)")
        st.markdown("Keywords used to detect group and individual columns in the spreadsheet:")
        terms_text = st.text_area(
            "Search Terms (comma-separated)",
            value=", ".join(config.search_list),
            help="Columns matching any of these terms will be scanned for group feedback."
        )
        updated_search_terms = [t.strip() for t in terms_text.split(",") if t.strip()]

        st.markdown("##### 🔌 Slack API Settings")
        cfg_api_url = st.text_input("Slack API URL", value=config.slack_api_url)
        cfg_token = st.text_input(
            "Slack Bot Token (SLACK_BOT_TOKEN)",
            value=get_active_token(),
            type="password",
            help="Slack bot token starting with xoxb-. On Streamlit Cloud, add this in App Settings → Secrets."
        )

        col_token_save, col_token_test = st.columns(2)
        with col_token_save:
            if st.button("💾 Apply / Save Token", use_container_width=True, help="Applies to current session and saves to .streamlit/secrets.toml if writable"):
                clean_tok, saved_to_disk = config.save_token(cfg_token)
                st.session_state["slack_token"] = clean_tok
                if saved_to_disk:
                    st.toast("Saved Slack token to .streamlit/secrets.toml!", icon="🔑")
                else:
                    st.info("ℹ️ **Token active for this session!** (Running in a read-only environment like Streamlit Cloud). To persist permanently, open your **Streamlit Cloud Dashboard → App Settings → Secrets** and add `SLACK_BOT_TOKEN = \"...\"`.")
        with col_token_test:
            if st.button("🔍 Test Token Auth", use_container_width=True):
                ok, res = bot_logic.test_slack_token(cfg_token, cfg_api_url)
                if ok:
                    st.success(f"Auth OK: @{res.get('user')} on {res.get('team')}")
                else:
                    st.error(f"Auth error: {res}")

    if st.button("💾 Save Settings to config.json", type="primary", use_container_width=True):
        mode_changed = mode_radio != config.mode
        new_config = {
            "slack": {
                "api_url": cfg_api_url
            },
            "file": {
                "name_list": cfg_name_file,
                "spreadsheet_folder": cfg_folder,
                "form_file": cfg_form_file
            },
            "search": {
                "terms": updated_search_terms
            },
            "mode": mode_radio
        }
        _, saved_ok = config.save_config(new_config)
        if mode_changed:
            st.session_state["parsed_comments"] = {}
            st.session_state["full_messages"] = {}
            st.session_state["selected_recipient_idx"] = 0
        if saved_ok:
            st.toast("Saved configuration to config.json!", icon="💾")
        else:
            st.info("ℹ️ Settings applied to active session (local filesystem is read-only).")
        st.rerun()

    st.markdown("---")

    # Section 2: Member Name List Editor & Downloader
    c_sec_hdr, c_sec_dn = st.columns([3, 2])
    with c_sec_hdr:
        st.markdown("##### 👥 Member Name & Slack ID Directory")
        source_label = st.session_state.get("name_list_source", config.name_filepath)
        st.caption(f"Active Directory Source: `{source_label}` ({len(st.session_state['name_dict'])} members loaded)")
    with c_sec_dn:
        json_export = json.dumps(st.session_state["name_dict"], indent=2)
        st.download_button(
            "📥 Download Directory (JSON)",
            data=json_export,
            file_name=st.session_state.get("name_list_source", "name_list.json"),
            mime="application/json",
            use_container_width=True,
            help="Download the current member name & Slack ID directory as a JSON file"
        )

    name_records = [
        {"Name": k, "Slack ID": v}
        for k, v in st.session_state["name_dict"].items()
    ]
    df_names = pd.DataFrame(name_records)

    edited_df = st.data_editor(
        df_names,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Name": st.column_config.TextColumn("Member Name (lowercase)", required=True),
            "Slack ID": st.column_config.TextColumn("Slack User ID (e.g. U0XXXXXXX)", required=True)
        }
    )

    c_save_names, c_reload_names = st.columns([2, 1])
    with c_save_names:
        if st.button("💾 Apply & Save Directory", type="primary", use_container_width=True):
            updated_dict = {}
            for _, row in edited_df.iterrows():
                name_val = str(row["Name"]).strip().lower() if pd.notna(row["Name"]) else ""
                id_val = str(row["Slack ID"]).strip() if pd.notna(row["Slack ID"]) else ""
                if name_val:
                    updated_dict[name_val] = id_val

            st.session_state["name_dict"] = updated_dict
            saved_ok = bot_logic.save_name_list(updated_dict, config.name_filepath)
            if saved_ok:
                st.toast(f"Saved {len(updated_dict)} members to {config.name_filepath}!", icon="👥")
            else:
                st.toast(f"Updated {len(updated_dict)} members in active session!", icon="👥")
            st.rerun()

    with c_reload_names:
        if st.button("🔄 Reload from Default File", use_container_width=True):
            refresh_name_list()
            st.rerun()


# =============================================================================
# TAB 2: SPREADSHEET & SETUP
# =============================================================================
with tab_upload:
    st.subheader("📁 Step 2: Spreadsheet Selection & Setup")

    col_src1, col_src2 = st.columns(2)
    with col_src1:
        source_type = st.radio(
            "Spreadsheet Source",
            ["Choose existing from spreadsheets folder", "Upload new spreadsheet (.xlsx)"],
            label_visibility="collapsed"
        )

    sheet_source = None
    loaded_file_label = ""

    if source_type == "Choose existing from spreadsheets folder":
        existing_files = bot_logic.get_available_spreadsheets(config.spreadsheet_folder)
        if not existing_files:
            st.warning(f"No .xlsx spreadsheets found in `{config.spreadsheet_folder}/` folder.")
        else:
            default_idx = existing_files.index(config.form_file) if config.form_file in existing_files else 0
            selected_file = st.selectbox("Select Spreadsheet", existing_files, index=default_idx)
            if selected_file:
                sheet_source = os.path.join(config.spreadsheet_folder, selected_file)
                loaded_file_label = selected_file
                st.session_state["active_spreadsheet_name"] = selected_file

    else:
        uploaded_file = st.file_uploader("Upload an Excel file (.xlsx)", type=["xlsx"])
        if uploaded_file is not None:
            sheet_source = uploaded_file
            loaded_file_label = uploaded_file.name
            st.session_state["active_spreadsheet_name"] = uploaded_file.name

            save_uploaded = st.checkbox("Save a copy to spreadsheets folder", value=True)
            if save_uploaded:
                save_path = os.path.join(config.spreadsheet_folder, uploaded_file.name)
                os.makedirs(config.spreadsheet_folder, exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                st.success(f"Saved `{uploaded_file.name}` to `{config.spreadsheet_folder}/`.")

    # Load and inspect sheet if source is available
    if sheet_source is not None:
        try:
            wb, sheet, sheet_names = bot_logic.load_workbook_and_sheet(sheet_source)
            st.session_state["wb"] = wb
            st.session_state["sheet"] = sheet

            st.success(f"Loaded spreadsheet: **{loaded_file_label}**")

            # Sheet selector if multiple sheets
            if len(sheet_names) > 1:
                selected_sheet_name = st.selectbox("Worksheet", sheet_names, index=sheet_names.index(sheet.title) if sheet.title in sheet_names else 0)
                if selected_sheet_name != sheet.title:
                    sheet = wb[selected_sheet_name]
                    st.session_state["sheet"] = sheet

            headers = bot_logic.get_sheet_headers(sheet)
            st.session_state["headers"] = headers

            # Run Auto-detection on Spreadsheet Headers
            all_known = list(st.session_state["name_dict"].keys())
            detected_mode, detect_reason, detect_details = bot_logic.detect_spreadsheet_mode(
                headers, all_known, config.search_list
            )
            st.session_state["detected_mode"] = detected_mode
            st.session_state["detected_reason"] = detect_reason

            # When a new spreadsheet is loaded, clear all names/groups/feedback GUI items
            if st.session_state.get("last_loaded_file") != loaded_file_label:
                st.session_state["last_loaded_file"] = loaded_file_label
                clear_group_gui_state()
                if config.mode != detected_mode:
                    config.mode = detected_mode
                    cfg = config.load_config()
                    cfg["mode"] = detected_mode
                    config.save_config(cfg)

                # Initialize detected groups with strictly EMPTY member lists
                if config.mode == "PD":
                    paired, _, _ = bot_logic.detect_groups_pd(headers, config.search_list)
                    st.session_state["group_configs"] = [
                        {
                            "id": f"grp_{i}_{int(time.time()*1000)}",
                            "group_name": p["group_name"],
                            "group_col": p["group_col"],
                            "indiv_name": p["indiv_name"],
                            "indiv_col": p["indiv_col"],
                            "members": []  # Strictly empty on load
                        }
                        for i, p in enumerate(paired)
                    ]
                st.toast(f"Loaded {loaded_file_label}. Cleared group assignments & names.", icon="🧹")
                st.rerun()

            # Basic Metrics
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Rows / Responses", max(sheet.max_row - 1, 0))
            m2.metric("Total Columns", len(headers))
            m3.metric("Current Mode", config.mode)

            # Auto-detection Banner & Manual Override
            st.markdown("---")
            c_det_info, c_det_btn = st.columns([3, 2])
            with c_det_info:
                st.markdown("##### 🤖 Spreadsheet Mode Detection")
                if config.mode == detected_mode:
                    st.success(f"**Auto-detected: {detected_mode} Mode** — {detect_reason}")
                else:
                    st.warning(f"**Manual Override Active:** Using **{config.mode} Mode** (Sheet format was detected as **{detected_mode} Mode** — *{detect_reason}*).")

            with c_det_btn:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                other_mode = "LC" if config.mode == "PD" else "PD"
                col_ovr, col_redet = st.columns(2)
                with col_ovr:
                    if st.button(f"Switch to {other_mode} (Override)", use_container_width=True):
                        config.mode = other_mode
                        cfg = config.load_config()
                        cfg["mode"] = other_mode
                        config.save_config(cfg)
                        st.session_state["group_configs"] = []
                        st.session_state["parsed_comments"] = {}
                        st.session_state["full_messages"] = {}
                        st.session_state["selected_recipient_idx"] = 0
                        st.rerun()
                with col_redet:
                    if st.button("🪄 Re-detect Mode", use_container_width=True):
                        if config.mode != detected_mode:
                            config.mode = detected_mode
                            cfg = config.load_config()
                            cfg["mode"] = detected_mode
                            config.save_config(cfg)
                            st.session_state["group_configs"] = []
                            st.session_state["parsed_comments"] = {}
                            st.session_state["full_messages"] = {}
                            st.session_state["selected_recipient_idx"] = 0
                            st.rerun()

            st.markdown("---")

            # Auto-detect groups preview if in PD mode
            if config.mode == "PD":
                paired, _, _ = bot_logic.detect_groups_pd(headers, config.search_list)
                st.markdown(f"**Detected Group Columns ({len(paired)} detected):**")
                tags_html = " ".join([f"`{p['group_name']}`" for p in paired])
                st.markdown(tags_html)
            elif config.mode == "LC":
                matched_cols = [h for h in headers if h and h.lower().strip() in all_known]
                st.markdown(f"**Detected Member Columns ({len(matched_cols)} detected):**")
                st.markdown(" ".join([f"`{h}`" for h in matched_cols[:10]]) + (f" *...and {len(matched_cols)-10} more*" if len(matched_cols) > 10 else ""))

            with st.expander("👀 View Spreadsheet Header & First 3 Responses", expanded=False):
                rows_data = []
                for r in range(1, min(sheet.max_row + 1, 5)):
                    row_vals = [sheet.cell(row=r, column=c).value for c in range(1, len(headers) + 1)]
                    rows_data.append(row_vals)
                if rows_data:
                    df = pd.DataFrame(rows_data[1:], columns=rows_data[0])
                    st.dataframe(df, use_container_width=True)

        except Exception as e:
            st.error(f"Error loading workbook: {e}")
    else:
        st.info("Please select or upload a spreadsheet above to begin.")


# =============================================================================
# TAB 3: GROUP & MEMBER MANAGEMENT
# =============================================================================
with tab_groups:
    if "sheet" not in st.session_state:
        st.warning("Please upload or select a spreadsheet in Step 2 (Spreadsheet & Setup) first.")
    else:
        sheet = st.session_state["sheet"]
        headers = st.session_state.get("headers", bot_logic.get_sheet_headers(sheet))
        all_known_members = sorted(list(st.session_state["name_dict"].keys()))

        if config.mode == "PD":
            st.subheader("👥 Performance Groups & Member Assignments")
            st.markdown(
                "Configure each group's name, its corresponding group feedback column, "
                "paired individual feedback column, and assign members to each group."
            )

            # Ensure defaults if session state group_configs is empty (strictly empty member lists)
            if not st.session_state["group_configs"]:
                paired, _, _ = bot_logic.detect_groups_pd(headers, config.search_list)
                initial_configs = []
                for i, p in enumerate(paired):
                    gid = f"grp_{i}_{int(time.time()*1000)}"
                    initial_configs.append({
                        "id": gid,
                        "group_name": p["group_name"],
                        "group_col": p["group_col"],
                        "indiv_name": p["indiv_name"],
                        "indiv_col": p["indiv_col"],
                        "members": []  # Strictly empty by default!
                    })
                    st.session_state[f"members_{gid}"] = []
                st.session_state["group_configs"] = initial_configs

            # -------------------------------------------------------------
            # Callbacks for Group & Member Management Actions
            # (Ensures all state modifications happen BEFORE widgets instantiate)
            # -------------------------------------------------------------
            def cb_add_new_group(headers_len):
                new_group_num = len(st.session_state["group_configs"]) + 1
                first_col = 1 if headers_len > 0 else None
                new_gid = f"grp_{new_group_num}_{int(time.time()*1000)}"
                st.session_state["group_configs"].append({
                    "id": new_gid,
                    "group_name": f"Group {new_group_num}",
                    "group_col": first_col,
                    "indiv_name": None,
                    "indiv_col": None,
                    "members": []
                })
                st.session_state[f"members_{new_gid}"] = []

            def cb_auto_detect_all():
                sheet_obj = st.session_state.get("sheet")
                if not sheet_obj:
                    return
                all_known = sorted(list(st.session_state["name_dict"].keys()))
                for g in st.session_state.get("group_configs", []):
                    gid = g.get("id")
                    i_col = st.session_state.get(f"i_col_{gid}", g.get("indiv_col"))
                    g_nm = st.session_state.get(f"name_{gid}", g.get("group_name", ""))
                    detected = bot_logic.auto_detect_members_for_group(
                        sheet_obj, i_col, all_known, group_name=g_nm
                    )
                    g["members"] = detected
                    st.session_state[f"members_{gid}"] = detected
                st.session_state["has_assigned_names"] = True

            def cb_clear_all():
                for g in st.session_state.get("group_configs", []):
                    gid = g.get("id")
                    g["members"] = []
                    st.session_state[f"members_{gid}"] = []
                st.session_state["has_assigned_names"] = False

            def cb_reset_groups():
                sheet_obj = st.session_state.get("sheet")
                if not sheet_obj:
                    return
                hdrs = st.session_state.get("headers", bot_logic.get_sheet_headers(sheet_obj))
                clear_group_gui_state()
                paired, _, _ = bot_logic.detect_groups_pd(hdrs, config.search_list)
                reset_configs = []
                for i, p in enumerate(paired):
                    gid = f"grp_{i}_{int(time.time()*1000)}"
                    reset_configs.append({
                        "id": gid,
                        "group_name": p["group_name"],
                        "group_col": p["group_col"],
                        "indiv_name": p["indiv_name"],
                        "indiv_col": p["indiv_col"],
                        "members": []
                    })
                    st.session_state[f"members_{gid}"] = []
                st.session_state["group_configs"] = reset_configs
                st.session_state["has_assigned_names"] = False

            def cb_detect_group(group_id):
                sheet_obj = st.session_state.get("sheet")
                if not sheet_obj:
                    return
                grp = next((g for g in st.session_state.get("group_configs", []) if g.get("id") == group_id), None)
                if not grp:
                    return
                i_col = st.session_state.get(f"i_col_{group_id}", grp.get("indiv_col"))
                g_nm = st.session_state.get(f"name_{group_id}", grp.get("group_name", ""))
                all_known = sorted(list(st.session_state["name_dict"].keys()))
                detected = bot_logic.auto_detect_members_for_group(
                    sheet_obj, i_col, all_known, group_name=g_nm
                )
                st.session_state[f"members_{group_id}"] = detected
                grp["members"] = detected
                st.session_state["has_assigned_names"] = True

            def cb_clear_group(group_id):
                st.session_state[f"members_{group_id}"] = []
                for g in st.session_state.get("group_configs", []):
                    if g.get("id") == group_id:
                        g["members"] = []

            def cb_add_missing(group_id):
                sheet_obj = st.session_state.get("sheet")
                if not sheet_obj:
                    return
                grp = next((g for g in st.session_state.get("group_configs", []) if g.get("id") == group_id), None)
                if not grp:
                    return
                i_col = st.session_state.get(f"i_col_{group_id}", grp.get("indiv_col"))
                g_nm = st.session_state.get(f"name_{group_id}", grp.get("group_name", ""))
                all_known = sorted(list(st.session_state["name_dict"].keys()))
                mentioned = bot_logic.auto_detect_members_for_group(
                    sheet_obj, i_col, all_known, group_name=g_nm
                )
                cur = list(st.session_state.get(f"members_{group_id}", grp.get("members", [])))
                updated = sorted(list(set(cur + mentioned)))
                st.session_state[f"members_{group_id}"] = updated
                grp["members"] = updated
                st.session_state["has_assigned_names"] = True

            def cb_remove_group(group_id):
                configs = st.session_state.get("group_configs", [])
                st.session_state["group_configs"] = [g for g in configs if g.get("id") != group_id]
                member_k = f"members_{group_id}"
                if member_k in st.session_state:
                    del st.session_state[member_k]

            def cb_on_members_change(group_id):
                new_m = list(st.session_state.get(f"members_{group_id}", []))
                for g in st.session_state.get("group_configs", []):
                    if g.get("id") == group_id:
                        g["members"] = new_m
                if new_m:
                    st.session_state["has_assigned_names"] = True
                for m in new_m:
                    clean = m.strip().lower()
                    if clean and clean not in st.session_state["name_dict"]:
                        st.session_state["name_dict"][clean] = ""

            # Quick Actions Row
            btn_col1, btn_col2, btn_col3, btn_col4 = st.columns([2, 2, 2, 2])
            with btn_col1:
                st.button("➕ Add New Group", on_click=cb_add_new_group, args=(len(headers),), use_container_width=True)

            with btn_col2:
                st.button("🪄 Auto-Detect All from Comments", on_click=cb_auto_detect_all, use_container_width=True, help="Scans comments & headers to populate members")

            with btn_col3:
                st.button("🧹 Clear All Group Names", on_click=cb_clear_all, use_container_width=True)

            with btn_col4:
                st.button("🔄 Reset Groups from Sheet", on_click=cb_reset_groups, use_container_width=True)

            # -------------------------------------------------------------
            # Summary Metrics, Missing Names Warnings & Overview (Top Level)
            # -------------------------------------------------------------
            member_group_map = defaultdict(list)
            for g in st.session_state["group_configs"]:
                gid = g.get("id")
                m_list = st.session_state.get(f"members_{gid}", g.get("members", []))
                for m in m_list:
                    member_group_map[m].append(g.get("group_name", "Group"))

            all_assigned_members = sorted(list(member_group_map.keys()))
            has_any_assigned = len(all_assigned_members) > 0
            has_assigned_names = st.session_state.get("has_assigned_names", False) or has_any_assigned

            st.markdown("---")
            c_sm1, c_sm2, c_sm3 = st.columns(3)
            c_sm1.metric("Total Groups", len(st.session_state["group_configs"]))
            c_sm2.metric("Members Assigned", len(all_assigned_members))
            unassigned_count = len([m for m in all_known_members if m not in all_assigned_members]) if has_assigned_names else 0
            c_sm3.metric("Unassigned Directory Members", unassigned_count if has_assigned_names else "-", delta_color="inverse")

            # Missing members warnings: Only shown after auto-detection or manual assignment
            if not has_assigned_names:
                st.info("💡 **Groups are currently empty.** Click **🪄 Auto-Detect All from Comments** above to automatically suggest members from sheet feedback, or select members manually in each group card below.")
            else:
                # 1. Unassigned Directory Members Warning
                unassigned_dir_members = [m for m in all_known_members if m not in all_assigned_members]
                if unassigned_dir_members:
                    st.warning(
                        f"⚠️ **{len(unassigned_dir_members)} member(s) in `name_list.json` are not assigned to any group:** "
                        + ", ".join([f"`{m}`" for m in unassigned_dir_members])
                    )

                # 2. Total Unassigned Mentions across all groups
                all_sheet_mentions = set()
                for g in st.session_state["group_configs"]:
                    indiv_col = st.session_state.get(f"i_col_{g.get('id')}", g.get("indiv_col"))
                    grp_name = st.session_state.get(f"name_{g.get('id')}", g.get("group_name", ""))
                    if indiv_col or grp_name:
                        m_list = bot_logic.auto_detect_members_for_group(
                            sheet, indiv_col, all_known_members, group_name=grp_name
                        )
                        all_sheet_mentions.update(m_list)

                unassigned_sheet_mentions = sorted([m for m in all_sheet_mentions if m not in all_assigned_members])
                if unassigned_sheet_mentions:
                    st.error(
                        f"🚨 **{len(unassigned_sheet_mentions)} member(s) have individual feedback in the spreadsheet but are NOT assigned to any group:** "
                        + ", ".join([f"`{m}`" for m in unassigned_sheet_mentions])
                        + " *(They will not receive their feedback unless assigned)*"
                    )

                # 3. Missing Slack IDs Warning
                missing_slack = [m for m in all_assigned_members if not st.session_state["name_dict"].get(m)]
                if missing_slack:
                    st.error(
                        f"❌ **{len(missing_slack)} assigned member(s) do not have a Slack User ID in `name_list.json`:** "
                        + ", ".join([f"`{m}`" for m in missing_slack])
                        + " *(Add their Slack ID in Step 1 to deliver Slack messages)*"
                    )

            # Expandable Membership Table
            with st.expander("📋 View Membership Summary Table", expanded=len(all_assigned_members) > 0):
                if all_assigned_members:
                    summary_data = []
                    for m in all_assigned_members:
                        slack_id = st.session_state["name_dict"].get(m, "⚠️ Missing Slack ID")
                        groups_str = ", ".join(member_group_map[m])
                        summary_data.append({
                            "Member Name": m,
                            "Slack ID": slack_id,
                            "Assigned Groups": groups_str,
                            "Group Count": len(member_group_map[m])
                        })
                    st.dataframe(pd.DataFrame(summary_data), use_container_width=True)
                else:
                    st.info("No members assigned to any groups yet.")

            st.markdown("---")
            c_head_grp, c_head_btn = st.columns([3, 1])
            with c_head_grp:
                st.markdown("### 🎛️ Group Configurations & Member Assignment")
            with c_head_btn:
                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                if st.button("Generate Comments ➡️", key="btn_gen_top", type="primary", use_container_width=True):
                    trigger_parse_comments(sheet)
                    st.success(f"Parsed feedback for {len(st.session_state['full_messages'])} members!")

            # Column option mapping for dropdowns
            col_options = {idx + 1: f"Col {idx + 1}: {h}" for idx, h in enumerate(headers) if h}
            col_options_with_none = {None: "(None)"}
            col_options_with_none.update(col_options)

            # Render Group Cards
            for idx, group_item in enumerate(st.session_state["group_configs"]):
                # Ensure group has stable unique id
                if "id" not in group_item:
                    group_item["id"] = f"grp_{idx}_{int(time.time()*1000)}"
                group_id = group_item["id"]
                member_key = f"members_{group_id}"

                # Ensure session state has member list initialized
                if member_key not in st.session_state:
                    st.session_state[member_key] = list(group_item.get("members", []))

                with st.container():
                    st.markdown(f'<div class="group-card">', unsafe_allow_html=True)
                    
                    c_title, c_del = st.columns([5, 1])
                    with c_title:
                        group_item["group_name"] = st.text_input(
                            f"Group {idx + 1} Name",
                            value=group_item.get("group_name", f"Group {idx + 1}"),
                            key=f"name_{group_id}"
                        )
                    with c_del:
                        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                        st.button(
                            "🗑️ Remove",
                            key=f"del_group_{group_id}",
                            on_click=cb_remove_group,
                            args=(group_id,),
                            help="Remove this group card"
                        )

                    c_g1, c_g2 = st.columns(2)
                    with c_g1:
                        # Select Group Feedback Column
                        current_g_col = group_item.get("group_col")
                        g_keys = list(col_options_with_none.keys())
                        g_idx = g_keys.index(current_g_col) if current_g_col in g_keys else 0
                        selected_g_col = st.selectbox(
                            f"Group Feedback Column",
                            options=g_keys,
                            format_func=lambda x: col_options_with_none.get(x, f"Col {x}"),
                            index=g_idx,
                            key=f"g_col_{group_id}"
                        )
                        group_item["group_col"] = selected_g_col

                    with c_g2:
                        # Select Individual Feedback Column
                        current_i_col = group_item.get("indiv_col")
                        i_keys = list(col_options_with_none.keys())
                        i_idx = i_keys.index(current_i_col) if current_i_col in i_keys else 0
                        selected_i_col = st.selectbox(
                            f"Individual Feedback Column (filtered by member name)",
                            options=i_keys,
                            format_func=lambda x: col_options_with_none.get(x, str(x)),
                            index=i_idx,
                            key=f"i_col_{group_id}"
                        )
                        group_item["indiv_col"] = selected_i_col
                        group_item["indiv_name"] = headers[selected_i_col - 1] if selected_i_col else None

                    # Members Multi-select with auto-sync and accept_new_options
                    current_m = list(st.session_state.get(member_key, group_item.get("members", [])))
                    all_opts = sorted(list(set(all_known_members + current_m)))

                    c_m_hdr, c_m_det, c_m_clr = st.columns([4, 1.2, 1])
                    with c_m_hdr:
                        st.markdown(f"**Assigned Members ({len(current_m)}):**")
                    with c_m_det:
                        st.button(
                            "🪄 Detect",
                            key=f"btn_detect_{group_id}",
                            on_click=cb_detect_group,
                            args=(group_id,),
                            use_container_width=True,
                            help="Auto-detect members from comments & header for this group"
                        )
                    with c_m_clr:
                        st.button(
                            "🧹 Clear",
                            key=f"btn_clr_{group_id}",
                            on_click=cb_clear_group,
                            args=(group_id,),
                            use_container_width=True,
                            help="Clear members for this group"
                        )

                    st.multiselect(
                        f"Members in {group_item['group_name']}",
                        options=all_opts,
                        key=member_key,
                        on_change=cb_on_members_change,
                        args=(group_id,),
                        accept_new_options=True,
                        placeholder="Search/select member names or type a new name and press Enter...",
                        label_visibility="collapsed"
                    )
                    group_item["members"] = st.session_state.get(member_key, [])

                    # Warning for names mentioned in comments/header but not assigned to this group (only if detection/assignment ran)
                    if has_assigned_names and (selected_i_col or group_item.get("group_name")):
                        mentioned_for_group = bot_logic.auto_detect_members_for_group(
                            sheet, selected_i_col, all_known_members, group_name=group_item.get("group_name", "")
                        )
                        missing_from_group = [m for m in mentioned_for_group if m not in current_m]
                        if missing_from_group:
                            c_w_txt, c_w_btn = st.columns([4, 1.4])
                            with c_w_txt:
                                names_str = ", ".join([f"`{m}`" for m in missing_from_group])
                                st.warning(f"⚠️ **{len(missing_from_group)} name(s) mentioned in feedback are missing from this group:** {names_str}")
                            with c_w_btn:
                                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
                                st.button(
                                    f"➕ Add Missing ({len(missing_from_group)})",
                                    key=f"add_miss_{group_id}",
                                    on_click=cb_add_missing,
                                    args=(group_id,),
                                    help="Add all missing mentioned names to this group",
                                    use_container_width=True
                                )

                    st.markdown('</div>', unsafe_allow_html=True)

            st.markdown("---")
            if st.button("Generate & Update Comments for Preview ➡️", key="btn_gen_bottom", type="primary", use_container_width=True):
                trigger_parse_comments(sheet)
                st.success(f"Parsed feedback for {len(st.session_state['full_messages'])} members!")

        elif config.mode == "LC":
            st.subheader("📋 Leadership Committee (LC) Individual Mapping")
            st.markdown("In LC mode, columns in the spreadsheet are mapped directly to member names.")

            matched_columns = []
            for col_idx, h in enumerate(headers, 1):
                if h.lower().strip() in all_known_members:
                    matched_columns.append({"Column": f"Col {col_idx}", "Header": h, "Matched Member": h.lower().strip()})

            if matched_columns:
                st.success(f"Found {len(matched_columns)} columns matching member names.")
                st.dataframe(pd.DataFrame(matched_columns), use_container_width=True)

                # Check for directory members without a column in the sheet
                matched_members_set = {col["Matched Member"] for col in matched_columns}
                unmatched_lc = [m for m in all_known_members if m not in matched_members_set]
                if unmatched_lc:
                    st.warning(
                        f"⚠️ **{len(unmatched_lc)} member(s) in `name_list.json` do not have a feedback column in this spreadsheet:** "
                        + ", ".join([f"`{m}`" for m in unmatched_lc])
                    )
            else:
                st.warning("No columns in this spreadsheet directly match member names in name_list.json.")

            if st.button("Generate LC Comments for Preview ➡️", type="primary", use_container_width=True):
                trigger_parse_comments(sheet)
                st.success(f"Parsed LC feedback for {len(st.session_state['full_messages'])} members!")


# =============================================================================
# TAB 4: PREVIEW SAMPLE COMMENTS
# =============================================================================
with tab_preview:
    st.subheader("💬 Step 4: Sample & Comment Preview")
    st.markdown("Review the exact message formatted for each member before dispatching.")

    # Automatically parse if not already parsed or if parsed under a different mode
    mode_changed = st.session_state.get("last_parsed_mode") != config.mode
    if (not st.session_state.get("full_messages") or mode_changed) and "sheet" in st.session_state:
        trigger_parse_comments(st.session_state["sheet"])

    full_msgs = st.session_state.get("full_messages", {})

    if not full_msgs:
        st.warning("No comments generated yet. Please ensure members are assigned in Step 3 and click 'Generate Comments'.")
    else:
        recipients = sorted(list(full_msgs.keys()))

        # Top Metric Cards
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        total_recipients = len(recipients)
        missing_ids = [r for r in recipients if not st.session_state["name_dict"].get(r)]
        avg_len = sum(len(full_msgs[r]) for r in recipients) // max(total_recipients, 1)

        col_m1.metric("Total Recipients", total_recipients)
        col_m2.metric("Slack IDs Configured", f"{total_recipients - len(missing_ids)} / {total_recipients}")
        col_m3.metric("Missing Slack IDs", len(missing_ids), delta_color="inverse")
        col_m4.metric("Avg Message Length", f"{avg_len} chars")

        if missing_ids:
            st.warning(f"⚠️ The following {len(missing_ids)} members have comments but no Slack ID in name_list.json: {', '.join(missing_ids)}. You can add their Slack IDs in Step 1 (Configuration & Roster).")

        st.markdown("---")

        # Interactive Sample Selector
        col_sel, col_rand = st.columns([3, 1])
        with col_sel:
            selected_person = st.selectbox(
                "Select Member to Preview",
                options=recipients,
                index=st.session_state["selected_recipient_idx"] if st.session_state["selected_recipient_idx"] < len(recipients) else 0
            )
            # update index in state
            st.session_state["selected_recipient_idx"] = recipients.index(selected_person)

        with col_rand:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if st.button("🎲 View Random Sample", use_container_width=True):
                rand_idx = random.randint(0, len(recipients) - 1)
                st.session_state["selected_recipient_idx"] = rand_idx
                st.rerun()

        # Recipient Info Banner
        slack_id = st.session_state["name_dict"].get(selected_person)
        st.markdown(
            f"**Recipient:** `{selected_person}` | "
            f"**Slack ID:** `{'✅ ' + slack_id if slack_id else '❌ Missing (cannot deliver)'}` | "
            f"**Message Length:** `{len(full_msgs[selected_person])}` characters"
        )

        col_view1, col_view2 = st.columns([3, 2])

        with col_view1:
            c_pv_head, c_pv_theme = st.columns([3, 1])
            with c_pv_head:
                st.markdown("##### 📱 Slack Direct Message Preview")
            with c_pv_theme:
                preview_theme = st.selectbox("Theme", ["dark", "light"], key="slack_theme_sel", label_visibility="collapsed")
            msg_text = full_msgs[selected_person]
            slack_html = bot_logic.render_slack_dm_html(
                "ST SlackBot", selected_person, slack_id, msg_text, theme=preview_theme
            )
            st.markdown(slack_html, unsafe_allow_html=True)

        with col_view2:
            st.markdown("##### 📝 Raw Text (Slack Markdown Payload)")
            st.text_area(
                "Raw API Payload",
                value=msg_text,
                height=350,
                disabled=True,
                label_visibility="collapsed"
            )

        # Breakdown Accordion
        with st.expander(f"🔍 Inspect Section-by-Section Breakdown for {selected_person}", expanded=False):
            sections = st.session_state["parsed_comments"].get(selected_person, {})
            if config.mode == "PD" and isinstance(sections, dict):
                for s_name, s_content in sections.items():
                    st.markdown(f"**Section: {s_name}**")
                    st.code(s_content if s_content.strip() else "(Empty)", language=None)
            elif isinstance(sections, str):
                st.code(sections if sections.strip() else "(Empty)", language=None)
            elif isinstance(sections, dict):
                for s_name, s_content in sections.items():
                    st.markdown(f"**Section: {s_name}**")
                    st.code(s_content if str(s_content).strip() else "(Empty)", language=None)

        st.markdown("---")

        # Full Audit Expander
        with st.expander(f"📋 Audit All {len(recipients)} Recipients at Once", expanded=False):
            search_query = st.text_input("Filter members:", placeholder="Type to filter...")
            filtered_recipients = [r for r in recipients if search_query.lower() in r.lower()] if search_query else recipients
            for r in filtered_recipients:
                r_slack = st.session_state["name_dict"].get(r, "Missing ID")
                st.markdown(f"**@{r}** (`{r_slack}`)")
                st.text_area(f"msg_{r}", value=full_msgs[r], height=120, disabled=True, label_visibility="collapsed")


# =============================================================================
# TAB 5: REVIEW & SEND
# =============================================================================
with tab_send:
    st.subheader("🚀 Step 5: Review & Dispatch Messages to Slack")
    st.markdown("Send verified personal feedback directly to members via the Slack Bot.")

    full_msgs = st.session_state.get("full_messages", {})
    if not full_msgs:
        st.warning("No comments ready to send. Please configure groups in Step 3 and preview in Step 4.")
    else:
        recipients = sorted(list(full_msgs.keys()))

        # Recipient Selection Checklist
        st.markdown("##### 1. Select Recipients to Include")

        # Table with checkboxes
        select_all = st.checkbox("Select All Recipients", value=True)

        recipient_status = []
        for r in recipients:
            sid = st.session_state["name_dict"].get(r, "")
            status = "Ready ✅" if sid else "Missing Slack ID ❌"
            recipient_status.append({
                "Send": select_all and bool(sid),
                "Member": r,
                "Slack ID": sid or "MISSING",
                "Status": status,
                "Char Count": len(full_msgs[r])
            })

        df_recipients = pd.DataFrame(recipient_status)
        edited_recipients = st.data_editor(
            df_recipients,
            column_config={
                "Send": st.column_config.CheckboxColumn("Include?", default=True),
                "Member": st.column_config.TextColumn("Member", disabled=True),
                "Slack ID": st.column_config.TextColumn("Slack User ID", disabled=True),
                "Status": st.column_config.TextColumn("Readiness", disabled=True),
                "Char Count": st.column_config.NumberColumn("Length", disabled=True)
            },
            hide_index=True,
            use_container_width=True
        )

        selected_rows = edited_recipients[edited_recipients["Send"] == True]
        confirmed_recipients = selected_rows["Member"].tolist()

        st.markdown(f"**Recipients selected for dispatch:** `{len(confirmed_recipients)}` of `{len(recipients)}`")

        # Safety Check / Test Send
        st.markdown("---")
        st.markdown("##### 2. Optional: Send Test Message First")
        test_col1, test_col2 = st.columns([3, 1])
        with test_col1:
            test_slack_id = st.text_input(
                "Test Slack User ID or Channel (e.g. your Slack ID)",
                value=st.session_state["name_dict"].get(recipients[0], ""),
                placeholder="U0XXXXXXXXX"
            )
        with test_col2:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if st.button("🧪 Send Single Test Message", use_container_width=True):
                if not test_slack_id:
                    st.error("Please enter a Slack User ID for testing.")
                else:
                    sample_msg = full_msgs[recipients[0]]
                    with st.spinner("Sending test message..."):
                        active_tok = get_active_token()
                        ok, res = bot_logic.send_slack_message(
                            active_tok, config.slack_api_url, test_slack_id, sample_msg
                        )
                        if ok:
                            st.success(f"Test message sent successfully! (ts: {res})")
                        else:
                            st.error(f"Failed to send test message: {res}")

        # Bulk Send Section
        st.markdown("---")
        st.markdown("##### 3. Broadcast Feedback Messages")

        confirm_checkbox = st.checkbox(
            f"I have reviewed the sample comments and confirm sending to all {len(confirmed_recipients)} selected members.",
            value=False
        )

        if st.button(
            f"🚀 Send Slack Messages to {len(confirmed_recipients)} Members",
            type="primary",
            disabled=not confirm_checkbox or len(confirmed_recipients) == 0,
            use_container_width=True
        ):
            progress_bar = st.progress(0)
            status_text = st.empty()
            log_container = st.container()

            success_count = 0
            fail_count = 0
            active_tok = get_active_token()

            with log_container:
                for idx, person in enumerate(confirmed_recipients):
                    slack_id = st.session_state["name_dict"].get(person)
                    msg_body = full_msgs[person]

                    status_text.text(f"Sending ({idx + 1}/{len(confirmed_recipients)}): @{person}...")

                    if not slack_id:
                        st.write(f"❌ **@{person}**: Skipped - missing Slack ID")
                        fail_count += 1
                        continue

                    ok, res = bot_logic.send_slack_message(
                        active_tok, config.slack_api_url, slack_id, msg_body
                    )

                    if ok:
                        st.write(f"✅ **@{person}** (`{slack_id}`): Delivered")
                        success_count += 1
                    else:
                        st.write(f"❌ **@{person}** (`{slack_id}`): Failed - {res}")
                        fail_count += 1

                    progress_bar.progress((idx + 1) / len(confirmed_recipients))

            status_text.text("Finished!")
            if success_count > 0 and fail_count == 0:
                st.success(f"🎉 Successfully delivered feedback to all {success_count} members!")
            else:
                st.warning(f"Completed with {success_count} successes and {fail_count} failures. See log above.")
