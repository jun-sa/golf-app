from flask import Flask, render_template, request, jsonify
import gspread
import os
from google.oauth2.service_account import Credentials
from threading import Lock
import threading
import requests
import time

app = Flask(__name__)

# -----------------------------
# keep-alive 用 /ping を5分おきに叩く
# -----------------------------
def ping_render():
    while True:
        try:
            res = requests.get("https://golf-app-4i3n.onrender.com/ping", timeout=10)
            print(f"[PING] Status: {res.status_code}", flush=True)
        except Exception as e:
            print(f"[PING ERROR] {e}", flush=True)
        time.sleep(300)

# -----------------------------
# Google Sheets 認証
# -----------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
creds = Credentials.from_service_account_file(
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"], scopes=SCOPES
)
gc = gspread.authorize(creds)

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
spreadsheet = gc.open_by_key(SPREADSHEET_ID)

# -----------------------------
# Players キャッシュ（ヘッダーに依存しない読み方）
# -----------------------------
cache = {"Players": [], "code_to_name": {}, "lock": Lock()}

def load_player_cache():
    with cache["lock"]:
        sh = spreadsheet.worksheet("Players")
        rows = sh.get_values("A2:B")  # [['101','山田 太郎'], ...]  ヘッダー無視
        code_to_name = {}
        for r in rows:
            if not r:
                continue
            code = str(r[0]).strip() if len(r) > 0 else ""
            name = str(r[1]).strip() if len(r) > 1 else ""
            if code:
                code_to_name[code] = name
        cache["Players"] = rows
        cache["code_to_name"] = code_to_name

# 起動時に失敗してもサービスを落とさない
try:
    load_player_cache()
    print("[Players] cache loaded", flush=True)
except Exception as e:
    print("[WARN] load_player_cache failed:", e, flush=True)
    cache["Players"] = []
    cache["code_to_name"] = {}

# -----------------------------
# 画面表示
# -----------------------------
@app.route("/")
def index():
    round_ = request.args.get("round", "1st")
    sheet = spreadsheet.worksheet(f"Pairings_{round_}")
    # ヘッダー空欄でも落ちないよう固定ヘッダー名を指定
    records = sheet.get_all_records(
        expected_headers=["Group","Code1","Code2","Code3","Choice1","Choice2","Choice3"]
    )

    code_to_name = cache["code_to_name"]

    # 1行=1組（Code1..3 / Choice1..3）を展開
    groups = []
    for row in records:
        group = []
        group_number = row.get("Group")
        for i in range(1, 4):
            code = row.get(f"Code{i}")
            choice = row.get(f"Choice{i}")
            if code:
                group.append({
                    "name": code_to_name.get(str(code), "Unknown"),
                    "code": str(code),
                    "choice": choice,
                    "group": group_number,
                })
        if group:
            groups.append(group)

    return render_template("index.html", groups=groups, selected_round=round_)

# -----------------------------
# 選択反映（セル1か所だけ更新）
# -----------------------------
@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json()
    code = data["code"]
    group = int(data["group"])
    round_ = data["round"]
    choice = data["choice"]

    sheet = spreadsheet.worksheet(f"Pairings_{round_}")
    records = sheet.get_all_records(
        expected_headers=["Group","Code1","Code2","Code3","Choice1","Choice2","Choice3"]
    )

    target_row_idx = None
    target_col_letter = None

    # 対象セル（Choice列）を探す
    for idx, row in enumerate(records, start=2):  # 2行目からデータ
        if row.get("Group") == group:
            for i in range(1, 4):  # Code1..3
                if str(row.get(f"Code{i}")) == code:
                    target_row_idx = idx
                    # Choice1..3 は F..H 列（EがCode3 の次なので F=Choice1）
                    target_col_letter = chr(ord("E") + i)  # i=1→F, 2→G, 3→H
                    break
        if target_row_idx:
            break

    if not (target_row_idx and target_col_letter):
        return jsonify({"status": "not found"}), 404

    # 対象セルのみ更新（API 1回）
    sheet.update(f"{target_col_letter}{target_row_idx}", [[choice]])
    return jsonify({"status": "ok"})

# -----------------------------
# ping エンドポイント & 一度だけ起動
# -----------------------------
@app.route("/ping")
def ping():
    return "pong", 200

_ping_started = False
_ping_lock = Lock()

def ensure_ping_thread():
    global _ping_started
    with _ping_lock:
        if not _ping_started:
            threading.Thread(target=ping_render, daemon=True).start()
            _ping_started = True
            print("[PING] background thread started", flush=True)

@app.before_request
def _kickoff_ping():
    if not _ping_started:
        ensure_ping_thread()

if __name__ == "__main__":
    ensure_ping_thread()
    app.run(host="0.0.0.0", port=10000)
