import hashlib
import io
import os
import secrets
import sqlite3
from datetime import datetime

import qrcode
from flask import (Flask, Response, abort, redirect, render_template_string,
                   request, session, url_for)

BASE_URL = os.environ.get("BASE_URL", "https://bobbie-ungalvanized-tatiana.ngrok-free.dev").rstrip("/")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me")
# База лежит в ./data рядом с app.py. Если на Railway подключён том,
# берём его путь (RAILWAY_VOLUME_MOUNT_PATH). DB_PATH переопределяет всё.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.environ.get("DB_PATH") or os.path.join(DATA_DIR, "certs.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=BASE_URL.startswith("https"))


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS certs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            used_at TEXT)""")
        # Заранее выданные одноразовые QR: PRESET_TOKEN_HASHES=hash1,hash2
        # (в окружении только хэши, сами токены есть только в QR)
        for i, th in enumerate(filter(None, os.environ.get("PRESET_TOKEN_HASHES", "").split(","))):
            c.execute("INSERT OR IGNORE INTO certs(name,token_hash,created_at) VALUES(?,?,?)",
                      (f"Одноразовый сертификат #{i + 1}", th.strip().lower(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def is_admin():
    return session.get("admin") is True


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


STYLE = """
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;max-width:560px;margin:24px auto;padding:0 16px;color:#222}
input,button{font-size:16px;padding:10px;border-radius:8px;border:1px solid #bbb}
button{background:#222;color:#fff;border:0;cursor:pointer}
.box{padding:20px;border-radius:12px;text-align:center;font-size:22px;margin:16px 0}
.ok{background:#d9f7e0;color:#106b2a}.bad{background:#fde0e0;color:#a11}.warn{background:#fff3cd;color:#7a5b00}
table{width:100%;border-collapse:collapse}td,th{padding:6px;border-bottom:1px solid #eee;text-align:left;font-size:14px}
a{color:#06c}.row{display:flex;gap:8px}.row input{flex:1}
</style>"""

LOGIN = STYLE + """<h2>Вход администратора</h2>
{% if err %}<p style=color:#a11>Неверный пароль</p>{% endif %}
<form method=post class=row><input type=password name=password placeholder=Пароль autofocus>
<button>Войти</button></form>"""

ADMIN = STYLE + """<script src="https://unpkg.com/html5-qrcode"></script>
<h2>Проверка сертификатов</h2>
<p><a href="/logout">Выйти</a></p>
<label><input type=checkbox id=consume checked style="width:auto"> Погасить QR после скана</label>
<div id=reader style="margin:12px 0"></div>
<div id=result></div>
<h3>Новый сертификат</h3>
<form method=post action="/create" class=row><input name=name placeholder="Имя / номер сертификата" required>
<button>Создать</button></form>
<h3>Список</h3>
<table><tr><th>#</th><th>Название</th><th>Статус</th></tr>
{% for c in certs %}<tr><td>{{c.id}}</td><td>{{c.name}}</td>
<td>{% if c.used_at %}использован {{c.used_at}}{% else %}действителен{% endif %}</td></tr>{% endfor %}</table>
<script>
let busy=false;
function extract(t){const m=t.match(/\\/v\\/([A-Za-z0-9_-]+)/);return m?m[1]:t.trim();}
async function check(text){
  if(busy)return;busy=true;
  const r=await fetch('/api/check',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({token:extract(text),consume:document.getElementById('consume').checked})});
  const d=await r.json();
  document.getElementById('result').innerHTML='<div class="box '+d.cls+'">'+d.message+'</div>';
  setTimeout(()=>busy=false,2500);
}
new Html5QrcodeScanner('reader',{fps:10,qrbox:250},false).render(check,()=>{});
</script>"""

RESULT = STYLE + """<div class="box {{cls}}">{{message}}</div>
<p><a href="/">В панель администратора</a></p>"""


def evaluate(token, consume):
    row = db().execute("SELECT * FROM certs WHERE token_hash=?", (h(token),)).fetchone()
    if not row:
        return "bad", "❌ Недействителен: сертификат не найден"
    if row["used_at"]:
        return "bad", f"❌ Недействителен: «{row['name']}» уже использован {row['used_at']}"
    if consume:
        with db() as c:
            cur = c.execute("UPDATE certs SET used_at=? WHERE id=? AND used_at IS NULL", (now(), row["id"]))
            if cur.rowcount == 0:  # гонка: кто-то успел раньше
                return "bad", "❌ Недействителен: уже использован"
        return "ok", f"✅ Действителен: «{row['name']}». QR теперь погашен"
    return "warn", f"✅ Действителен: «{row['name']}» (не погашен)"


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(url_for("index"))
        return render_template_string(LOGIN, err=True), 401
    if not is_admin():
        return render_template_string(LOGIN, err=False)
    certs = db().execute("SELECT * FROM certs ORDER BY id DESC").fetchall()
    return render_template_string(ADMIN, certs=certs)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/create", methods=["POST"])
def create():
    if not is_admin():
        abort(403)
    token = secrets.token_urlsafe(16)
    with db() as c:
        c.execute("INSERT INTO certs(name,token_hash,created_at) VALUES(?,?,?)",
                  (request.form["name"].strip()[:200], h(token), now()))
    # токен показывается один раз — в хэше его не восстановить
    link = f"{BASE_URL}/v/{token}"
    return render_template_string(
        STYLE + "<h2>Сертификат создан</h2><p>QR (сохраните/распечатайте, повторно он не покажется):</p>"
        "<img src='/qr.png?d={{d}}' width=260><p style='word-break:break-all;font-size:13px'>{{link}}</p>"
        "<p><a href='/'>Назад</a></p>", d=link, link=link)


@app.route("/qr.png")
def qr_png():
    if not is_admin():
        abort(403)
    img = qrcode.make(request.args.get("d", ""), box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Response(buf.getvalue(), mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.route("/v/<token>")
def verify(token):
    """Сюда ведёт QR. Не-админ ничего не гасит и ничего не узнаёт."""
    if not is_admin():
        return render_template_string(RESULT, cls="warn",
                                      message="Проверять сертификаты может только администратор."), 403
    cls, msg = evaluate(token, consume=True)
    return render_template_string(RESULT, cls=cls, message=msg)


@app.route("/api/check", methods=["POST"])
def api_check():
    if not is_admin():
        abort(403)
    d = request.get_json(force=True)
    cls, msg = evaluate(str(d.get("token", "")), bool(d.get("consume", True)))
    return {"cls": cls, "message": msg}


init()
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    try:
        from waitress import serve  # чистый Python WSGI-сервер, годится для продакшена
        serve(app, host="0.0.0.0", port=port, threads=4)
    except ImportError:
        app.run(host="0.0.0.0", port=port)