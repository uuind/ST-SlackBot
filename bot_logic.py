import os
import re
import json
import time
import io
import html
import requests
from collections import defaultdict
from openpyxl import load_workbook
import config


def load_name_list(filepath):
    """Load member name-to-slack-id mapping from JSON file."""
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_name_list(name_dict, filepath):
    """Save member name-to-slack-id mapping to JSON file. Returns (success: bool)."""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(name_dict, f, indent=4)
        return True
    except OSError:
        return False


def parse_name_list_json(raw_content) -> dict:
    """
    Parse flexible JSON formats into a standardized {name: slack_id} dictionary.
    Supports:
      - Direct dict: {"audrey": "U0123...", "carol": "U0456..."}
      - Object with members list: {"members": [{"name": "audrey", "id": "U0123..."}, ...]}
      - Direct list of dicts: [{"name": "audrey", "slack_id": "U0123..."}, ...]
    """
    if isinstance(raw_content, (bytes, bytearray)):
        raw_content = raw_content.decode("utf-8")
    if isinstance(raw_content, str):
        data = json.loads(raw_content)
    else:
        data = raw_content

    result = {}
    if isinstance(data, dict):
        if "members" in data and isinstance(data["members"], list):
            items = data["members"]
        elif "users" in data and isinstance(data["users"], list):
            items = data["users"]
        elif "roster" in data and isinstance(data["roster"], list):
            items = data["roster"]
        else:
            for k, v in data.items():
                if isinstance(v, str):
                    result[str(k).strip().lower()] = v.strip()
                elif isinstance(v, dict):
                    sid = v.get("id") or v.get("slack_id") or v.get("Slack ID") or ""
                    result[str(k).strip().lower()] = str(sid).strip()
            return result
    elif isinstance(data, list):
        items = data
    else:
        return result

    for item in items:
        if isinstance(item, dict):
            name = (
                item.get("name") or item.get("Name") or item.get("member") or item.get("Member") or item.get("user") or ""
            )
            sid = (
                item.get("slack_id") or item.get("Slack ID") or item.get("id") or item.get("ID") or item.get("user_id") or ""
            )
            if name:
                result[str(name).strip().lower()] = str(sid).strip()

    return result


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


def is_excluded_group_header(header: str, exclude_terms=None) -> bool:
    """
    Returns True if a header is metadata, reviewer identification, instructions,
    or general feedback/questions directed to organizers/directors (PDs, ADs, leadership)
    rather than a song or performance group feedback column.
    """
    h = str(header).lower().strip()
    if not h:
        return True

    # Form submission metadata & reviewer identification
    if h in {"timestamp", "name", "your name"} or h.startswith("timestamp"):
        return True
    if "please sign your name" in h or "this is the end" in h:
        return True

    # Configured excluded terms
    if exclude_terms is None:
        try:
            import config
            exclude_terms = getattr(config, "exclude_search_list", None)
        except Exception:
            exclude_terms = None

    if exclude_terms:
        for term in exclude_terms:
            t = str(term).strip().lower()
            if t and t in h:
                return True

    # General questions / feedback specifically directed to PDs, ADs, leadership, or directors
    pd_ad_patterns = [
        r'\bfor\s+(?:the\s+)?(?:pds?|ads?|pds?/ads?|directors?|leadership)\b',
        r'\bto\s+(?:the\s+)?(?:pds?|ads?|pds?/ads?|directors?|leadership)\b',
        r'\b(?:notes|questions?|comments?|feedback)\s+(?:on\s+mpp\s+)?for\s+(?:the\s+)?pds?',
        r'\bpds?/ads?\b',
        r'\bnotes\s+for\s+pds?\b'
    ]
    for pat in pd_ad_patterns:
        if re.search(pat, h):
            return True

    return False


def detect_job_columns(headers, known_members=None):
    """
    Detects job/role feedback columns in LC-mode Job Feedback forms.
    Expected header formats:
      - 'Artistic Directors (AD): Audrey, Jackson'
      - 'Historian: Jackson, Mika'
      - 'Webmaster: Lue'
    Returns list of dicts with col_idx (1-based), header, role_title, abbrev, holders, display_label.
    """
    known_set = {m.strip().lower() for m in (known_members or []) if m and str(m).strip()}
    pd_skip_terms = {"group", "individual", "indiv", "solo", "feedback", "comments", "notes", "timestamp"}
    job_cols = []

    for col_idx, raw_h in enumerate(headers, 1):
        if not raw_h:
            continue
        h = str(raw_h).strip()
        h_lower = h.lower()

        if not h or h_lower == "timestamp" or ":" not in h:
            continue
        if h.endswith("?") and h.index(":") > len(h) - 10:
            continue

        left, right = h.split(":", 1)
        left_clean = left.strip()
        right_clean = right.strip()
        if not left_clean or not right_clean:
            continue

        # Parse candidate holders on the right side
        holder_tokens = [
            tok.strip() for tok in re.split(r"[,&/]+|\band\b", right_clean, flags=re.IGNORECASE)
            if tok and tok.strip()
        ]
        if not holder_tokens:
            continue

        # Check if right-side tokens match known members or look like short person names
        matched_known = sum(1 for t in holder_tokens if t.lower() in known_set)
        looks_like_names = all(1 <= len(t.split()) <= 2 and t.replace("-", "").replace("'", "").isalpha() for t in holder_tokens)
        left_has_pd_term = any(re.search(r"\b" + re.escape(pt) + r"\b", left_clean.lower()) for pt in pd_skip_terms)

        is_job = False
        if known_set and matched_known >= 1:
            is_job = True
        elif looks_like_names and not left_has_pd_term and len(holder_tokens) <= 8:
            is_job = True

        if not is_job:
            continue

        abbrev_match = re.search(r"\(([^)]+)\)", left_clean)
        abbrev = abbrev_match.group(1).strip() if abbrev_match else ""
        role_title = re.sub(r"\([^)]*\)", "", left_clean).strip()
        display_label = f"{role_title} ({abbrev})" if abbrev else role_title

        job_cols.append({
            "col_idx": col_idx,
            "header": h,
            "role_title": role_title,
            "abbrev": abbrev,
            "holders": holder_tokens,
            "display_label": display_label
        })

    return job_cols


def detect_spreadsheet_mode(headers, known_members, group_terms=None, indiv_terms=None, exclude_terms=None):
    """
    Automatically detects whether a spreadsheet is 'LC' or 'PD' mode based on headers.
    Returns:
    - detected_mode: "LC" or "PD"
    - reason: explanation string
    - details: dict with counts, matching columns, and lc_subtype ("members" or "job_channels")
    """
    if group_terms is None:
        group_terms = ["Group", "Ensemble", "Feedback", "Comments", "Notes", "Arashi", "Three Sizz", "3 Sizzlin"]
    if indiv_terms is None:
        if isinstance(group_terms, list) and any("indiv" in t.lower() or "individual" in t.lower() for t in group_terms):
            indiv_terms = [t for t in group_terms if "indiv" in t.lower() or "individual" in t.lower()]
            group_terms = [t for t in group_terms if "indiv" not in t.lower() and "individual" not in t.lower()]
        else:
            indiv_terms = ["Individual", "Indiv", "Solo"]

    all_pd_terms = list(group_terms) + list(indiv_terms)
    known_set = {m.strip().lower() for m in (known_members or []) if m and str(m).strip()}
    lc_matches = [h for h in headers if h and h.strip().lower() in known_set]
    job_matches = detect_job_columns(headers, known_members=known_members)
    pd_matches = [
        h for h in headers
        if h and not is_excluded_group_header(h, exclude_terms=exclude_terms) and any(t.lower() in h.lower() for t in all_pd_terms)
    ]

    lc_subtype = "members"
    if len(job_matches) >= 3 and len(job_matches) >= len(lc_matches):
        mode = "LC"
        lc_subtype = "job_channels"
        reason = f"Detected {len(job_matches)} job/role columns for channel feedback (Job Channel LC Mode)."
    elif len(lc_matches) >= 3 and len(lc_matches) > len(pd_matches):
        mode = "LC"
        reason = f"Detected {len(lc_matches)} individual member columns matching name list."
    elif len(pd_matches) > 0:
        mode = "PD"
        reason = f"Detected {len(pd_matches)} group/performance feedback columns matching search terms."
    else:
        if len(job_matches) > 0:
            mode = "LC"
            lc_subtype = "job_channels"
            reason = f"Found {len(job_matches)} job/role column match(es)."
        elif len(lc_matches) > 0:
            mode = "LC"
            reason = f"Found {len(lc_matches)} member column match(es)."
        else:
            mode = "PD"
            reason = "Defaulted to PD mode (no clear member columns found)."

    return mode, reason, {
        "lc_matches": lc_matches,
        "pd_matches": pd_matches,
        "job_matches": job_matches,
        "lc_subtype": lc_subtype
    }

STOP_WORDS = {
    'group', 'individual', 'feedback', 'comments', 'please', 'include', 'write',
    'who', 'the', 'comment', 'is', 'for', 'run', 'their', 'name', 'notes', 'and', 'with',
    'no', 'of', 'in', 'on', 'at', 'to', 'a', 'an'
}


def _extract_header_tokens(text):
    clean = re.sub(r'[^\w\s]', ' ', str(text).lower())
    tokens = {w for w in clean.split() if w not in STOP_WORDS}
    words = {w for w in tokens if not w.isdigit()}
    nums = {w for w in tokens if w.isdigit()}
    return words, nums


def detect_groups_pd(headers, group_terms=None, indiv_terms=None, exclude_terms=None):
    """
    Identify potential group columns and intelligently paired individual columns in PD mode.
    Handles any number of groups and standalone group columns without individual counterparts.
    """
    if group_terms is None:
        group_terms = ["Group", "Ensemble", "Feedback", "Comments", "Notes", "Arashi", "Three Sizz", "3 Sizzlin"]
    if indiv_terms is None:
        # Check if caller passed a single combined search_terms list
        if isinstance(group_terms, list) and any("indiv" in t.lower() or "individual" in t.lower() for t in group_terms):
            indiv_terms = [t for t in group_terms if "indiv" in t.lower() or "individual" in t.lower()]
            group_terms = [t for t in group_terms if "indiv" not in t.lower() and "individual" not in t.lower()]
        else:
            indiv_terms = ["Individual", "Indiv", "Solo"]

    group_cols = []
    indiv_cols = []

    for idx, header in enumerate(headers):
        if not header or is_excluded_group_header(header, exclude_terms=exclude_terms):
            continue
        col_number = idx + 1
        h_lower = header.lower()

        is_indiv = any(term.lower() in h_lower for term in indiv_terms)
        is_group = any(term.lower() in h_lower for term in group_terms)

        if is_indiv:
            words, nums = _extract_header_tokens(header)
            indiv_cols.append({
                "col": col_number,
                "name": header,
                "words": words,
                "nums": nums
            })
        elif is_group:
            words, nums = _extract_header_tokens(header)
            group_cols.append({
                "col": col_number,
                "name": header,
                "words": words,
                "nums": nums
            })

    g_col_set = {g["col"] for g in group_cols}

    # Evaluate candidate pairs
    candidate_pairs = []
    for g in group_cols:
        for i in indiv_cols:
            if i["col"] <= g["col"]:
                continue
            # Structural Form Rule: No other group column can intervene between g and i
            intervening = [gc for gc in g_col_set if g["col"] < gc < i["col"]]
            if intervening:
                continue

            word_overlap = len(g["words"] & i["words"])
            num_overlap = len(g["nums"] & i["nums"])
            dist = i["col"] - g["col"]

            score = 0
            # Adjacency bonus (individual question follows group question)
            if dist == 1:
                score += 10
            elif dist == 2:
                score += 5
            else:
                score += 1

            if word_overlap > 0:
                score += word_overlap * 10
            if num_overlap > 0 and word_overlap > 0:
                score += num_overlap * 2

            candidate_pairs.append((score, g["col"], i["col"], g, i))

    # Sort candidates by score descending for optimal global pairing
    candidate_pairs.sort(key=lambda x: x[0], reverse=True)

    paired_dict = {}
    used_indiv = set()
    used_group = set()

    for score, g_col, i_col, g, i in candidate_pairs:
        if g_col not in used_group and i_col not in used_indiv and score > 0:
            paired_dict[g_col] = i
            used_group.add(g_col)
            used_indiv.add(i_col)

    paired_groups = []
    for g in group_cols:
        i = paired_dict.get(g["col"])
        paired_groups.append({
            "group_name": g["name"],
            "group_col": g["col"],
            "indiv_name": i["name"] if i else None,
            "indiv_col": i["col"] if i else None
        })

    return paired_groups, group_cols, indiv_cols


OBJECT_PREPOSITIONS = {
    'to', 'with', 'like', 'as', 'from', 'at', 'near', 'behind', 'beside', 
    'follow', 'following', 'than', 'into', 'on', 'about', 'against', 'after', 
    'bc', 'because', 'between', 'of', 'towards', 'toward', 'alongside', 'under'
}

NAME_ALIASES = {
    'johnathan': 'jonathan',
    'isssaaaaaaa': 'issa',
    'issaaaa': 'issa'
}


def harvest_dynamic_starters(corpus_or_sheet, known_members):
    """
    Dynamically discovers starter/predicate vocabulary from text or openpyxl sheet
    by observing words that immediately follow confirmed member name anchors (e.g.
    at line starts, after punctuation, or with explicit markers like ':', '-', ',', '—').
    """
    starters = set()
    n_set = {m.lower().strip() for m in known_members if m and str(m).strip()}

    # Base grammatical markers that naturally start direct address predicates in English:
    # 2nd-person pronouns and essential auxiliary verbs
    starters.update({
        'u', 'you', 'ur', 'your', 'youre', 'yours', 'yall',
        'can', 'could', 'should', 'would', 'might', 'will',
        'is', 'are', 'was', 'were', 'be', 'am',
        'do', 'dont', 'did', 'have', 'had', 'has',
        'good', 'great', 'nice', 'love', 'loved', 'like', 'liked', 'super', 'solid'
    })

    lines = []
    if hasattr(corpus_or_sheet, "iter_rows"):
        for row in corpus_or_sheet.iter_rows(values_only=True):
            for cell in row:
                if cell and isinstance(cell, str):
                    lines.extend(cell.split("\n"))
    elif isinstance(corpus_or_sheet, str):
        lines = corpus_or_sheet.split("\n")
    elif isinstance(corpus_or_sheet, (list, tuple, set)):
        lines = list(corpus_or_sheet)

    for line in lines:
        l = line.strip()
        if not l:
            continue
        # 1. Line starts with Name: e.g. "Name [punct/space] word"
        m1 = re.match(r"^([a-zA-Z]+)(?:\s*[:\-–—,]\s*|\s+)([a-zA-Z]+)", l)
        if m1:
            cand, nxt = m1.group(1).lower(), m1.group(2).lower()
            if cand in n_set and nxt not in n_set and len(nxt) > 1:
                starters.add(nxt)

        # 2. Major punctuation followed by Name: [.!?;&•—–]\s*Name\s*(?:[:\-–—,]|\s+)word
        for m2 in re.finditer(r"[.!?;&•—–]\s*([a-zA-Z]+)(?:\s*[:\-–—,]\s*|\s+)([a-zA-Z]+)", l):
            cand, nxt = m2.group(1).lower(), m2.group(2).lower()
            if cand in n_set and nxt not in n_set and len(nxt) > 1:
                starters.add(nxt)

        # 3. Explicit marker anywhere: \bName\s*[:\-–—]\s*word
        for m3 in re.finditer(r"\b([a-zA-Z]+)\s*[:\-–—]\s*([a-zA-Z]+)", l):
            cand, nxt = m3.group(1).lower(), m3.group(2).lower()
            if cand in n_set and nxt not in n_set and len(nxt) > 1:
                starters.add(nxt)

    return starters


def find_member_mentions(text, members_list):
    """
    Finds occurrences of known members (and known aliases) in text at word boundaries.
    Returns list of tuples: (start, end, canonical_name, matched_str).
    """
    mentions = []
    text_lower = text.lower()
    for m in members_list:
        clean_m = str(m).strip().lower()
        if not clean_m:
            continue
        for match in re.finditer(r'\b' + re.escape(clean_m) + r'\b', text_lower):
            mentions.append((match.start(), match.end(), clean_m, text[match.start():match.end()]))

    for alias, canonical in NAME_ALIASES.items():
        if canonical in members_list or alias in text_lower:
            target = canonical if canonical in members_list else alias
            for match in re.finditer(r'\b' + re.escape(alias) + r'\b', text_lower):
                mentions.append((match.start(), match.end(), target, text[match.start():match.end()]))

    # Sort by start offset ascending, longer matches first to resolve duplicates
    mentions.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    filtered = []
    last_end = -1
    for start, end, canon, raw in mentions:
        if start >= last_end:
            filtered.append((start, end, canon, raw))
            last_end = end
    return filtered


def is_addressee_anchor(text, match_start, match_end, member_name, dynamic_starters=None):
    """
    Determines whether a name mention marks the start of a comment addressed to that member,
    versus an in-sentence mention/comparison (e.g. 'standing close to Kaelan').
    """
    prefix = text[:match_start]
    suffix = text[match_end:]

    words_before = re.findall(r'[a-zA-Z]+', prefix)
    last_word = words_before[-1].lower() if words_before else ''

    # Check if joined by 'and' or '&' to a previous object word (e.g. 'bc sophia and audrey')
    if last_word in {'and', '&'} and len(words_before) >= 3:
        if words_before[-3].lower() in OBJECT_PREPOSITIONS:
            return False

    has_boundary_after_last = bool(re.search(r'[\n.!?;&•—–]\s*$', prefix)) or bool(re.search(r'\s{2,}$', prefix))

    if last_word in OBJECT_PREPOSITIONS and not has_boundary_after_last:
        return False

    is_at_start = bool(re.match(r'^\s*[-*•–—~>]?\s*$', prefix))
    is_after_newline = bool(re.search(r'\n\s*[-*•–—~>]?\s*$', prefix))
    is_after_major_punct = bool(re.search(r'[.!?;&•—–]\s*$', prefix)) or bool(re.search(r'\s{2,}$', prefix))
    is_after_comma = bool(re.search(r',\s*$', prefix))

    has_explicit_marker = bool(re.match(r'^\s*[:\-–—,\)]', suffix))
    has_salutation_before = bool(re.search(r'\b(?:okay|ok|hey|hi|hello|for|maybe)\s*$', prefix, re.IGNORECASE))

    if is_at_start or is_after_newline or is_after_major_punct:
        return True
    if has_salutation_before or has_explicit_marker:
        return True
    if is_after_comma:
        return True

    # Delimiter-less case (e.g. space between clauses without punctuation: "good Ava solo is nice")
    post_words = re.findall(r'[a-zA-Z]+', suffix)
    first_post_word = post_words[0].lower() if post_words else ''

    is_post_starter = False
    if dynamic_starters and first_post_word in dynamic_starters:
        is_post_starter = True
    elif re.match(r'^(?:u|ur|urs|you|your|yours|youre|yall)$', first_post_word):
        is_post_starter = True
    elif re.match(r'^(?:is|are|was|were|be|am|can|could|should|would|might|will|did|do|does|dont|had|has|have)$', first_post_word):
        is_post_starter = True
    elif len(first_post_word) > 3 and (first_post_word.endswith('ed') or first_post_word.endswith('ing')):
        is_post_starter = True

    if is_post_starter and bool(re.search(r'\s+$', prefix)):
        return True

    return False


def extract_member_comments_from_cell(cell_val, known_members, dynamic_starters=None):
    """
    Extracts member-specific comments from an individual feedback cell.
    Handles multi-line paragraphs, un-delimited short responses, and inconsistent delimiters
    (newlines, commas, semicolons, dashes, periods, em-dashes, or spaces).
    Returns list of tuples: [(member_name, comment_snippet), ...]
    """
    if not cell_val or not str(cell_val).strip():
        return []

    if dynamic_starters is None:
        dynamic_starters = harvest_dynamic_starters(str(cell_val), known_members)

    text = str(cell_val).strip()
    lines = text.split('\n')
    results = []

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        mentions = find_member_mentions(line_clean, known_members)
        if not mentions:
            continue

        addressees = []
        for start, end, canon, raw in mentions:
            if is_addressee_anchor(line_clean, start, end, canon, dynamic_starters=dynamic_starters):
                addressees.append((start, end, canon, raw))

        if not addressees:
            # Fallback: if names were mentioned in a single-mention line, attribute line to each mentioned member
            for start, end, canon, raw in mentions:
                results.append((canon, line_clean))
            continue

        if len(addressees) == 1:
            results.append((addressees[0][2], line_clean))
        else:
            # Check for compound addressees at start: e.g. 'Name1 and Name2: [comment]'
            compound_match = re.match(r'^\s*([a-zA-Z]+)\s+(?:and|&)\s+([a-zA-Z]+)\s*[:,\-–—]', line_clean)
            if compound_match:
                n1 = compound_match.group(1).lower()
                n2 = compound_match.group(2).lower()
                results.append((n1, line_clean))
                results.append((n2, line_clean))
                continue

            # Merge consecutive mentions of the same member
            merged_addressees = []
            for a in addressees:
                if merged_addressees and merged_addressees[-1][2] == a[2]:
                    continue
                merged_addressees.append(a)

            for idx in range(len(merged_addressees)):
                cur_start, cur_end, cur_canon, cur_raw = merged_addressees[idx]
                next_start = merged_addressees[idx + 1][0] if idx + 1 < len(merged_addressees) else len(line_clean)
                segment = line_clean[cur_start:next_start].strip()
                segment = re.sub(r'[\s,;]+$', '', segment).strip()
                if segment:
                    results.append((cur_canon, segment))

    return results


def auto_detect_members_for_group(sheet, indiv_col_idx, known_members, group_name="", group_col_idx=None):
    """
    Scans feedback columns and group header for mentions of known members.
    If indiv_col_idx is provided, it scans individual feedback.
    If the group has no individual comments column (or no members were detected in it),
    and group_col_idx is provided, it scans the group comments column.
    """
    found_members = set()
    dynamic_starters = harvest_dynamic_starters(sheet, known_members)

    # Check group name itself (e.g. 'Arashi: Frederick & Yuka')
    if group_name:
        for m in known_members:
            if re.search(r'\b' + re.escape(m.lower()) + r'\b', group_name.lower()):
                found_members.add(m.lower())

    max_r = sheet.max_row or 0

    # Check individual comments column if present
    if indiv_col_idx:
        for row in range(2, max_r + 1):
            cell_val = sheet.cell(row=row, column=indiv_col_idx).value
            if not cell_val:
                continue
            extracted = extract_member_comments_from_cell(cell_val, known_members, dynamic_starters=dynamic_starters)
            for m, _ in extracted:
                found_members.add(m.lower())

    # For groups that don't have individual comments (or none were detected), scan group comments column
    if (not indiv_col_idx or not found_members) and group_col_idx:
        for row in range(2, max_r + 1):
            cell_val = sheet.cell(row=row, column=group_col_idx).value
            if not cell_val:
                continue
            extracted = extract_member_comments_from_cell(cell_val, known_members, dynamic_starters=dynamic_starters)
            for m, _ in extracted:
                found_members.add(m.lower())

    # Return in order of known_members
    return [m for m in known_members if m.lower() in found_members]


def parse_pd_comments(sheet, group_configs, header_title="", known_members=None):
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

    if known_members is None:
        all_assigned = set()
        for c in group_configs:
            all_assigned.update(c.get("members", []))
        if hasattr(config, "name_filepath") and os.path.exists(config.name_filepath):
            try:
                name_list_data = load_name_list(config.name_filepath)
                all_assigned.update(name_list_data.keys())
            except Exception:
                pass
        known_members = sorted(list(all_assigned))

    dynamic_starters = harvest_dynamic_starters(sheet, known_members)

    for config_item in group_configs:
        g_name = config_item["group_name"]
        g_col = config_item.get("group_col")
        i_col = config_item.get("indiv_col")
        i_name = config_item.get("indiv_name") or f"{g_name} Individual"
        members = [m.lower().strip() for m in config_item.get("members", []) if m.strip()]

        # 1. Extract group feedback
        group_text = ""
        max_r = sheet.max_row or 0
        if g_col:
            if g_col not in group_feedback_cache:
                g_comments = ""
                for r in range(2, max_r + 1):
                    val = sheet.cell(row=r, column=g_col).value
                    if val is not None and str(val).strip():
                        g_comments += str(val).strip() + "\n"
                group_feedback_cache[g_col] = g_comments
            group_text = group_feedback_cache.get(g_col, "")

        # 2. Extract individual lines per member using smart addressee segmentation
        indiv_comments_by_person = defaultdict(list)
        unassigned_indiv_comments = []

        def _is_trivial_placeholder(s):
            clean = re.sub(r"[^a-zA-Z0-9]", "", str(s).lower())
            return clean in {"", "na", "none", "no", "nope", "n", "nil", "null", "x"}

        if i_col:
            member_set = set(members)
            for r in range(2, max_r + 1):
                val = sheet.cell(row=r, column=i_col).value
                if val is not None and str(val).strip():
                    cell_text = str(val).strip()
                    for line in cell_text.split("\n"):
                        line_clean = line.strip()
                        if not line_clean:
                            continue

                        extracted = extract_member_comments_from_cell(line_clean, known_members, dynamic_starters=dynamic_starters)
                        if not extracted:
                            if not _is_trivial_placeholder(line_clean):
                                unassigned_indiv_comments.append(line_clean)
                            continue

                        # If multiple addressees in a single line, check if there was a standalone leading comment
                        if len(extracted) > 1:
                            mentions = find_member_mentions(line_clean, known_members)
                            addressees = [m for m in mentions if is_addressee_anchor(line_clean, m[0], m[1], m[2], dynamic_starters=dynamic_starters)]
                            if addressees and addressees[0][0] > 0:
                                prefix = line_clean[:addressees[0][0]].strip()
                                if re.search(r"[.!?;&—–]\s*$", prefix) and len(prefix) > 3:
                                    prefix_clean = prefix.rstrip(".!?;&—– ").strip()
                                    if not _is_trivial_placeholder(prefix_clean) and not re.match(r"^(?:ok|okay|hey|hi|hello|for)\b", prefix_clean, re.I):
                                        unassigned_indiv_comments.append(prefix.strip())

                        for target_m, snippet in extracted:
                            if target_m.lower() in member_set:
                                indiv_comments_by_person[target_m.lower()].append(snippet)
                            else:
                                # Feedback in this group's individual column addressed to someone NOT assigned to this group
                                if not _is_trivial_placeholder(snippet):
                                    unassigned_indiv_comments.append(snippet)

        # Merge unassigned individual comments into group comments if columns differ
        if g_col != i_col and unassigned_indiv_comments:
            unassigned_block = "\n".join(unassigned_indiv_comments)
            if group_text and group_text.strip():
                group_text = group_text.strip() + "\n" + unassigned_block + "\n"
            else:
                group_text = unassigned_block + "\n"

        # 3. Assign to members
        for person in members:
            # Add group comments if present
            if group_text and group_text.strip():
                comments_by_person[person][g_name] = group_text

            # Filter individual comments if present
            if i_col:
                p_comments = indiv_comments_by_person.get(person, [])
                if p_comments:
                    comments_by_person[person][i_name] = "\n".join(p_comments)

    # Format full messages
    full_message_by_person = {}
    for person, sections in comments_by_person.items():
        full_message_by_person[person] = format_pd_message(sections, header_title=header_title)

    return comments_by_person, full_message_by_person


def build_header_block(header_title):
    """Format a Slack header banner indicating which spreadsheet/feedback this is for."""
    if not header_title or not str(header_title).strip():
        return ""
    title = str(header_title).strip().strip("*").strip()
    clean_title = title.replace("(Responses)", "").replace("  ", " ").strip()
    if "feedback" not in clean_title.lower():
        clean_title += " Feedback"
    return f"*{clean_title}*\n{'=' * 32}\n\n"


def format_pd_message(sections, header_title=""):
    """
    Format PD sections into the exact Slack message format:
    *<Spreadsheet Name>*
    ================================

    *Section Name*
    comments
    -----------------------
    """
    header_block = build_header_block(header_title)
    whole_comment = ""
    for section_name, text in sections.items():
        clean_text = text.strip() if text else ""
        if clean_text:
            whole_comment += f"*{section_name}*\n{clean_text}\n-----------------------\n"

    if whole_comment.strip():
        return (header_block + whole_comment).strip()
    return ""


def parse_lc_comments(sheet, person_list, header_title=""):
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
            max_r = sheet.max_row or 0
            for r in range(2, max_r + 1):
                val = sheet.cell(row=r, column=col_idx).value
                if val is not None and str(val).strip():
                    col_comments.append(str(val).strip())
            if col_comments:
                joined = "\n______________________________\n".join(col_comments)
                comments_by_person[person_key] = joined

    full_message_by_person = {}
    for person, comments in comments_by_person.items():
        full_message_by_person[person] = format_lc_message(comments, header_title=header_title)

    return comments_by_person, full_message_by_person


def format_lc_message(comments, header_title=""):
    """
    Format LC comments into Slack message format:
    *<Spreadsheet Name>*
    ================================

    *Personal Feedback*
    ‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾
    <comments>
    """
    clean_text = comments.strip() if comments else ""
    if not clean_text:
        return ""
    header_block = build_header_block(header_title)
    body = f"*Personal Feedback*\n‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\n{clean_text}\n"
    return (header_block + body).strip()


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

    # Replace horizontal divider lines (---, ‾‾‾, ___, ===) and absorb adjacent single newlines
    # so block-level <div> dividers don't get extra <br> padding
    escaped = re.sub(
        r'\n?[ \t]*[-_‾—=]{3,}[ \t]*\n?',
        f'<div style="height: 1px; background-color: {hr_color}; margin: 6px 0;"></div>',
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
        <div style="padding: 14px 16px; display: flex; align-items: flex-start; gap: 12px;">
            <div style="width: 40px; height: 40px; border-radius: 8px; background: linear-gradient(135deg, #4a154b, #611f69); display: flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0; box-shadow: 0 1px 3px rgba(0,0,0,0.2);">
                🥁
            </div>
            <div style="flex-grow: 1; min-width: 0;">
                <div style="display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px;">
                    <span style="font-weight: 900; font-size: 15px; color: {'#ffffff' if theme == 'dark' else '#1d1c1d'};">{sender_name}</span>
                    <span style="background: {badge_bg}; color: {badge_color}; font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 3px;">APP</span>
                    <span style="font-size: 12px; color: {meta_color};">Today at {time_str}</span>
                </div>
                <div style="font-size: 14.5px; line-height: 1.4; color: {text_color}; word-break: break-word;">
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


def fetch_slack_users(token, api_url="https://slack.com/api/"):
    """
    Fetch all active, non-bot human members from the Slack workspace via users.list.
    Requires the `users:read` OAuth scope on the bot token.
    Returns (ok: bool, users_list_or_error: list[dict] or str).
    """
    if not token or not token.strip():
        return False, "Slack Bot Token is missing. Please set your token in Step 1 or secrets."

    clean_token = token.strip()
    base_url = api_url.rstrip('/')
    url = f"{base_url}/users.list"
    headers = {
        'Authorization': f'Bearer {clean_token}',
        'Content-Type': 'application/json; charset=utf-8'
    }

    members = []
    cursor = None

    try:
        while True:
            params = {'limit': 200}
            if cursor:
                params['cursor'] = cursor

            resp = requests.get(url, headers=headers, params=params, timeout=12)
            data = resp.json()

            if not data.get("ok"):
                err = data.get("error", "Unknown error")
                if err == "missing_scope":
                    needed = data.get("needed", "users:read")
                    return False, (
                        f"Missing required Slack OAuth scope: `{needed}`.\n\n"
                        f"To enable this:\n"
                        f"1. Go to your Slack App dashboard at https://api.slack.com/apps\n"
                        f"2. Navigate to **OAuth & Permissions** → **Scopes** → **Bot Token Scopes**\n"
                        f"3. Add the `{needed}` scope.\n"
                        f"4. Click **Reinstall to Workspace** at the top of the OAuth page to grant permissions."
                    )
                elif err in ("invalid_auth", "token_revoked", "account_inactive"):
                    return False, f"Slack Authentication error: `{err}`. Please verify your bot token."
                return False, f"Slack API error: `{err}`"

            for m in data.get("members", []):
                # Filter out deleted members and bots
                if m.get("deleted") or m.get("is_bot") or m.get("is_app_user"):
                    continue
                if m.get("id") == "USLACKBOT":
                    continue

                prof = m.get("profile", {})
                disp_name = prof.get("display_name", "").strip()
                real_name = prof.get("real_name", "").strip() or m.get("real_name", "").strip()
                uname = m.get("name", "").strip()
                uid = m.get("id", "").strip()

                # Choose best default name: display_name > real_name first name > username
                first_name = real_name.split()[0] if real_name else ""
                suggested = (disp_name or first_name or uname).lower()

                members.append({
                    "id": uid,
                    "username": uname,
                    "real_name": real_name,
                    "display_name": disp_name,
                    "suggested_name": suggested
                })

            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        members.sort(key=lambda x: x["suggested_name"])
        return True, members

    except requests.exceptions.RequestException as e:
        return False, f"Network error connecting to Slack API: {e}"
    except Exception as e:
        return False, f"Unexpected error while fetching Slack users: {e}"


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
            if error == 'not_in_channel':
                scopes_hdr = resp.headers.get('X-OAuth-Scopes', '')
                active_scopes = [s.strip() for s in scopes_hdr.split(',') if s.strip()]

                # Try auto-joining if channels:join is available
                if 'channels:join' in active_scopes:
                    try:
                        join_url = f"{api_url.rstrip('/')}/conversations.join"
                        join_resp = requests.post(join_url, headers=headers, json={'channel': user_id}, timeout=10)
                        if join_resp.json().get('ok'):
                            retry_resp = requests.post(url, headers=headers, json=payload, timeout=10)
                            retry_res = retry_resp.json()
                            if retry_res.get('ok'):
                                return True, retry_res.get('ts', 'ok')
                    except Exception:
                        pass

                if active_scopes and 'chat:write.public' not in active_scopes:
                    return False, (
                        f"Fatal Slack error: not_in_channel (`chat:write.public` is NOT active on this token; "
                        f"active scopes: `{', '.join(active_scopes)}`). Click **Reinstall to Workspace** in Slack OAuth & Permissions."
                    )
                return False, (
                    "Fatal Slack error: not_in_channel (`chat:write.public` only covers unrestricted public channels; "
                    "if this channel is private or restricted, invite the bot via `/invite @ST SlackBot`)."
                )

            if error in ('invalid_auth', 'channel_not_found', 'user_not_found', 'account_inactive'):
                return False, f"Fatal Slack error: {error}"

        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                return False, f"Network error after {max_retries} attempts: {e}"
        except Exception as e:
            return False, f"Unexpected error: {e}"

        wait_time = 2 ** attempt
        time.sleep(wait_time)

    return False, f"Failed after {max_retries} attempts: {result.get('error', 'Unknown Error')}"


def load_channel_map(filepath="channel_map.json"):
    """Load saved job-role-to-Slack-channel mapping from JSON file."""
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_channel_map(channel_map, filepath="channel_map.json"):
    """Save job-role-to-Slack-channel mapping to JSON file. Returns (success: bool)."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(channel_map, f, indent=4)
        return True
    except OSError:
        return False


def fetch_slack_channels(token, api_url="https://slack.com/api/", types="public_channel"):
    """
    Fetches all non-archived Slack channels from the workspace via conversations.list.
    Requires the `channels:read` Bot Token Scope (and `groups:read` if private channels are included).
    Returns:
      - (True, list of channel dicts: [{'id', 'name', 'is_private', 'num_members', 'topic'}])
      - (False, error_message_str)
    """
    if not token or not str(token).strip():
        return False, "Slack Bot Token is not configured."

    clean_token = str(token).strip()
    url = f"{api_url.rstrip('/')}/conversations.list"
    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json; charset=utf-8"
    }

    channels = []
    cursor = None

    try:
        while True:
            params = {
                "types": types,
                "exclude_archived": "true",
                "limit": 200
            }
            if cursor:
                params["cursor"] = cursor

            resp = requests.get(url, headers=headers, params=params, timeout=12)
            data = resp.json()

            if not data.get("ok"):
                err = data.get("error", "Unknown error")
                if err == "missing_scope":
                    needed = data.get("needed", "channels:read")
                    return False, (
                        f"Missing required Slack OAuth scope: `{needed}`.\n\n"
                        f"To enable this:\n"
                        f"1. Go to your Slack App dashboard at https://api.slack.com/apps\n"
                        f"2. Navigate to **OAuth & Permissions** → **Scopes** → **Bot Token Scopes**\n"
                        f"3. Add the `{needed}` scope (and `chat:write.public` to post to public channels).\n"
                        f"4. Click **Reinstall to Workspace** at the top of the OAuth page."
                    )
                elif err in ("invalid_auth", "token_revoked", "account_inactive"):
                    return False, f"Slack Authentication error: `{err}`. Please verify your bot token."
                return False, f"Slack API error: `{err}`"

            for ch in data.get("channels", []):
                ch_id = ch.get("id", "").strip()
                ch_name = ch.get("name", "").strip()
                if not ch_id or not ch_name:
                    continue
                channels.append({
                    "id": ch_id,
                    "name": ch_name,
                    "is_private": bool(ch.get("is_private", False)),
                    "num_members": ch.get("num_members", 0),
                    "topic": (ch.get("topic") or {}).get("value", "").strip()
                })

            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        # Sort #job-* channels first alphabetically, then other channels alphabetically
        channels.sort(key=lambda c: (0 if c["name"].lower().startswith("job-") else 1, c["name"].lower()))
        return True, channels

    except requests.exceptions.RequestException as e:
        return False, f"Network error connecting to Slack API: {e}"
    except Exception as e:
        return False, f"Unexpected error while fetching Slack channels: {e}"


_JOB_GENERIC_WORDS = {
    "coordinator", "coordinators", "coord", "director", "directors",
    "officer", "officers", "and", "of", "the", "for"
}


def auto_match_job_channel(job_info, channels):
    """
    Matches a detected job column dict (from detect_job_columns) against fetched Slack channels.
    Prioritizes channels prefixed with `#job-` / `#jobs-`.
    Returns the best matching channel dict, or None if no confident match is found.
    """
    if not job_info or not channels:
        return None

    role_title = str(job_info.get("role_title", "")).strip()
    abbrev = str(job_info.get("abbrev", "")).strip()

    # Build normalized candidate keys from role_title and abbrev
    candidates = []
    if abbrev:
        ab_norm = re.sub(r"[^a-z0-9]", "", abbrev.lower())
        if ab_norm:
            candidates.append((ab_norm, 120))
            if ab_norm.endswith("s") and len(ab_norm) > 2:
                candidates.append((ab_norm[:-1], 118))

    role_lower = role_title.lower()
    role_full_norm = re.sub(r"[^a-z0-9]", "", role_lower)
    if role_full_norm:
        candidates.append((role_full_norm, 108))

    # Strip generic role words like "Coordinator", "Director", "Coord"
    role_words = [w for w in re.findall(r"[a-z0-9]+", role_lower) if w not in _JOB_GENERIC_WORDS]
    if role_words:
        stripped_norm = "".join(role_words)
        candidates.append((stripped_norm, 112))
        if stripped_norm.endswith("s") and len(stripped_norm) > 3:
            candidates.append((stripped_norm[:-1], 106))
        for w in role_words:
            if len(w) >= 3:
                candidates.append((w, 90))

    best_channel = None
    best_score = 0

    for ch in channels:
        ch_name = ch.get("name", "").lower().strip()
        is_job_prefixed = ch_name.startswith("job-") or ch_name.startswith("jobs-")
        ch_core = re.sub(r"^jobs?[-_]", "", ch_name)
        ch_norm = re.sub(r"[^a-z0-9]", "", ch_core)
        ch_tokens = [t for t in re.findall(r"[a-z0-9]+", ch_core) if t]

        if not ch_norm:
            continue

        prefix_bonus = 15 if is_job_prefixed else 0
        score = 0

        for key, base_weight in candidates:
            if ch_norm == key:
                score = max(score, base_weight + prefix_bonus)
            elif len(key) >= 3 and len(ch_norm) >= 3:
                # Handle pluralization or short prefix (e.g. "pub" vs "publicity", "workshop" vs "workshops")
                if ch_norm.startswith(key) or key.startswith(ch_norm):
                    ratio = min(len(ch_norm), len(key)) / max(len(ch_norm), len(key))
                    if ratio >= 0.4 or (len(ch_norm) >= 3 and key.startswith(ch_norm)):
                        score = max(score, int(base_weight * 0.8) + prefix_bonus)
                elif key in ch_tokens:
                    score = max(score, 75 + prefix_bonus)

        if score > best_score:
            best_score = score
            best_channel = ch

    return best_channel if best_score >= 70 else None


def auto_match_job_channels(job_columns, channels):
    """
    Matches all detected job columns to Slack channels.
    Returns dict {col_idx: channel_dict_or_None}.
    """
    return {job["col_idx"]: auto_match_job_channel(job, channels) for job in job_columns}


def parse_lc_channel_comments(sheet, channel_configs, header_title=""):
    """
    Parses LC Job Feedback columns into per-channel messages.
    channel_configs is a list of dicts:
      [
          {
              "col_idx": int,
              "job_name": str,
              "channel_id": str,
              "channel_name": str,
              "include": bool
          }, ...
      ]
    Returns:
      - comments_by_target: dict {target_label: joined_comments_str}
      - full_message_by_target: dict {target_label: formatted_slack_string}
      - target_id_map: dict {target_label: channel_id}
    """
    comments_by_target = {}
    full_message_by_target = {}
    target_id_map = {}

    clean_base_title = ""
    if header_title and str(header_title).strip():
        t = str(header_title).strip().strip("*").strip()
        clean_base_title = t.replace("(Responses)", "").replace("  ", " ").strip()
        if "feedback" not in clean_base_title.lower():
            clean_base_title += " Feedback"

    max_r = sheet.max_row or 0

    for cfg in channel_configs:
        if not cfg.get("include", True):
            continue
        col_idx = cfg.get("col_idx")
        ch_id = (cfg.get("channel_id") or "").strip()
        ch_name = (cfg.get("channel_name") or "").strip().lstrip("#")
        job_name = (cfg.get("job_name") or f"Column {col_idx}").strip()

        if not col_idx or (not ch_id and not ch_name):
            continue

        target_label = f"#{ch_name}" if ch_name else ch_id
        inline_title = f"{clean_base_title} ({job_name})" if clean_base_title else job_name
        header_block = f"*{inline_title}*\n{'=' * 32}\n"

        col_comments = []
        for r in range(2, max_r + 1):
            val = sheet.cell(row=r, column=col_idx).value
            if val is not None and str(val).strip():
                col_comments.append(str(val).strip())

        if not col_comments:
            continue

        joined = "\n______________________________\n".join(col_comments)

        # Avoid key collision if two job columns map to the same channel
        if target_label in comments_by_target:
            comments_by_target[target_label] += f"\n______________________________\n*{job_name}*\n{joined}"
            full_message_by_target[target_label] = f"{header_block}{comments_by_target[target_label]}".strip()
        else:
            comments_by_target[target_label] = joined
            full_message_by_target[target_label] = f"{header_block}{joined}".strip()
            target_id_map[target_label] = ch_id

    return comments_by_target, full_message_by_target, target_id_map
