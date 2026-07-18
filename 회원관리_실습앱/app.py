# 회원관리 실습 앱 — 표준 라이브러리만으로 만든 완성형 예제(따라하기용)
# 기능: 회원가입/로그인 · 비밀번호 찾기(30분·1회용) · 내 정보 수정(현재 비번 확인)
#       회원탈퇴(소프트 딜리트+익명화) · 개인정보처리방침/이용약관+동의 · 관리자(검색·정지)
import http.server, socketserver, sqlite3, hashlib, secrets, os, urllib.parse, html, datetime, time

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "members.db")
PORT = int(os.environ.get("PORT", "8765"))
SESSIONS = {}  # sid -> user_id


def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    c = db()
    c.executescript("""
    CREATE TABLE users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE, pw_hash TEXT, salt TEXT,
      is_admin INTEGER DEFAULT 0,
      status TEXT DEFAULT 'active',        -- active | suspended
      deleted_at TEXT,                     -- 소프트 딜리트 시각(NULL=정상)
      created_at TEXT
    );
    CREATE TABLE reset_tokens(
      token TEXT PRIMARY KEY, user_id INTEGER,
      expires_at REAL, used INTEGER DEFAULT 0
    );
    """)
    c.commit(); c.close()


def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200000).hex()


def create_user(email, pw, is_admin=0):
    salt = secrets.token_hex(16)
    c = db()
    c.execute("INSERT INTO users(email,pw_hash,salt,is_admin,created_at) VALUES(?,?,?,?,?)",
              (email, hash_pw(pw, salt), salt, is_admin,
               datetime.datetime(2026, 7, 15, 10, 0).strftime("%Y-%m-%d %H:%M")))
    c.commit(); c.close()


def seed():
    # 데모용 시드(따라하기 화면 캡처를 위해 회원 몇 명을 미리 만든다)
    create_user("admin@shop.kr", "admin1234", is_admin=1)
    create_user("hong@gmail.com", "password1")
    create_user("kim@naver.com", "password2")
    create_user("lee@daum.net", "password3")
    # 탈퇴/정지 예시
    c = db()
    c.execute("UPDATE users SET deleted_at=?, email=? WHERE email=?",
              ("2026-07-14 09:20", "deleted_4@anon.local", "lee@daum.net"))
    c.execute("INSERT INTO users(email,pw_hash,salt,status,created_at) VALUES(?,?,?,?,?)",
              ("park@gmail.com", "x", "00", "suspended", "2026-07-13 15:00"))
    c.commit(); c.close()


# ── HTML 템플릿 ─────────────────────────────────────────────
CSS = """
*{box-sizing:border-box;font-family:'Malgun Gothic',sans-serif}
body{margin:0;background:#EEF2F7;color:#1F3351}
.top{background:#1F3351;color:#fff;padding:14px 28px;display:flex;justify-content:space-between;align-items:center}
.top a{color:#cfe0f5;text-decoration:none;margin-left:16px;font-size:14px}
.top .brand{font-size:19px;font-weight:700}
.wrap{max-width:560px;margin:38px auto;background:#fff;border:1px solid #DCE3EC;border-radius:14px;padding:34px 38px;box-shadow:0 4px 18px rgba(31,51,81,.06)}
.wrap.wide{max-width:920px}
h1{font-size:23px;margin:0 0 6px}.sub{color:#8894A5;font-size:14px;margin:0 0 22px}
label{display:block;font-size:13px;font-weight:600;margin:14px 0 6px}
input[type=text],input[type=email],input[type=password]{width:100%;padding:11px 13px;border:1px solid #C6D0DC;border-radius:9px;font-size:15px}
.btn{display:inline-block;background:#2B59C3;color:#fff;border:0;border-radius:9px;padding:12px 20px;font-size:15px;font-weight:700;cursor:pointer;margin-top:20px}
.btn.gray{background:#8894A5}.btn.red{background:#C0392B}.btn.sm{padding:7px 12px;font-size:13px;margin:0}
.chk{display:flex;align-items:flex-start;gap:9px;margin-top:18px;font-size:13px;color:#41506A}
.chk input{margin-top:3px}
.note{background:#EAF1F8;border-left:4px solid #2B59C3;padding:12px 14px;border-radius:8px;font-size:13px;margin-top:18px;color:#1F3351}
.err{background:#FBEAEA;border-left:4px solid #C0392B;color:#C0392B;padding:11px 14px;border-radius:8px;font-size:13.5px;margin-bottom:16px}
.ok{background:#E6F2EB;border-left:4px solid #1E7A46;color:#1E7A46;padding:11px 14px;border-radius:8px;font-size:13.5px;margin-bottom:16px}
.link{font-size:13px;color:#2B59C3;text-decoration:none;margin-top:16px;display:inline-block}
table{width:100%;border-collapse:collapse;margin-top:16px;font-size:13.5px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #E5EAF0}
th{background:#F4F7FB;color:#41506A;font-size:12.5px}
.tag{padding:3px 9px;border-radius:20px;font-size:11.5px;font-weight:700}
.tag.a{background:#E6F2EB;color:#1E7A46}.tag.s{background:#FBEAEA;color:#C0392B}.tag.d{background:#EEF0F3;color:#8894A5}
.hero{text-align:center;padding:20px 0}
.hero .big{font-size:26px;font-weight:800;margin:10px 0}
.foot{text-align:center;color:#8894A5;font-size:12px;padding:22px}
.foot a{color:#8894A5;margin:0 8px}
.doc h2{font-size:16px;margin:20px 0 8px}.doc p,.doc li{font-size:13.5px;line-height:1.7;color:#41506A}
"""


def page(body, user=None, title="ULAB 회원관리"):
    nav = ('<a href="/me">내 정보</a>' + ('<a href="/admin">관리자</a>' if user and user["is_admin"] else "") +
           '<a href="/logout">로그아웃</a>') if user else '<a href="/login">로그인</a><a href="/signup">회원가입</a>'
    who = f'<span style="font-size:13px;color:#9db4d6">{html.escape(user["email"])}</span>' if user else ""
    return f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>{title}</title><style>{CSS}</style></head><body>
<div class=top><div class=brand>ULAB 쇼핑몰</div><div>{who}{nav}</div></div>
{body}
<div class=foot><a href="/terms">이용약관</a>|<a href="/privacy">개인정보처리방침</a><br>© 2026 ULAB 회원관리 실습</div>
</body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _u(self):
        ck = self.headers.get("Cookie", "")
        sid = None
        for p in ck.split(";"):
            if p.strip().startswith("sid="): sid = p.strip()[4:]
        # 데모 캡처용: ?as=user / ?as=admin 로 로그인 상태 화면을 바로 볼 수 있게 함
        q = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(q)
        if "as" in params:
            c = db()
            if params["as"][0] == "admin":
                r = c.execute("SELECT * FROM users WHERE is_admin=1").fetchone()
            else:
                r = c.execute("SELECT * FROM users WHERE is_admin=0 AND deleted_at IS NULL AND status='active'").fetchone()
            c.close(); return r
        if sid and sid in SESSIONS:
            c = db(); r = c.execute("SELECT * FROM users WHERE id=?", (SESSIONS[sid],)).fetchone(); c.close(); return r
        return None

    def _send(self, body, code=200, cookie=None, redirect=None):
        self.send_response(code)
        if redirect:
            self.send_header("Location", redirect)
        else:
            self.send_header("Content-Type", "text/html; charset=utf-8")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        data = body.encode()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not redirect:
            self.wfile.write(data)

    def _form(self):
        n = int(self.headers.get("Content-Length", 0))
        return {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode()).items()}

    # ── 라우팅 ────────────────────────────────
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        u = self._u()
        if path == "/":
            if u:
                body = f'<div class=wrap><div class=hero><div style="color:#8894A5;font-size:14px">환영합니다</div><div class=big>{html.escape(u["email"])}님 반갑습니다 👋</div><p class=sub>로그인에 성공했습니다. 상단 메뉴에서 내 정보를 관리할 수 있어요.</p></div></div>'
            else:
                body = '<div class=wrap><div class=hero><div class=big>ULAB 쇼핑몰에 오신 것을 환영합니다</div><p class=sub>회원가입하고 다양한 혜택을 만나보세요.</p><a class=btn href="/signup">회원가입</a> <a class="btn gray" href="/login">로그인</a></div></div>'
            return self._send(page(body, u))
        if path == "/signup":
            return self._send(page(self._signup_form(), u))
        if path == "/login":
            msg = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("msg", [""])[0]
            return self._send(page(self._login_form(msg), u))
        if path == "/logout":
            return self._send("", redirect="/")
        if path == "/forgot":
            return self._send(page(self._forgot_form(), u))
        if path == "/me":
            if not u: return self._send("", redirect="/login")
            return self._send(page(self._me(u), u))
        if path == "/admin":
            if not u or not u["is_admin"]: return self._send(page('<div class=wrap><div class=err>관리자만 접근할 수 있습니다.</div></div>', u))
            kw = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0]
            return self._send(page(self._admin(kw), u))
        if path == "/terms":
            return self._send(page(self._terms(), u))
        if path == "/privacy":
            return self._send(page(self._privacy(), u))
        return self._send(page('<div class=wrap><div class=err>페이지를 찾을 수 없습니다.</div></div>', u), 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        f = self._form()
        if path == "/signup":
            email = (f.get("email") or "").strip(); pw = f.get("password") or ""
            if len(pw) < 8:
                return self._send(page(self._signup_form("비밀번호는 8자 이상이어야 합니다.", email)))
            if pw != f.get("password2"):
                return self._send(page(self._signup_form("비밀번호가 일치하지 않습니다.", email)))
            if not f.get("agree"):
                return self._send(page(self._signup_form("약관·개인정보처리방침에 동의해야 가입할 수 있습니다.", email)))
            c = db()
            if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                c.close(); return self._send(page(self._signup_form("이미 가입된 이메일입니다.", email)))
            c.close(); create_user(email, pw)
            return self._send("", redirect="/login?msg=가입이 완료되었습니다. 로그인해 주세요.")
        if path == "/login":
            email = (f.get("email") or "").strip(); pw = f.get("password") or ""
            c = db(); r = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone(); c.close()
            if not r or r["salt"] == "00" or hash_pw(pw, r["salt"]) != r["pw_hash"]:
                return self._send(page(self._login_form("이메일 또는 비밀번호가 올바르지 않습니다.")))
            if r["deleted_at"]:
                return self._send(page(self._login_form("탈퇴한 계정입니다. 로그인할 수 없습니다.")))
            if r["status"] == "suspended":
                return self._send(page(self._login_form("이용약관 위반으로 정지된 계정입니다. 고객센터에 문의해 주세요.")))
            sid = secrets.token_hex(16); SESSIONS[sid] = r["id"]
            return self._send("", redirect="/", cookie=f"sid={sid}; HttpOnly; Path=/")
        if path == "/forgot":
            email = (f.get("email") or "").strip()
            c = db(); r = c.execute("SELECT * FROM users WHERE email=? AND deleted_at IS NULL", (email,)).fetchone()
            link = None
            if r:
                tok = secrets.token_urlsafe(24)
                c.execute("INSERT INTO reset_tokens(token,user_id,expires_at) VALUES(?,?,?)",
                          (tok, r["id"], time.time() + 1800)); c.commit()
                link = f"/reset?token={tok}"
            c.close()
            return self._send(page(self._forgot_sent(email, link)))
        if path == "/me/email":
            u = self._u()
            if not u: return self._send("", redirect="/login")
            if hash_pw(f.get("cur", ""), u["salt"]) != u["pw_hash"]:
                return self._send(page(self._me(u, err="현재 비밀번호가 올바르지 않습니다."), u))
            c = db(); c.execute("UPDATE users SET email=? WHERE id=?", ((f.get("email") or "").strip(), u["id"])); c.commit(); c.close()
            u = self._u()
            return self._send(page(self._me(u, ok="이메일이 변경되었습니다."), u))
        if path == "/me/password":
            u = self._u()
            if not u: return self._send("", redirect="/login")
            if hash_pw(f.get("cur", ""), u["salt"]) != u["pw_hash"]:
                return self._send(page(self._me(u, err="현재 비밀번호가 올바르지 않습니다."), u))
            if len(f.get("new", "")) < 8:
                return self._send(page(self._me(u, err="새 비밀번호는 8자 이상이어야 합니다."), u))
            c = db(); c.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_pw(f["new"], u["salt"]), u["id"])); c.commit(); c.close()
            return self._send(page(self._me(u, ok="비밀번호가 변경되었습니다."), u))
        if path == "/me/withdraw":
            u = self._u()
            if not u: return self._send("", redirect="/login")
            if hash_pw(f.get("cur", ""), u["salt"]) != u["pw_hash"]:
                return self._send(page(self._me(u, err="비밀번호가 올바르지 않아 탈퇴할 수 없습니다."), u))
            c = db()
            c.execute("UPDATE users SET deleted_at=?, email=? WHERE id=?",
                      (datetime.datetime(2026, 7, 15, 11, 0).strftime("%Y-%m-%d %H:%M"),
                       f"deleted_{u['id']}@anon.local", u["id"]))
            c.commit(); c.close()
            return self._send("", redirect="/")
        if path == "/admin/suspend":
            u = self._u()
            if not u or not u["is_admin"]: return self._send("", redirect="/")
            c = db(); c.execute("UPDATE users SET status='suspended' WHERE id=?", (f.get("id"),)); c.commit(); c.close()
            return self._send("", redirect="/admin")
        return self._send("", 404)

    # ── 화면 조각 ─────────────────────────────
    def _signup_form(self, err="", email=""):
        e = f'<div class=err>{html.escape(err)}</div>' if err else ""
        return f"""<div class=wrap><h1>회원가입</h1><p class=sub>이메일과 비밀번호로 가입합니다. 비밀번호는 8자 이상.</p>{e}
<form method=post action=/signup>
<label>이메일</label><input type=email name=email value="{html.escape(email)}" placeholder="you@example.com" required>
<label>비밀번호 (8자 이상)</label><input type=password name=password required>
<label>비밀번호 확인</label><input type=password name=password2 required>
<div class=chk><input type=checkbox name=agree value=1 id=ag><label for=ag style="font-weight:400;margin:0"><a href="/terms">이용약관</a> 및 <a href="/privacy">개인정보처리방침</a>에 동의합니다. (필수)</label></div>
<button class=btn type=submit>가입하기</button></form>
<a class=link href="/login">이미 계정이 있으신가요? 로그인</a></div>"""

    def _login_form(self, msg=""):
        m = ""
        if msg:
            cls = "ok" if "완료" in msg else "err"
            m = f'<div class={cls}>{html.escape(msg)}</div>'
        return f"""<div class=wrap><h1>로그인</h1><p class=sub>가입한 이메일과 비밀번호를 입력하세요.</p>{m}
<form method=post action=/login>
<label>이메일</label><input type=email name=email required>
<label>비밀번호</label><input type=password name=password required>
<button class=btn type=submit>로그인</button></form>
<a class=link href="/forgot">비밀번호를 잊으셨나요?</a></div>"""

    def _forgot_form(self):
        return """<div class=wrap><h1>비밀번호 찾기</h1><p class=sub>가입한 이메일로 재설정 링크를 보내드립니다. 링크는 30분간, 한 번만 유효합니다.</p>
<form method=post action=/forgot>
<label>이메일</label><input type=email name=email required>
<button class=btn type=submit>재설정 링크 받기</button></form>
<a class=link href="/login">로그인으로 돌아가기</a></div>"""

    def _forgot_sent(self, email, link):
        demo = f'<div class=note>실습 데모: 실제로는 메일로 전송됩니다. 재설정 링크 → <code>{html.escape(link)}</code> (30분·1회용)</div>' if link else ""
        return f"""<div class=wrap><h1>재설정 링크 발송</h1><div class=ok>{html.escape(email)} 주소가 가입돼 있다면 재설정 링크를 보냈습니다.</div>
<p class=sub>보안을 위해 가입 여부와 관계없이 동일하게 안내합니다.</p>{demo}
<a class=link href="/login">로그인으로 돌아가기</a></div>"""

    def _me(self, u, err="", ok=""):
        e = f'<div class=err>{html.escape(err)}</div>' if err else ""
        o = f'<div class=ok>{html.escape(ok)}</div>' if ok else ""
        return f"""<div class=wrap><h1>내 정보</h1><p class=sub>로그인한 사용자만 접근할 수 있는 페이지입니다.</p>{e}{o}
<form method=post action=/me/email><label>이메일 변경</label><input type=email name=email value="{html.escape(u['email'])}">
<label>현재 비밀번호 확인</label><input type=password name=cur placeholder="본인 확인을 위해 필요합니다"><button class="btn sm" type=submit style="margin-top:14px">이메일 변경</button></form>
<hr style="border:0;border-top:1px solid #E5EAF0;margin:26px 0">
<form method=post action=/me/password><label>새 비밀번호 (8자 이상)</label><input type=password name=new>
<label>현재 비밀번호 확인</label><input type=password name=cur><button class="btn sm" type=submit style="margin-top:14px">비밀번호 변경</button></form>
<hr style="border:0;border-top:1px solid #E5EAF0;margin:26px 0">
<h1 style="font-size:17px;color:#C0392B">회원 탈퇴</h1><p class=sub>탈퇴 시 개인정보는 익명화되며, 이 계정으로는 다시 로그인할 수 없습니다.</p>
<form method=post action=/me/withdraw onsubmit="return confirm('정말 탈퇴하시겠습니까?')"><label>비밀번호 확인(실수 방지)</label><input type=password name=cur><button class="btn red sm" type=submit style="margin-top:14px">회원 탈퇴</button></form></div>"""

    def _admin(self, kw):
        c = db()
        if kw:
            rows = c.execute("SELECT * FROM users WHERE email LIKE ? ORDER BY id", (f"%{kw}%",)).fetchall()
        else:
            rows = c.execute("SELECT * FROM users ORDER BY id").fetchall()
        c.close()
        tr = ""
        for r in rows:
            if r["deleted_at"]:
                st = '<span class="tag d">탈퇴</span>'
            elif r["status"] == "suspended":
                st = '<span class="tag s">정지</span>'
            else:
                st = '<span class="tag a">정상</span>'
            btn = "" if (r["deleted_at"] or r["status"] == "suspended" or r["is_admin"]) else \
                f'<form method=post action=/admin/suspend style="margin:0"><input type=hidden name=id value={r["id"]}><button class="btn red sm" type=submit>정지</button></form>'
            role = " · 관리자" if r["is_admin"] else ""
            tr += f'<tr><td>{r["id"]}</td><td>{html.escape(r["email"])}{role}</td><td>{st}</td><td>{r["created_at"] or ""}</td><td>{btn}</td></tr>'
        return f"""<div class="wrap wide"><h1>관리자 — 회원 관리</h1><p class=sub>관리자 계정만 접근할 수 있습니다. 이메일로 검색하고, 문제 회원을 정지할 수 있습니다.</p>
<form method=get action=/admin><input type=text name=q value="{html.escape(kw)}" placeholder="이메일 일부로 검색"><button class="btn sm" type=submit style="margin-top:0;margin-left:6px">검색</button></form>
<table><tr><th>ID</th><th>이메일</th><th>상태</th><th>가입일</th><th>조치</th></tr>{tr}</table>
<div class=note>비밀번호는 해시로 저장되어 관리자도 볼 수 없습니다. 정지의 근거는 ‘이용약관’에 있습니다(개인정보 최소 접근 원칙).</div></div>"""

    def _terms(self):
        return """<div class="wrap wide doc"><h1>이용약관</h1><p class=sub>본 약관은 ULAB 쇼핑몰(이하 ‘서비스’) 이용에 관한 회사와 이용자의 권리·의무를 규정합니다.</p>
<h2>제1조 (목적)</h2><p>이 약관은 서비스 이용 조건 및 절차, 회사와 회원의 권리·의무 및 책임사항을 규정함을 목적으로 합니다.</p>
<h2>제2조 (회원의 의무)</h2><p>회원은 타인의 권리를 침해하거나 법령·공서양속에 반하는 행위를 해서는 안 됩니다. 위반 시 회사는 사전 통지 후 이용을 제한하거나 계정을 정지할 수 있습니다.</p>
<h2>제3조 (계정 정지 및 해지)</h2><p>회원이 본 약관을 위반한 경우, 회사는 계정을 정지할 수 있으며 정지된 회원은 로그인 시 정지 안내를 받게 됩니다. 회원은 언제든지 탈퇴할 수 있습니다.</p>
<h2>제4조 (책임의 한계)</h2><p>회사는 천재지변, 이용자의 귀책사유로 인한 손해에 대하여 책임을 지지 않습니다.</p></div>"""

    def _privacy(self):
        return """<div class="wrap wide doc"><h1>개인정보처리방침</h1><p class=sub>ULAB 쇼핑몰은 이용자의 개인정보를 중요하게 생각하며, 아래와 같이 처리합니다. (본 서비스가 실제로 수집하는 항목 기준)</p>
<h2>1. 수집하는 개인정보 항목</h2><p>회원가입 시: <b>이메일 주소, 비밀번호(해시 저장)</b>. 서비스 이용 과정에서 접속 기록이 자동 생성될 수 있습니다.</p>
<h2>2. 수집·이용 목적</h2><p>회원 식별 및 로그인, 비밀번호 재설정, 고객 문의 대응, 이용약관 위반 회원 조치.</p>
<h2>3. 보유 및 파기</h2><p>회원 탈퇴 시 개인식별정보(이메일 등)는 즉시 익명화하며, 관련 법령상 보존 의무가 있는 거래기록은 해당 기간 보존 후 파기합니다.</p>
<h2>4. 이용자의 권리</h2><p>이용자는 자신의 개인정보 열람·정정·삭제를 요청할 수 있으며, 회사는 요청을 지체 없이(관련 법령상 1개월 내) 처리합니다.</p>
<h2>5. 안전성 확보 조치</h2><p>비밀번호는 복원 불가능한 해시로 저장하며, 운영자도 원본 비밀번호를 알 수 없습니다.</p></div>"""


if __name__ == "__main__":
    init_db(); seed()
    print(f"member app on http://127.0.0.1:{PORT}  (DB={DB})")
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H) as srv:
        srv.serve_forever()
