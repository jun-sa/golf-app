from flask import Flask, render_template, request, jsonify
import gspread
import os
from google.oauth2.service_account import Credentials
from threading import Lock
import threading
import requests
import time

app = Flask(__name__)

# 既にある import 群の下あたりに追加
from threading import Lock
import threading

ping_thread_started = False
_ping_lock = Lock()

def ensure_ping_thread():
    """ping_render を一度だけ起動する"""
    global ping_thread_started
    with _ping_lock:
        if not ping_thread_started:
            threading.Thread(target=ping_render, daemon=True).start()
            ping_thread_started = True
            print("[PING] background thread started", flush=True)

# Flask 3.x 用：最初のリクエスト時にだけ起動
@app.before_request
def _kickoff_ping():
    if not ping_thread_started:
        ensure_ping_thread()

# ローカル実行対策（gunicorn では __main__ にならないが、念のため）
if __name__ == "__main__":
    ensure_ping_thread()
    app.run(host="0.0.0.0", port=10000)


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
    try:
        rnd = request.args.get("round", "1st")
        sheet = spreadsheet.worksheet(f"Pairings_{rnd}")
        # 空セルは空文字にしておくと扱いが安定する
        records = sheet.get_all_records(default_blank="")

        # もう Players は毎回読まない（キャッシュを使う）
        code_to_name = cache["code_to_name"]

        groups = []
        for row in records:
            group = []
            group_number = row.get("Group")
            # Group が 1.0 や "1 " のような値でも扱えるようにしておく
            try:
                if group_number is not None and str(group_number).strip() != "":
                    group_number = int(float(str(group_number).strip()))
            except Exception:
                # 型変換できなくても致命ではないのでそのまま使う
                pass

            for i in range(1, 3+1):  # Code1..Code3
                code = row.get(f"Code{i}", "")
                choice = row.get(f"Choice{i}", "")
                code_str = str(code).strip()
                if code_str:
                    name = code_to_name.get(code_str, "不明")
                    group.append({
                        "name": name,
                        "code": code_str,
                        "choice": choice,
                        "group": group_number
                    })
            if group:
                groups.append(group)

        return render_template("index.html", groups=groups, selected_round=rnd)

    except Exception as e:
        import traceback
        print("ERROR in /:", e, traceback.format_exc(), flush=True)
        # 画面は 500 のままでOKだが、ログに原因が出るように
        return "Internal Server Error", 500




@app.route("/submit", methods=["POST"])
def submit():
    try:
        data = request.get_json()
        code = str(data["code"]).strip()
        group = int(str(data["group"]).strip())   # 型ズレ対策
        rnd = data["round"]                       # 変数名 round は組込と被るので避ける
        choice = data["choice"]

        sheet = spreadsheet.worksheet(f"Pairings_{rnd}")
        records = sheet.get_all_records()  # 1回だけ読む

        target_row_idx = None     # 2行目起点の行番号
        target_choice_col = None  # F/G/H のいずれか

        # 行・列を特定（型ズレ/空白に強く）
        for idx, row in enumerate(records, start=2):
            # Group を int に正規化して比較
            row_group = None
            try:
                row_group = int(str(row.get("Group")).strip())
            except Exception:
                pass

            if row_group == group:
                for i in range(1, 4):  # Code1..3 / Choice1..3
                    cell_code = str(row.get(f"Code{i}", "")).strip()
                    if cell_code and cell_code == code:
                        target_row_idx = idx
                        # Choice1..3 は列 F/G/H（E=5 → E+1=F, E+2=G, E+3=H）
                        target_choice_col = chr(ord("E") + i)
                        break
            if target_row_idx:
                break

        if not target_row_idx or not target_choice_col:
            return jsonify({"status": "not found"}), 404

        # 該当セルを書き込み（選択反映）
        # sheet.update(f"{target_choice_col}{target_row_idx}", [[choice]])

        # 既に読み込んだ records を使って集計（今変更したセルだけは choice を反映して数える）
        aim_count = 0
        noaim_count = 0
        for r_idx, row in enumerate(records, start=2):
            for j in range(1, 4):
                code_j = row.get(f"Code{j}")
                if not code_j:
                    continue

                val = str(row.get(f"Choice{j}", "")).strip()
                # さっき自分が更新したセルは最新 choice を使う
                if r_idx == target_row_idx and (chr(ord("E") + j) == target_choice_col):
                    val = choice

                if val == "狙う":
                    aim_count += 1
                elif val == "狙わない":
                    noaim_count += 1

        # ★ Pairings_* の J2:K2 に一発で書き込み（APIコール1回）
        # sheet.update("J2:K2", [[aim_count, noaim_count]])

        return jsonify({"status": "ok", "aim": aim_count, "noaim": noaim_count})

    except Exception as e:
        import traceback
        print("ERROR in /submit:", e, traceback.format_exc(), flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500



@app.route("/ping")
def ping():
    return "pong", 200
    

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

