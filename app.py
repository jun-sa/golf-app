from flask import Flask, render_template, request, jsonify
import gspread
import os
from google.oauth2.service_account import Credentials
from threading import Lock
import threading
import requests
import time

app = Flask(__name__)

def ping_render():
    while True:
        try:
            res = requests.get("https://golf-app-4i3n.onrender.com/ping")
            print(f"[PING] Status: {res.status_code}")
        except Exception as e:
            print(f"[PING ERROR] {e}")
        time.sleep(180)  # 3分おき

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
    code_to_name = cache["code_to_name"]  # これだけで十分

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
    try:
        data = request.get_json()
        code = str(data["code"]).strip()
        group = int(str(data["group"]).strip())
        rnd = data["round"]  # built-inのroundを避けるため変数名変更
        choice = data["choice"]

        sheet = spreadsheet.worksheet(f"Pairings_{rnd}")

        # 1回だけ読み込み（records は dict のリスト）
        records = sheet.get_all_records()

        target_row_idx = None   # シート上の行番号（2起点）
        target_choice_col = None  # F/G/H のどれか

        # 行/列の特定（型ズレに強くする）
        for idx, row in enumerate(records, start=2):  # 2行目から
            row_group_raw = row.get("Group")
            try:
                row_group = int(str(row_group_raw).strip())
            except Exception:
                row_group = None

            if row_group == group:
                for i in range(1, 4):  # Code1..3 / Choice1..3
                    cell_code = str(row.get(f"Code{i}", "")).strip()
                    if cell_code and cell_code == code:
                        target_row_idx = idx
                        # Choice1..3 は列F..H（E=5 → E+1=F, E+2=G, E+3=H）
                        target_choice_col = chr(ord("E") + i)
                        break
            if target_row_idx:
                break

        if not target_row_idx or not target_choice_col:
            return jsonify({"status": "not found"}), 404

        # まず選択を書き込む
        sheet.update(f"{target_choice_col}{target_row_idx}", [[choice]])

        # いま手元にある records は古いので、変更箇所だけ差し替えて集計
        aim_count = 0
        noaim_count = 0

        for r_idx, row in enumerate(records, start=2):
            for j in range(1, 4):
                code_j = row.get(f"Code{j}")
                if not code_j:
                    continue

                # 元の値
                val = str(row.get(f"Choice{j}", "")).strip()

                # さっき更新した該当セルだけは choice を反映して集計する
                if r_idx == target_row_idx and (chr(ord("E") + j) == target_choice_col):
                    val = choice

                if val == "狙う":
                    aim_count += 1
                elif val == "狙わない":
                    noaim_count += 1

        # J2:K2 を一発で更新（リクエスト1回・速度/安定性UP）
        sheet.update("J2:K2", [[aim_count, noaim_count]])

        return jsonify({"status": "ok", "aim": aim_count, "noaim": noaim_count})

    except Exception as e:
        import traceback
        print("ERROR in /submit:", e, traceback.format_exc(), flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/ping")
def ping():
    return "pong", 200

@app.before_first_request
def activate_ping():
    threading.Thread(target=ping_render, daemon=True).start()
    

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

