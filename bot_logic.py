import os
import json
import time
import io
import html
import requests
from collections import defaultdict
from openpyxl import load_workbook


def load_name_list(filepath):
    """Load member name-to-slack-id mapping from JSON file."""
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_name_list(name_dict, filepath):
    """Save member name-to-slack-id mapping to JSON file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(name_dict, f, indent=4)


def get_available_spreadsheets(folder="spreadsheets"):
    """Get list of .xlsx files in the specified folder."""
    if not os.path.exists(folder):
        return []
    files = [f for f in os.listdir(folder) if f.endswith('.xlsx') and not f.startswith('~$')]
    files.sort()
    return files


def load_workbook_and_sheet(file_source, sheet_name=None):
    """
    Load workbook from filepath or file-like buffer.
    Returns (workbook, sheet, sheet_names).
    """
    if isinstance(file_source, (str, os.PathLike)):
        wb = load_workbook(file_source, data_only=True)
    elif hasattr(file_source, 'read'):
        # In-memory buffer or UploadedFile
        file_bytes = io.BytesIO(file_source.read())
        wb = load_workbook(file_bytes, data_only=True)
    else:
        wb = load_workbook(file_source, data_only=True)

    sheet_names = wb.sheetnames
    if sheet_name and sheet_name in sheet_names:
        sheet = wb[sheet_name]
    elif 'Form Responses 1' in sheet_names:
        sheet = wb['Form Responses 1']
    else:
        sheet = wb.active

    return wb, sheet, sheet_names


def get_sheet_headers(sheet):
    """Get row 1 values as a list of strings."""
    row_iter = sheet.iter_rows(min_row=1, max_row=1, values_only=True)
    try:
        first_row = next(row_iter)
        return [str(cell).strip() if cell is not None else "" for cell in first_row]
    except StopIteration:
        return []


def detect_spreadsheet_mode(headers, known_members, search_terms):
    """
    Automatically detects whether a spreadsheet is 'LC' or 'PD' mode based on headers.
    Returns:
    - detected_mode: "LC" or "PD"
    - reason: explanation string
    - details: dict with counts and matching columns
    """
    known_set = {m.strip().lower() for m in known_members if m.strip()}
    lc_matches = [h for h in headers if h and h.strip().lower() in known_set]
    pd_matches = [h for h in headers if h and any(t.lower() in h.lower() for t in search_terms)]

    if len(lc_matches) >= 3 and len(lc_matches) > len(pd_matches):
        mode = "LC"
        reason = f"Detected {len(lc_matches)} individual member columns matching name list."
    elif len(pd_matches) > 0:
        mode = "PD"
        reason = f"Detected {len(pd_matches)} group/performance feedback columns matching search terms."
    else:
        if len(lc_matches) > 0:
            mode = "LC"
            reason = f"Found {len(lc_matches)} member column match(es)."
        else:
            mode = "PD"
            reason = "Defaulted to PD mode (no clear member columns found)."

    return mode, reason, {"lc_matches": lc_matches, "pd_matches": pd_matches}


import re

STOP_WORDS = {
    'group', 'individual', 'feedback', 'comments', 'please', 'include', 'write',
    'who', 'the', 'comment', 'is', 'for', 'run', 'their', 'name', 'notes', 'and', 'with'
}


def _extract_header_tokens(text):
    clean = re.sub(r'[^\w\s]', ' ', str(text).lower())
    return {w for w in clean.split() if w not in STOP_WORDS}


def detect_groups_pd(headers, search_terms):
    """
    Identify potential group columns and intelligently paired individual columns in PD mode.
    Handles any number of groups (2, 3, 4, 5, 6, etc.) and standalone group columns.
    """
    group_cols = []
    indiv_cols = []

    for idx, header in enumerate(headers):
        if not header:
            continue
        col_number = idx + 1
        h_lower = header.lower()
        if "individual" in h_lower:
            indiv_cols.append({
                "col": col_number,
                "name": header,
                "tokens": _extract_header_tokens(header)
            })
        elif any(term.lower() in h_lower for term in search_terms):
            group_cols.append({
                "col": col_number,
                "name": header,
                "tokens": _extract_header_tokens(header)
            })

    paired_groups = []
    used_indiv_cols = set()

    for g in group_cols:
        best_indiv = None
        best_score = 0
        for i in indiv_cols:
            if i["col"] in used_indiv_cols:
                continue
            overlap = len(g["tokens"] & i["tokens"])
            score = overlap
            # If immediately adjacent and has common tokens or indiv follows immediately
            if i["col"] == g["col"] + 1 and overlap > 0:
                score += 2
            elif i["col"] == g["col"] + 1 and len(g["tokens"]) == 0:
                score += 1

            if score > best_score:
                best_score = score
                best_indiv = i

        if best_indiv and best_score > 0:
            used_indiv_cols.add(best_indiv["col"])
            paired_groups.append({
                "group_name": g["name"],
                "group_col": g["col"],
                "indiv_name": best_indiv["name"],
                "indiv_col": best_indiv["col"],
            })
        else:
            paired_groups.append({
                "group_name": g["name"],
                "group_col": g["col"],
                "indiv_name": None,
                "indiv_col": None,
            })

    return paired_groups, group_cols, indiv_cols


def auto_detect_members_for_group(sheet, indiv_col_idx, known_members, group_name=""):
    """
    Scans the individual feedback column and group header for mentions of known members.
    """
    found_members = set()

    # Check group name itself (e.g. 'Arashi: Frederick & Yuka')
    if group_name:
        for m in known_members:
            if re.search(r'\b' + re.escape(m.lower()) + r'\b', group_name.lower()):
                found_members.add(m.lower())

    # Check individual comments column
    if indiv_col_idx:
        for row in range(2, sheet.max_row + 1):
            cell_val = sheet.cell(row=row, column=indiv_col_idx).value
            if not cell_val:
                continue
            text = str(cell_val).lower()
            for member in known_members:
                if member.lower() in text:
                    found_members.add(member.lower())

    # Return in order of known_members
    return [m for m in known_members if m.lower() in found_members]


def parse_pd_comments(sheet, group_configs):
    """
    Parses PD mode comments from sheet using the group configurations.
    group_configs is a list of dicts:
    [
        {
            "group_name": str,
            "group_col": int or None,
            "indiv_col": int or None,
            "indiv_name": str or None,
            "members": [str, ...]
        }
    ]
    Returns:
    - comments_by_person: dict of dicts {person: {section_name: comment_text}}
    - full_message_by_person: dict {person: formatted_slack_string}
    - group_feedback_cache: dict {group_col: text}
    """
    comments_by_person = defaultdict(dict)
    group_feedback_cache = {}

    for config_item in group_configs:
        g_name = config_item["group_name"]
        g_col = config_item.get("group_col")
        i_col = config_item.get("indiv_col")
        i_name = config_item.get("indiv_name") or f"{g_name} Individual"
        members = [m.lower().strip() for m in config_item.get("members", []) if m.strip()]

        # 1. Extract group feedback
        group_text = ""
        if g_col:
            if g_col not in group_feedback_cache:
                g_comments = ""
                for r in range(2, sheet.max_row + 1):
                    val = sheet.cell(row=r, column=g_col).value
                    if val is not None and str(val).strip():
                        g_comments += str(val).strip() + "\n"
                group_feedback_cache[g_col] = g_comments
            group_text = group_feedback_cache.get(g_col, "")

        # 2. Extract individual lines
        indiv_lines = []
        if i_col:
            for r in range(2, sheet.max_row + 1):
                val = sheet.cell(row=r, column=i_col).value
                if val is not None and str(val).strip():
                    indiv_lines.extend(str(val).strip().split("\n"))

        # 3. Assign to members
        for person in members:
            # Add group comments if present
            if group_text and group_text.strip():
                comments_by_person[person][g_name] = group_text

            # Filter individual comments if present
            if indiv_lines and i_col:
                person_indiv = [line.strip() for line in indiv_lines if person in line.lower() and line.strip()]
                indiv_text = "\n".join(person_indiv)
                if indiv_text:
                    comments_by_person[person][i_name] = indiv_text

    # Format full messages
    full_message_by_person = {}
    for person, sections in comments_by_person.items():
        full_message_by_person[person] = format_pd_message(sections)

    return comments_by_person, full_message_by_person


def format_pd_message(sections):
    """
    Format PD sections into the exact Slack message format:
    *Section Name*
    comments
    -----------------------
    """
    whole_comment = ""
    for section_name, text in sections.items():
        clean_text = text.strip() if text else ""
        if clean_text:
            whole_comment += f"*{section_name}*\n{clean_text}\n-----------------------\n"
    return whole_comment.strip()


def parse_lc_comments(sheet, person_list):
    """
    Parses LC mode comments from sheet where column headers match person names.
    Returns:
    - comments_by_person: dict {person: comments_string}
    - full_message_by_person: dict {person: formatted_slack_string}
    """
    headers = get_sheet_headers(sheet)
    comments_by_person = {}
    normalized_persons = {p.lower().strip(): p for p in person_list}

    for col_idx, header in enumerate(headers, 1):
        header_lower = header.lower().strip()
        if header_lower in normalized_persons:
            person_key = header_lower
            col_comments = []
            for r in range(2, sheet.max_row + 1):
                val = sheet.cell(row=r, column=col_idx).value
                if val is not None and str(val).strip():
                    col_comments.append(str(val).strip())
            if col_comments:
                joined = "\n______________________________\n".join(col_comments)
                comments_by_person[person_key] = joined

    full_message_by_person = {}
    for person, comments in comments_by_person.items():
        full_message_by_person[person] = format_lc_message(comments)

    return comments_by_person, full_message_by_person


def format_lc_message(comments):
    """
    Format LC comments into Slack message format:
    *Personal Feedback*
    ‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾
    <comments>
    """
    clean_text = comments.strip() if comments else ""
    return f"*Personal Feedback*\n‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\n{clean_text}\n"


def render_slack_dm_html(sender_name, recipient_name, recipient_id, message_text, theme="dark"):
    """
    Renders an authentic, pixel-accurate Slack Direct Message HTML component.
    Converts Slack markdown (*bold*, _italic_, dividers) into styled HTML elements.
    """
    bg_color = "#1a1d21" if theme == "dark" else "#ffffff"
    text_color = "#d1d2d3" if theme == "dark" else "#1d1c1d"
    border_color = "#35373b" if theme == "dark" else "#e2e8f0"
    header_bg = "#222529" if theme == "dark" else "#f8fafc"
    meta_color = "#abacad" if theme == "dark" else "#616061"
    badge_bg = "#2e343b" if theme == "dark" else "#e8e8e8"
    badge_color = "#d1d2d3" if theme == "dark" else "#616061"
    hr_color = "#383f45" if theme == "dark" else "#e2e8f0"

    escaped = html.escape(message_text.strip())

    # Replace horizontal divider lines (---, ‾‾‾, ___)
    escaped = re.sub(
        r'^[ \t]*[-_‾—]{3,}[ \t]*$',
        f'<div style="height: 1px; background-color: {hr_color}; margin: 12px 0;"></div>',
        escaped,
        flags=re.MULTILINE
    )

    # Replace *bold* Slack syntax
    bold_color = "#ffffff" if theme == "dark" else "#000000"
    escaped = re.sub(r'(?<!\w)\*([^\*\n]+)\*(?!\w)', rf'<strong style="color: {bold_color}; font-weight: 700;">\1</strong>', escaped)

    # Replace _italic_ Slack syntax
    escaped = re.sub(r'(?<!\w)_([^_\n]+)_(?!\w)', r'<em>\1</em>', escaped)

    # Line breaks
    escaped = escaped.replace('\n', '<br>')

    time_str = time.strftime("%I:%M %p")

    return f'''
    <div style="background-color: {bg_color}; border: 1px solid {border_color}; border-radius: 8px; margin-bottom: 12px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; overflow: hidden; box-shadow: 0 2px 6px rgba(0,0,0,0.12);">
        <div style="background-color: {header_bg}; padding: 8px 14px; border-bottom: 1px solid {border_color}; display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: {meta_color};">
            <div style="display: flex; align-items: center; gap: 6px;">
                <span>🔒</span>
                <span>Direct Message from <strong>{sender_name}</strong></span>
            </div>
            <div>
                To: <span style="font-weight: 600; color: {'#38bdf8' if theme == 'dark' else '#0284c7'};">@{recipient_name}</span> ({recipient_id or 'NO_SLACK_ID'})
            </div>
        </div>
        <div style="padding: 16px; display: flex; align-items: flex-start; gap: 12px;">
            <div style="width: 40px; height: 40px; border-radius: 8px; background: linear-gradient(135deg, #4a154b, #611f69); display: flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0; box-shadow: 0 1px 3px rgba(0,0,0,0.2);">
                🥁
            </div>
            <div style="flex-grow: 1; min-width: 0;">
                <div style="display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px;">
                    <span style="font-weight: 900; font-size: 15px; color: {'#ffffff' if theme == 'dark' else '#1d1c1d'};">{sender_name}</span>
                    <span style="background: {badge_bg}; color: {badge_color}; font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 3px;">APP</span>
                    <span style="font-size: 12px; color: {meta_color};">Today at {time_str}</span>
                </div>
                <div style="font-size: 14.5px; line-height: 1.55; color: {text_color}; word-break: break-word;">
                    {escaped}
                </div>
            </div>
        </div>
    </div>
    '''


def test_slack_token(token, api_url="https://slack.com/api/"):
    """
    Verify Slack bot token using auth.test endpoint.
    Returns (ok: bool, details: dict or str).
    """
    if not token:
        return False, "Slack token is missing."

    headers = {
        'Authorization': f'Bearer {token.strip()}',
        'Content-Type': 'application/json; charset=utf-8'
    }
    url = f"{api_url.rstrip('/')}/auth.test"

    try:
        resp = requests.post(url, headers=headers, timeout=8)
        data = resp.json()
        if data.get("ok"):
            return True, {
                "user": data.get("user", "Unknown"),
                "user_id": data.get("user_id", ""),
                "team": data.get("team", ""),
                "team_id": data.get("team_id", "")
            }
        else:
            return False, data.get("error", "Unknown Slack API error")
    except Exception as e:
        return False, str(e)


def send_slack_message(token, api_url, user_id, message_text, max_retries=3):
    """
    Sends message to a Slack user with exponential backoff.
    Returns (ok: bool, message_or_error: str).
    """
    if not token:
        return False, "Slack token is not set."
    if not user_id:
        return False, "User ID is empty."
    if not message_text:
        return False, "Message text is empty."

    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'Authorization': f'Bearer {token.strip()}'
    }
    payload = {
        'channel': user_id,
        'text': message_text
    }
    url = f"{api_url.rstrip('/')}/chat.postMessage"

    result = {}
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            result = resp.json()
            if result.get('ok'):
                return True, result.get('ts', 'ok')

            error = result.get('error', 'unknown_error')
            if error in ('invalid_auth', 'channel_not_found', 'user_not_found', 'not_in_channel', 'account_inactive'):
                return False, f"Fatal Slack error: {error}"

        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                return False, f"Network error after {max_retries} attempts: {e}"
        except Exception as e:
            return False, f"Unexpected error: {e}"

        wait_time = 2 ** attempt
        time.sleep(wait_time)

    return False, f"Failed after {max_retries} attempts: {result.get('error', 'Unknown Error')}"
