import os
import json
#handles all of the configuration

CONFIG_FILE = './config.json'


slack_token = ""
slack_api_url = ""
name_filepath = ""
form_filepath = ""
search_list = []
mode = ""

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    global slack_token, slack_api_url, name_filepath, form_filepath, search_list, mode
    slack_token = os.getenv("SLACK_BOT_TOKEN")
    slack_api_url = config['slack']['api_url']
    name_filepath = config['file']['name_list']
    spreadsheets_folder = config['file']['spreadsheet_folder']
    form_file = config['file']['form_file']
    form_filepath = os.path.join(spreadsheets_folder, form_file)
    search_list = config['search']['terms']
    mode = config['mode']


