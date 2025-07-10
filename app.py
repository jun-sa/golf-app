from flask import Flask, render_template, request, jsonify
import gspread
import os
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# 環境変数からパスを取得（Renderが設定してくれる）
# CREDENTIALS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

# 認証情報の読み込み（ここを環境変数ベースに）
creds = Credentials.from_service_account_file(
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"], scopes=SCOPES
)
gc = gspread.authorize(creds)
spreadsheet = gc.open("GolfPairingsApp2025")  # 君のシート名に合わせて！

@app.route("/")
def index():
    round = request.args.get("round", "1st")  # ← デフォルト1st
    sheet = spreadsheet.worksheet(f"Pairings_{round}")
    records = sheet.get_all_records()

    player_sheet = spreadsheet.worksheet("Players")
    player_records = player_sheet.get_all_records()
    code_to_name = {str(row["Code"]): row["Name"] for row in player_records}

    # データをグループ化（1組ごとに分けるなど）
    groups = []
    group = []
    current_group = 1
    for row in records:
        if row["Group"] != current_group:
            groups.append(group)
            group = []
            current_group += 1
        group.append({
            "name": code_to_name.get(str(row["Code"]), "Unknown"),
            "code": row["Code"],
            "choice": row["Choice"]
        })
    groups.append(group)  # 最後のグループを追加

    return render_template("index.html", groups=groups, selected_round=round)



@app.route("/submit", methods=["POST"])
@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json()
    code = data["code"]
    group = int(data["group"])
    round = data["round"]
    choice = data["choice"]

    sheet_name = f"Pairings_{round}"
    sheet = spreadsheet.worksheet(sheet_name)
    records = sheet.get_all_records()  # ここだけで1回に！

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
        # 更新処理（Choice列）
        sheet.update(f"{target_col_letter}{target_row_idx}", [[choice]])

        # 💡再び読み直さずに、今の records から集計！
        all_choices = []
        for row in records:
            for j in range(1, 4):
                if row.get(f"Code{j}"):
                    val = str(row.get(f"Choice{j}", "")).strip()
                    if row.get(f"Group") == group and str(row.get(f"Code{j}")) == code:
                        val = choice  # 自分の選択を反映（↑はまだ古いままやから）

                    if val:
                        all_choices.append(val)

        aim_count = all_choices.count("狙う")
        noaim_count = all_choices.count("狙わない")

        # Summary反映
        summary_sheet_name = f"Summary_{round}"
        summary_sheet = spreadsheet.worksheet(summary_sheet_name)
        summary_sheet.update("A2", [[aim_count]])
        summary_sheet.update("B2", [[noaim_count]])

        return jsonify({"status": "ok"})

    return jsonify({"status": "not found"}), 404






if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
