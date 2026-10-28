import os
import json
import time
import random
import importlib
from collections import defaultdict
import streamlit as st
import pandas as pd
from pathlib import Path

import config
import bot_logic
import auth

# Force reload helper modules so Streamlit Cloud picks up newly added functions without stale cache
try:
    importlib.reload(config)
    importlib.reload(bot_logic)
    importlib.reload(auth)
except Exception:
    pass


def safe_parse_name_list_json(raw_content) -> dict:
    """Parse name list JSON via bot_logic with defensive local fallback."""
    if hasattr(bot_logic, "parse_name_list_json"):
        return bot_logic.parse_name_list_json(raw_content)

    if isinstance(raw_content, (bytes, bytearray)):
        raw_content = raw_content.decode("utf-8")
    data = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
    result = {}
    if isinstance(data, dict):
        items = data.get("members") or data.get("users") or data.get("roster")
        if not items:
            for k, v in data.items():
                if isinstance(v, str):
                    result[str(k).strip().lower()] = v.strip()
                elif isinstance(v, dict):
                    sid = v.get("id") or v.get("slack_id") or ""
                    result[str(k).strip().lower()] = str(sid).strip()
            return result
    elif isinstance(data, list):
        items = data
    else:
        return {}

    for item in items:
        if isinstance(item, dict):
            name = item.get("name") or item.get("Name") or item.get("member") or ""
            sid = item.get("slack_id") or item.get("Slack ID") or item.get("id") or ""
            if name:
                result[str(name).strip().lower()] = str(sid).strip()
    return result

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

if "message_header_text" not in st.session_state:
    base = os.path.splitext(os.path.basename(config.form_file))[0] if config.form_file else ""
    st.session_state["message_header_text"] = f"{base}" if base else ""

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

    # Retrieve or derive message header text
    header_title = st.session_state.get("message_header_text")
    if not header_title:
        active_sheet_name = st.session_state.get("active_spreadsheet_name", "")
        base_name = os.path.splitext(os.path.basename(active_sheet_name))[0] if active_sheet_name else ""
        header_title = f"{base_name}" if base_name else ""

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
            comments, msgs = bot_logic.parse_pd_comments(sheet, st.session_state["group_configs"], header_title=header_title)
            st.session_state["parsed_comments"] = comments
            st.session_state["full_messages"] = msgs
            st.session_state["last_parsed_mode"] = "PD"
    elif config.mode == "LC":
        comments, msgs = bot_logic.parse_lc_comments(sheet, name_list, header_title=header_title)
        st.session_state["parsed_comments"] = comments
        st.session_state["full_messages"] = msgs
        st.session_state["last_parsed_mode"] = "LC"


# -----------------------------------------------------------------------------
# User Authentication Screen (Access Gate)
# -----------------------------------------------------------------------------
if not st.session_state.get("authenticated"):
    st.markdown('<div class="main-title">🥁 ST SlackBot</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Feedback sender for (M)(A)(O)PPs & EOQM/EOYM feedback</div>', unsafe_allow_html=True)
    st.markdown("---")

    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        st.markdown("### 🔐 User Login")
        st.caption("Please sign in with your username and password.")

        with st.form("login_form"):
            username_input = st.text_input("Username", placeholder="Enter username")
            password_input = st.text_input("Password", type="password", placeholder="Enter password")
            submit_login = st.form_submit_button("Sign In", type="primary", use_container_width=True)

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
        if st.button("Log Out", key="sidebar_logout", use_container_width=True, type="primary"):
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
        help="PD = Performance Director (Group/Song & Individual notes)\nLC = Logistics Coordinator (EOQM/EOYM messages)"
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
            st.caption(f"⚙️ Matches sheet detection (**{det_m} Mode**)")
        else:
            st.caption(f"⚠️ Manually overridden from sheet's detected **{det_m} Mode**")

    if config.mode == "PD":
        st.info("**PD Mode Active**\n| Parses practice feedback grouped by songs/ensembles and filters individual comments.")
    else:
        st.info("**LC Mode Active**\n| Parses personal feedback columns directly mapped to individual member names.")

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
col_title, col_badge = st.columns([3, 1])
with col_title:
    st.markdown('<div class="main-title">ST SlackBot v2</div>', unsafe_allow_html=True)
    u_label = st.session_state.get("user_label", "Admin")
    st.markdown(f'<div class="sub-title">Session: **@{u_label}** • Active: `{config.mode} Mode`</div>', unsafe_allow_html=True)

with col_badge:
    mode_badge_html = f'<div style="text-align: right; margin-top: 15px;"><span class="{"badge-pd" if config.mode == "PD" else "badge-lc"}">{config.mode} MODE</span></div>'
    st.markdown(mode_badge_html, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Main Navigation Tabs (Streamlined 4-Step Flow)
# -----------------------------------------------------------------------------
tab_groups_label = "👥 2. Review Groups" if config.mode == "PD" else "📋 2. Review Member Columns"

tab_setup, tab_groups, tab_preview, tab_send = st.tabs([
    "📂 1. Setup & Spreadsheet",
    tab_groups_label,
    "💬 3. Review Comments",
    "🚀 4. Send Comments"
])


# =============================================================================
# TAB 1: SETUP & SPREADSHEET (Combined Roster, Spreadsheet & Auto Mode Detection)
# =============================================================================
with tab_setup:
    st.subheader("📂 Step 1: Setup & Spreadsheet Selection")
    st.caption("Manage member Slack IDs, load your performance feedback spreadsheet, and confirm auto-detected modes.")

    col_roster, col_sheet = st.columns(2)

    # -------------------------------------------------------------------------
    # Card 1: Member Roster & Directory
    # -------------------------------------------------------------------------
    with col_roster:
        st.markdown("##### 👥 Member Roster & Slack IDs")
        source_label = st.session_state.get("name_list_source", config.name_filepath)
        num_members = len(st.session_state["name_dict"])
        st.info(f"**{num_members} members loaded** • Source: `{source_label}`")

        c_rf1, c_rf2, c_rf3 = st.columns(3)
        with c_rf1:
            if st.button("🏷️ Fetch Slack IDs", use_container_width=True, help="Queries Slack API users.list via users:read to populate members & IDs"):
                active_tok = get_active_token()
                with st.spinner("Fetching members from Slack..."):
                    ok, res = bot_logic.fetch_slack_users(active_tok, config.slack_api_url)
                    if not ok:
                        st.error(res)
                    else:
                        existing_id_to_name = {v: k for k, v in st.session_state["name_dict"].items() if v}
                        new_dict = {}
                        slack_meta = dict(st.session_state.get("slack_user_meta", {}))
                        for m in res:
                            uid = m["id"]
                            assigned_name = existing_id_to_name.get(uid, m["suggested_name"])
                            if assigned_name in new_dict and new_dict[assigned_name] != uid:
                                assigned_name = m["username"].lower()
                            new_dict[assigned_name] = uid
                            slack_meta[uid] = f"{m['real_name']} (@{m['username']})" if m['real_name'] else f"@{m['username']}"

                        st.session_state["name_dict"] = new_dict
                        st.session_state["slack_user_meta"] = slack_meta
                        st.session_state["name_list_source"] = "Slack Workspace API (users.list)"
                        st.toast(f"Fetched {len(res)} members from Slack!", icon="🤖")
                        st.rerun()

        with c_rf2:
            with st.popover("📁 Import JSON", use_container_width=True):
                st.markdown("###### Upload Member Roster JSON")
                uploaded_name_file = st.file_uploader(
                    "Upload .json file",
                    type=["json"],
                    key="pop_upload_name_file",
                    help="Upload a name_list.json file"
                )
                if uploaded_name_file is not None:
                    name_sig = f"{uploaded_name_file.name}_{uploaded_name_file.size}"
                    if st.session_state.get("last_uploaded_name_sig") != name_sig:
                        try:
                            parsed_dict = safe_parse_name_list_json(uploaded_name_file.getvalue())
                            if parsed_dict:
                                st.session_state["name_dict"] = parsed_dict
                                st.session_state["name_list_source"] = uploaded_name_file.name
                                st.session_state["last_uploaded_name_sig"] = name_sig
                                bot_logic.save_name_list(parsed_dict, config.name_filepath)
                                st.toast(f"Imported {len(parsed_dict)} members!", icon="📥")
                                st.rerun()
                            else:
                                st.error("No valid members found in JSON.")
                        except Exception as e:
                            st.error(f"Error parsing JSON: {e}")

        with c_rf3:
            json_export = json.dumps(st.session_state["name_dict"], indent=2)
            st.download_button(
                "📥 Export JSON",
                data=json_export,
                file_name="name_list.json",
                mime="application/json",
                use_container_width=True,
                help="Download the online copy of name_list.json"
            )

        with st.expander("📝 View & Edit Member Names & Slack IDs", expanded=False):
            st.caption("Double-click any name in **Spreadsheet Name** to match performance form headers:")
            slack_meta_cache = st.session_state.get("slack_user_meta", {})
            name_records = []
            for k, v in st.session_state["name_dict"].items():
                rec = {
                    "Spreadsheet Name": k,
                    "Slack ID": v,
                }
                if v in slack_meta_cache:
                    rec["Slack Profile Info"] = slack_meta_cache[v]
                name_records.append(rec)

            df_names = pd.DataFrame(name_records)
            col_config = {
                "Spreadsheet Name": st.column_config.TextColumn("Spreadsheet Name", required=True),
                "Slack ID": st.column_config.TextColumn("Slack User ID", required=True),
            }
            if "Slack Profile Info" in df_names.columns:
                col_config["Slack Profile Info"] = st.column_config.TextColumn("Slack Profile", disabled=True)

            edited_df = st.data_editor(
                df_names,
                num_rows="dynamic",
                use_container_width=True,
                column_config=col_config,
                key="setup_roster_editor"
            )

            c_save_r, c_rel_r = st.columns([2, 1])
            with c_save_r:
                if st.button("💾 Save Directory Changes", type="secondary", use_container_width=True):
                    updated_dict = {}
                    for _, row in edited_df.iterrows():
                        name_val = str(row.get("Spreadsheet Name", "")).strip().lower() if pd.notna(row.get("Spreadsheet Name")) else ""
                        id_val = str(row.get("Slack ID", "")).strip() if pd.notna(row.get("Slack ID")) else ""
                        if name_val:
                            updated_dict[name_val] = id_val
                    st.session_state["name_dict"] = updated_dict
                    bot_logic.save_name_list(updated_dict, config.name_filepath)
                    st.toast(f"Saved {len(updated_dict)} members!", icon="💾")
                    st.rerun()
            with c_rel_r:
                if st.button("🔄 Reload File", use_container_width=True):
                    refresh_name_list()
                    st.rerun()

    # -------------------------------------------------------------------------
    # Card 2: Spreadsheet Selection & Auto Mode Detection
    # -------------------------------------------------------------------------
    with col_sheet:
        st.markdown("##### 📁 Spreadsheet (.xlsx)")
        existing_files = bot_logic.get_available_spreadsheets(config.spreadsheet_folder)
        sheet_source = None
        loaded_file_label = ""

        c_src_type = st.radio("Spreadsheet Selection Mode", ["Existing from folder", "Upload new (.xlsx)"], horizontal=True, label_visibility="collapsed")
        if c_src_type == "Existing from folder":
            if existing_files:
                default_idx = existing_files.index(config.form_file) if config.form_file in existing_files else 0
                selected_file = st.selectbox("Select file", existing_files, index=default_idx, label_visibility="collapsed")
                if selected_file:
                    sheet_source = os.path.join(config.spreadsheet_folder, selected_file)
                    loaded_file_label = selected_file
                    st.session_state["active_spreadsheet_name"] = selected_file
            else:
                st.caption(f"No spreadsheets found in `{config.spreadsheet_folder}/`.")
        else:
            uploaded_file = st.file_uploader("Upload Excel spreadsheet (.xlsx)", type=["xlsx"], key="setup_uploader_file", label_visibility="collapsed")
            if uploaded_file is not None:
                sheet_source = uploaded_file
                loaded_file_label = uploaded_file.name
                st.session_state["active_spreadsheet_name"] = uploaded_file.name
                save_path = os.path.join(config.spreadsheet_folder, uploaded_file.name)
                os.makedirs(config.spreadsheet_folder, exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

        if sheet_source is not None:
            try:
                wb, sheet, sheet_names = bot_logic.load_workbook_and_sheet(sheet_source)
                st.session_state["wb"] = wb
                st.session_state["sheet"] = sheet

                if len(sheet_names) > 1:
                    selected_sheet_name = st.selectbox("Worksheet", sheet_names, index=sheet_names.index(sheet.title) if sheet.title in sheet_names else 0)
                    if selected_sheet_name != sheet.title:
                        sheet = wb[selected_sheet_name]
                        st.session_state["sheet"] = sheet

                headers = bot_logic.get_sheet_headers(sheet)
                st.session_state["headers"] = headers

                # Auto-detection
                all_known = list(st.session_state["name_dict"].keys())
                detected_mode, detect_reason, _ = bot_logic.detect_spreadsheet_mode(
                    headers, all_known, config.group_search_list, config.indiv_search_list
                )
                st.session_state["detected_mode"] = detected_mode
                st.session_state["detected_reason"] = detect_reason

                # When a new spreadsheet is loaded, reset group assignments
                if st.session_state.get("last_loaded_file") != loaded_file_label:
                    st.session_state["last_loaded_file"] = loaded_file_label
                    base_name = os.path.splitext(loaded_file_label)[0]
                    default_title = f"{base_name}"
                    st.session_state["message_header_text"] = default_title
                    st.session_state["input_message_header"] = default_title
                    clear_group_gui_state()
                    if config.mode != detected_mode:
                        config.mode = detected_mode
                        cfg = config.load_config()
                        cfg["mode"] = detected_mode
                        config.save_config(cfg)
                    if config.mode == "PD":
                        paired, _, _ = bot_logic.detect_groups_pd(
                            headers, config.group_search_list, config.indiv_search_list
                        )
                        st.session_state["group_configs"] = [
                            {
                                "id": f"grp_{i}_{int(time.time()*1000)}",
                                "group_name": p["group_name"],
                                "group_col": p["group_col"],
                                "indiv_name": p["indiv_name"],
                                "indiv_col": p["indiv_col"],
                                "members": []
                            }
                            for i, p in enumerate(paired)
                        ]
                    st.toast(f"Loaded {loaded_file_label} ({detected_mode} Mode)", icon="📄")
                    st.rerun()

                # Mode & Status Indicator
                c_det_banner, c_det_toggle = st.columns([3, 1])
                with c_det_banner:
                    if config.mode == detected_mode:
                        st.success(f"🤖 **Auto-detected: {detected_mode} Mode** — {detect_reason}")
                    else:
                        st.warning(f"⚠️ **Override Active:** Using **{config.mode} Mode** (Sheet format was detected as {detected_mode})")
                with c_det_toggle:
                    other_mode = "LC" if config.mode == "PD" else "PD"
                    if st.button(f"Switch to {other_mode}", use_container_width=True):
                        config.mode = other_mode
                        cfg = config.load_config()
                        cfg["mode"] = other_mode
                        config.save_config(cfg)
                        clear_group_gui_state()
                        st.rerun()

                # Message Header Banner
                current_header = st.session_state.get("message_header_text", "")
                if not current_header:
                    current_header = f"Feedback: {os.path.splitext(loaded_file_label)[0]}"
                    st.session_state["message_header_text"] = current_header

                new_header = st.text_input(
                    "📝 Message Header Banner",
                    value=current_header,
                    key="input_message_header",
                    help="Appears at the very top of each member's Slack message"
                )
                if new_header != st.session_state.get("message_header_text"):
                    st.session_state["message_header_text"] = new_header
                    if st.session_state.get("full_messages"):
                        trigger_parse_comments(sheet)
                    st.rerun()

                st.caption("Live Header Preview:")
                p_block = bot_logic.build_header_block(st.session_state.get("message_header_text", ""))
                if p_block:
                    st.code(p_block.rstrip(), language="markdown")

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
            st.info("Select or upload an Excel spreadsheet above to begin.")

    # -------------------------------------------------------------------------
    # Collapsible Advanced / Optional Settings (Slack Token, Config, Keywords)
    # -------------------------------------------------------------------------
    st.markdown("---")
    with st.expander("⚙️ Optional Settings (Slack Bot Token, Config & Keywords)", expanded=False):
        c_opt1, c_opt2 = st.columns(2)
        with c_opt1:
            st.markdown("###### 🔌 Slack Bot Token")
            cfg_token = st.text_input(
                "Slack Bot Token (SLACK_BOT_TOKEN)",
                value=get_active_token(),
                type="password",
                help="Bot token starting with xoxb-."
            )
            col_t_save, col_t_test = st.columns(2)
            with col_t_save:
                if st.button("💾 Save Token", use_container_width=True):
                    clean_tok, _ = config.save_token(cfg_token)
                    st.session_state["slack_token"] = clean_tok
                    st.toast("Saved Slack token!", icon="🔌")
            with col_t_test:
                if st.button("🧪 Test Slack Connection", use_container_width=True):
                    with st.spinner("Testing Slack token..."):
                        ok, res = bot_logic.test_slack_token(get_active_token(), config.slack_api_url)
                        if ok:
                            st.success(f"Connected to **{res.get('team')}** as **@{res.get('user')}**!")
                        else:
                            st.error(f"Test failed: {res}")

        with c_opt2:
            st.markdown("###### 🔍 PD Keyword Categories & Config File")
            g_terms_in = st.text_input(
                "Group Column Terms (comma-separated)",
                value=", ".join(config.group_search_list),
                help="Terms identifying group/song feedback columns (e.g. Group, Ensemble, Feedback, Arashi)"
            )
            i_terms_in = st.text_input(
                "Individual Column Terms (comma-separated)",
                value=", ".join(config.indiv_search_list),
                help="Terms identifying individual feedback columns (e.g. Individual, Indiv, Solo)"
            )
            col_k_save, col_cfg_pop = st.columns(2)
            with col_k_save:
                if st.button("💾 Save Keywords", use_container_width=True):
                    up_group = [t.strip() for t in g_terms_in.split(",") if t.strip()]
                    up_indiv = [t.strip() for t in i_terms_in.split(",") if t.strip()]
                    cfg = config.load_config()
                    if "search" not in cfg:
                        cfg["search"] = {}
                    cfg["search"]["group_terms"] = up_group
                    cfg["search"]["indiv_terms"] = up_indiv
                    cfg["search"]["terms"] = up_group + up_indiv
                    config.save_config(cfg)
                    config.group_search_list = up_group
                    config.indiv_search_list = up_indiv
                    config.search_list = up_group + up_indiv
                    st.toast("Saved group & individual keywords!", icon="🔍")
            with col_cfg_pop:
                with st.popover("📄 Import config.json", use_container_width=True):
                    uploaded_cfg = st.file_uploader("Upload config.json", type=["json"], key="pop_cfg_upload")
                    if uploaded_cfg is not None:
                        try:
                            cfg_data = json.loads(uploaded_cfg.getvalue().decode("utf-8"))
                            if isinstance(cfg_data, dict):
                                config.save_config(cfg_data)
                                st.toast("Imported configuration!", icon="⚙️")
                                st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

    # -------------------------------------------------------------------------
    # Primary Action: Parse Spreadsheet & Proceed
    # -------------------------------------------------------------------------
    st.markdown("---")
    if "sheet" in st.session_state:
        sheet = st.session_state["sheet"]
        target_step_title = tab_groups_label.split(".", 1)[1].strip() if "." in tab_groups_label else tab_groups_label
        if st.button(f"⚡ Parse Spreadsheet & Proceed to {target_step_title} ➡️", type="primary", use_container_width=True):
            trigger_parse_comments(sheet)
            st.success(f"✅ Spreadsheet parsed! Switch to **{tab_groups_label}** above to review.")
    else:
        st.info("👈 Please select or upload a spreadsheet above to begin.")


# =============================================================================
# TAB 2: REVIEW GROUPS & MEMBERS
# =============================================================================
with tab_groups:
    if "sheet" not in st.session_state:
        st.warning("Please upload or select a spreadsheet in Step 1 (Setup & Spreadsheet) first.")
    else:
        sheet = st.session_state["sheet"]
        headers = st.session_state.get("headers", bot_logic.get_sheet_headers(sheet))
        all_known_members = sorted(list(st.session_state["name_dict"].keys()))

        if config.mode == "PD":
            st.subheader("👥 Step 2: Review Groups & Member Assignments")
            st.markdown(
                "Configure each group's name, its corresponding group feedback column, "
                "paired individual feedback column, and assign members to each group."
            )

            # Ensure defaults if session state group_configs is empty (strictly empty member lists)
            if not st.session_state["group_configs"]:
                paired, _, _ = bot_logic.detect_groups_pd(
                    headers, config.group_search_list, config.indiv_search_list
                )
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
            btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 2])
            with btn_col1:
                st.button("➕ Add New Group", on_click=cb_add_new_group, args=(len(headers),), use_container_width=True)

            with btn_col2:
                st.button("🪄 Auto-Detect All from Comments", on_click=cb_auto_detect_all, use_container_width=True, help="Scans comments & headers to populate members")

            with btn_col3:
                st.button("🧹 Clear All Groups", on_click=cb_clear_all, use_container_width=True)

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
            with st.expander("📋 View Membership Summary Table", expanded=False):
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
            st.markdown("### 🎛️ Group Configurations & Member Assignment")

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
            if st.button("💬 Generate Comments & Proceed to Preview ➡️", key="btn_gen_bottom", type="primary", use_container_width=True):
                trigger_parse_comments(sheet)
                st.success(f"✅ Parsed feedback for {len(st.session_state['full_messages'])} members! Switch to **💬 3. Review Comments** above to inspect.")

        elif config.mode == "LC":
            st.subheader("📋 Step 2: Review Member Columns (LC Mode)")
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

            if st.button("💬 Generate LC Comments & Proceed to Preview ➡️", type="primary", use_container_width=True):
                trigger_parse_comments(sheet)
                st.success(f"✅ Parsed LC feedback for {len(st.session_state['full_messages'])} members! Switch to **💬 3. Review Comments** above to inspect.")


# =============================================================================
# TAB 3: PREVIEW SAMPLE COMMENTS
# =============================================================================
with tab_preview:
    st.subheader("💬 Step 3: Review Sample Comments")
    st.markdown("Review the exact message formatted for each member before dispatching.")

    # Automatically parse if not already parsed or if parsed under a different mode
    mode_changed = st.session_state.get("last_parsed_mode") != config.mode
    if (not st.session_state.get("full_messages") or mode_changed) and "sheet" in st.session_state:
        trigger_parse_comments(st.session_state["sheet"])

    full_msgs = st.session_state.get("full_messages", {})

    if not full_msgs:
        st.warning("No comments generated yet. Please ensure groups or columns are configured in Step 2 and click 'Generate Comments'.")
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
            st.warning(f"⚠️ The following {len(missing_ids)} members have comments but no Slack ID in name_list.json: {', '.join(missing_ids)}. You can add their Slack IDs in Step 1 (Setup & Spreadsheet).")

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
# TAB 4: SEND COMMENTS TO SLACK
# =============================================================================
with tab_send:
    st.subheader("🚀 Step 4: Send Comments to Slack")
    st.markdown("Send verified personal feedback directly to members via the Slack Bot.")

    full_msgs = st.session_state.get("full_messages", {})
    if not full_msgs:
        st.warning("No comments ready to send. Please configure groups in Step 2 and preview in Step 3.")
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
        st.caption("Send a sample feedback payload directly to **your own Slack ID** or a test channel before broadcasting to everyone.")

        with st.form("test_send_form"):
            t_col_user, t_col_target, t_col_btn = st.columns([2, 3, 2])
            with t_col_user:
                sample_target = st.selectbox(
                    "Sample Feedback Payload:",
                    options=recipients,
                    index=0,
                    help="The generated feedback for this member will be sent as the test payload."
                )
            with t_col_target:
                test_slack_id = st.text_input(
                    "Your Test Slack User ID or Channel ID:",
                    value=st.session_state.get("last_test_slack_id", ""),
                    placeholder="e.g. U0XXXXXXXXX (your Slack ID)",
                    help="Enter YOUR Slack User ID so the test message is only delivered to you."
                )
            with t_col_btn:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                send_test_btn = st.form_submit_button("🧪 Send Test Message", type="secondary", use_container_width=True)

            if send_test_btn:
                clean_target = test_slack_id.strip()
                if not clean_target:
                    st.error("Please enter your Slack User ID or test channel ID to receive the test message.")
                else:
                    st.session_state["last_test_slack_id"] = clean_target
                    sample_msg = full_msgs[sample_target]
                    with st.spinner(f"Sending sample feedback for @{sample_target} to {clean_target}..."):
                        active_tok = get_active_token()
                        ok, res = bot_logic.send_slack_message(
                            active_tok, config.slack_api_url, clean_target, sample_msg
                        )
                        if ok:
                            st.success(f"✅ Test message (sample for **@{sample_target}**) was delivered exclusively to **`{clean_target}`**! (Slack ts: `{res}`)")
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
