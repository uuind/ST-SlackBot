import os
#handles all of the configuration
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")  # or paste it directly (not recommended)
SLACK_API_URL = 'https://slack.com/api/'
NAME_FILE = "name_list.json"
FORM_FILEPATH = "./Tales-MPP-Winter-2026.xlsx"
SEARCH_LIST = ['Group', 'Ensemble', 'Arashi', 'Three Sizz', 'Individual']