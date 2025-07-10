from flask import Flask, render_template, request, jsonify
import gspread
import os
from google.oauth2.service_account import Credentials
from threading import Lock

app = Flask(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]
creds = Credentials.from_service_account_file(
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"], scopes=SCOPES
)
gc = gspread.authorize(creds)
spreadsheet = gc.open("GolfPairingsApp2025")

# プレイヤー情報のキャッシュ
cache = {
    "Players": [],
    "code_to_name": {},
    "lock": Lock()
}

def load_player_cache():
    with cache["lock"]:
        player_sheet = spreadsheet.worksheet("Players")
        player_records = player_sheet.get_all_records()
        cache["Players"] = player_records
        cache["code_to_name"] = {
            str(row["Code"]): row["Name"] for row in player_records
        }

load_player_cache()

@app.route("/")
def index():
    round = request.args.get("round", "1st")
    sheet = spreadsheet.worksheet(f"Pairings_{round}")
    records = sheet.get_all_records()

    player_sheet = spreadsheet.worksheet("Players")
    player_records = player_sheet.get_all_records()
    code_to_name = {str(row["Code"]): row["Name"] for row in player_records}

    # 修正後：1行に3人分の選手データを展開してグループ化
    groups = []
    for row in records:
        group = []
        group_number = row.get("Group")
        for i in range(1, 4):  # Code1～Code3
            code = row.get(f"Code{i}")
            choice = row.get(f"Choice{i}")
            if code:  # 空でなければ
                group.append({
                    "name": code_to_name.get(str(code), "Unknown"),
                    "code": str(code),
                    "choice": choice,
                    "group": group_number
                })
        if group:
            groups.append(group)

    return render_template("index.html", groups=groups, selected_round=round)


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json()
    code = data["code"]
    group = int(data["group"])
    round = data["round"]
    choice = data["choice"]

    sheet = spreadsheet.worksheet(f"Pairings_{round}")
    records = sheet.get_all_records()

    target_row_idx = None
    target_col_letter = None

    for idx, row in enumerate(records, start=2):
        if row.get("Group") == group:
            for i in range(1, 4):
                if str(row.get(f"Code{i}")) == code:
                    target_row_idx = idx
                    target_col_letter = chr(ord('E') + i)
                    break
        if target_row_idx:
            break

    if target_row_idx and target_col_letter:
        sheet.update(f"{target_col_letter}{target_row_idx}", [[choice]])

        aim_count = 0
        noaim_count = 0
        for row in records:
            for j in range(1, 4):
                if row.get(f"Code{j}"):
                    val = str(row.get(f"Choice{j}", "")).strip()
                    if row.get("Group") == group and str(row.get(f"Code{j}")) == code:
                        val = choice
                    if val == "狙う":
                        aim_count += 1
                    elif val == "狙わない":
                        noaim_count += 1

        summary_sheet = spreadsheet.worksheet(f"Summary_{round}")
        summary_sheet.update("A2", [[aim_count]])
        summary_sheet.update("B2", [[noaim_count]])

        return jsonify({"status": "ok"})

    return jsonify({"status": "not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
