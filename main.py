import os
import sys
import config
import bot_logic


def run_slackbot_process():
    """CLI runner for ST-SlackBot delegating to bot_logic."""
    config.load_config()

    # 1. Locate spreadsheet (CLI argument, config, or prompt)
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        spreadsheet_path = sys.argv[1]
    elif not config.form_filepath or not os.path.exists(config.form_filepath):
        spreadsheet_path = input("Enter spreadsheet path: ").strip()
    else:
        spreadsheet_path = config.form_filepath

    if not os.path.exists(spreadsheet_path):
        print(f"Error: File not found at '{spreadsheet_path}'")
        return

    print(f"Loading workbook: {spreadsheet_path}")
    wb, sheet, _ = bot_logic.load_workbook_and_sheet(spreadsheet_path)
    headers = bot_logic.get_sheet_headers(sheet)

    # 2. Load members
    name_dict = bot_logic.load_name_list(config.name_filepath)
    known_members = list(name_dict.keys())
    print(f"Loaded {len(known_members)} members from '{config.name_filepath}'.")

    # Auto-detect mode from sheet headers
    detected_mode, detect_reason, _ = bot_logic.detect_spreadsheet_mode(
        headers, known_members, config.search_list
    )
    print(f"🤖 Auto-detected spreadsheet format: {detected_mode} Mode ({detect_reason})")

    mode_prompt = f"Use {detected_mode} Mode? [Enter to accept, or type 'PD'/'LC' to override]: "
    user_choice = input(mode_prompt).strip().upper()
    active_mode = user_choice if user_choice in ("PD", "LC") else detected_mode
    config.mode = active_mode
    print(f"Active Mode: {config.mode}\n")

    full_messages = {}

    # 3. Process according to mode
    if config.mode == "PD":
        paired, _, _ = bot_logic.detect_groups_pd(headers, config.search_list)
        if not paired:
            print("No groups matching search terms found in headers.")
            return

        group_configs = []
        for p in paired:
            group_name = p["group_name"]
            auto_detected = bot_logic.auto_detect_members_for_group(sheet, p["indiv_col"], known_members)
            default_str = ", ".join(auto_detected)

            prompt = f"Members in '{group_name}'"
            if default_str:
                prompt += f" [Enter to accept auto-detected: {default_str}]"
            prompt += ": "

            user_input = input(prompt).strip()
            if user_input:
                members = [m.strip().lower() for m in user_input.split(",") if m.strip()]
            else:
                members = auto_detected

            group_configs.append({
                "group_name": group_name,
                "group_col": p["group_col"],
                "indiv_name": p["indiv_name"],
                "indiv_col": p["indiv_col"],
                "members": members
            })

        _, full_messages = bot_logic.parse_pd_comments(sheet, group_configs)

    elif config.mode == "LC":
        _, full_messages = bot_logic.parse_lc_comments(sheet, known_members)

    else:
        print(f"Invalid mode in configuration: '{config.mode}'")
        return

    # 4. Review and Dispatch
    if not full_messages:
        print("No feedback generated for any members.")
        return

    print(f"\nGenerated feedback for {len(full_messages)} members:")
    for person in sorted(full_messages.keys()):
        slack_id = name_dict.get(person, "MISSING_ID")
        print(f" - {person} (Slack ID: {slack_id}, {len(full_messages[person])} chars)")

    # Sample preview
    sample_person = sorted(full_messages.keys())[0]
    print(f"\n--- [SAMPLE PREVIEW FOR @{sample_person}] ---")
    print(full_messages[sample_person])
    print("-------------------------------------------\n")

    confirm = input(f"Send Slack messages to these {len(full_messages)} members? (y/N): ").strip().lower()
    if confirm != "y":
        print("Canceled. No messages were sent.")
        return

    # 5. Send messages
    print("\nSending messages...")
    success_count = 0
    fail_count = 0

    for person, message_text in full_messages.items():
        slack_id = name_dict.get(person)
        if not slack_id:
            print(f"❌ {person}: Skipped (Missing Slack ID)")
            fail_count += 1
            continue

        ok, res = bot_logic.send_slack_message(
            config.slack_token, config.slack_api_url, slack_id, message_text
        )
        if ok:
            print(f"✅ {person} ({slack_id}): Delivered")
            success_count += 1
        else:
            print(f"❌ {person} ({slack_id}): Failed ({res})")
            fail_count += 1

    print(f"\nFinished. Sent: {success_count}, Failed: {fail_count}")


if __name__ == "__main__":
    run_slackbot_process()
