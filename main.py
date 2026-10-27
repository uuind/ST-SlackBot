from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from collections import defaultdict
from dotenv import load_dotenv
import csv
import requests
import time
import json
from openpyxl import Workbook, load_workbook

from config import SLACK_API_URL, SLACK_TOKEN, SEARCH_LIST, NAME_FILE, FORM_FILEPATH
import os
from pathlib import Path

dotenv_path = Path("./token.env")
load_dotenv(dotenv_path=dotenv_path)

# Set your Slack token and channel name



client = WebClient(token=SLACK_TOKEN)

"""
Comment Dictionary Structure:
comment_dict = {
    "name1": {
        "Group1": string,
        "Group1_Indvidual": string,
        etc.
            },
    "name2": {},
    etc.
}
"""
global_comment_dict = defaultdict(dict)


def main():
    # setup spreadsheet variables
    if FORM_FILEPATH is None:
        spreadsheet_path = input("Enter spreadsheet name or filepath")
    else:
        spreadsheet_path = FORM_FILEPATH

    workbook = load_workbook(spreadsheet_path, read_only=True)
    sheet = workbook['Form Responses 1']

    # get row headers/groups
    row_iterator = sheet.iter_rows(min_row=1, max_row=1, values_only=True)
    first_row_values = next(row_iterator)
    print(first_row_values)

    # get slack_ids for every member (located in NAME_FILE)
    slack_id_dict = create_person_dict(NAME_FILE)

    # figure out which comments are group/individual
    indiv_comments_mask, group_comments_mask, groups = build_group_dictionary(first_row_values)

    # extract group and individual comments
    parse_group_comments(sheet, groups, group_comments_mask)
    parse_individual_comments(sheet, groups, indiv_comments_mask)
    print(global_comment_dict)

    send_comments_to_everyone(slack_id_dict)


def send_comments_to_everyone(slack_id_dict):
    for person in global_comment_dict.keys():
        whole_comment = ""
        try:
            slack_id = slack_id_dict[person]
            for group in global_comment_dict[person].keys():
                whole_comment += "*" + group + "*" + '\n' + global_comment_dict[person][group] + '\n' + "-----------------------" + '\n'
            send_slack_message_with_retry(slack_id, whole_comment)
        except Exception as e:
            print(f"Error: {e}")


def create_person_dict(filepath):
    with open(filepath, 'r') as file:
        slack_id_dict = json.load(file)
        comment_dict = dict.fromkeys(slack_id_dict.keys())

    return slack_id_dict


def parse_group_comments(sheet, groups, group_comment_indexes):
    column_index = 1
    group_index = 0
    for column in group_comment_indexes:
        if column:
            comments = ""
            group_name = sheet.cell(row=1, column=column_index).value
            for row_tuple in sheet.iter_rows(
                    min_row=2,
                    min_col=column_index,
                    max_col=column_index,
                    values_only=True
            ):
                if row_tuple[0] is not None:
                    comments += (row_tuple[0]) + '\n'
            for person in groups[group_index]:
                global_comment_dict[person][group_name] = comments

            group_index += 1
        column_index += 1


def parse_individual_comments(sheet, groups, individual_comment_indexes):
    column_index = 1 # xlsx index starts from 1
    group_index = 0
    for column in individual_comment_indexes:
        if column:
            master_comment = ""
            group_name = sheet.cell(row=1, column=column_index).value
            for row_tuple in sheet.iter_rows(
                    min_row=2,
                    min_col=column_index,
                    max_col=column_index,
                    values_only=True
            ):
                if row_tuple[0] is not None:
                    comment = row_tuple[0]
                    master_comment += comment + '\n'
            comments_master_list = master_comment.split('\n')
            for person in groups[group_index]:
                personal_comment = ""
                for individual_comment in comments_master_list:
                    if person in individual_comment.lower():
                        personal_comment += individual_comment + '\n'
                global_comment_dict[person][group_name] = personal_comment + '\n'
            group_index += 1
        column_index += 1


def build_group_dictionary(header):
    groups = []
    indiv_comments_mask = [0] * len(header)
    group_comments_mask = [0] * len(header)
    column_index = 0
    for group in header:
        if any(word in group for word in SEARCH_LIST):
            if group.find("Individual") == -1:
                group_name = group
                names = input(f"Please put the names of people in {group_name}, separated by commas").lower().replace(" ","").split(',')
                groups.append(names)
                group_comments_mask[column_index] = 1
            else:
                indiv_comments_mask[column_index] = 1

        column_index += 1

    return indiv_comments_mask, group_comments_mask, groups


def send_slack_message_with_retry(user_id, message_text, max_retries=3):
    """
    Sends a message to a specified Slack channel/user with exponential backoff.

    Args:
        user_id (str): The ID of the conversation (DM, private channel, or public channel).
        message_text (str): The text content of the message.
        max_retries (int): The maximum number of times to retry the API call.
    """
    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'Authorization': f'Bearer {SLACK_TOKEN}'
    }

    payload = {
        'channel': user_id,
        'text': message_text
    }
    result = {}
    for attempt in range(max_retries):
        try:
            print(f"[{user_id}] Attempt {attempt + 1}/{max_retries}...")

            # --- REAL API CALL ---
            # NOTE: To make this real, replace 'chat.postMessage' with f'{SLACK_API_URL}chat.postMessage'
            # and UNCOMMENT the four lines below, then DELETE the MOCK block.

            response = requests.post(f'{SLACK_API_URL}chat.postMessage', headers=headers, data=json.dumps(payload))
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
            result = response.json()
            break
        except requests.exceptions.RequestException as e:
            # Handle connection errors, timeouts, and simulated transient errors
            print(f"[{user_id}] Request error: {e}")

        except Exception as e:
            # Handle errors returned from Slack (e.g., 'channel_not_found')
            print(f"[{user_id}] Slack API Error: {result.get('error', 'Unknown Error')} - Full Response: {result}")
            # If the error is fatal (e.g., invalid token or channel not found), stop trying
            if result.get('error') in ('invalid_auth', 'channel_not_found', 'user_not_found'):
                print(f"[{user_id}] FATAL ERROR. Stopping retries.")
                break

        # Apply exponential backoff before the next attempt
        if attempt < max_retries - 1:
            wait_time = 2 ** attempt
            print(f"[{user_id}] Retrying in {wait_time} seconds...")
            time.sleep(wait_time)
        else:
            print(f"[{user_id}] Failed after {max_retries} attempts. Giving up.")

    # Return True on successful break, False otherwise (in a real app you'd want detailed result)
    return result.get('ok', False) if 'result' in locals() else False


if __name__ == "__main__":
    main()
