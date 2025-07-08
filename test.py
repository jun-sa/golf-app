import gspread
from google.oauth2.service_account import Credentials

# スコープ定義
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# 認証
creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
gc = gspread.authorize(creds)

# スプレッドシートを開く（名前 or URL）
spreadsheet = gc.open("GolfPairingsApp2025")  # スプレッドシート名を指定

# タブを開く
players_sheet = spreadsheet.worksheet("Players")

# データを取得
players = players_sheet.get_all_records()
for player in players:
    print(player["Code"], player["Name"])
