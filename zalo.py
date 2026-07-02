# api/zalo.py
import os
import re
import time
import json
import uuid
import base64
import hashlib
import traceback
import logging
from io import BytesIO
from flask import Flask, request, jsonify, session as flask_session
import requests

app = Flask(__name__)
# В продакшене замените на стойкий секретный ключ
app.secret_key = os.environ.get("SECRET_KEY", "zalo-survival-secret-key-change-me")
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True

# Логирование для отладки
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (адаптированы из предоставленной логики)
# ------------------------------------------------------------

def get_session():
    """Возвращает requests.Session из Flask-сессии или создает новую."""
    if 'session_cookies' not in flask_session:
        flask_session['session_cookies'] = {}
        flask_session['user_agent'] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        flask_session['imei'] = None
        flask_session['login_step'] = 'init'
    s = requests.Session()
    # Восстанавливаем куки, если они есть
    for name, value in flask_session['session_cookies'].items():
        s.cookies.set(name, value)
    return s

def save_session(session):
    """Сохраняет куки requests.Session в Flask-сессию."""
    flask_session['session_cookies'] = session.cookies.get_dict()
    flask_session.modified = True

def get_user_agent():
    return flask_session.get('user_agent', "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

def get_qr_post_headers(user_agent):
    return {
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://id.zalo.me/account?continue=https%3A%2F%2Fzalo.me%2Fpc",
        "User-Agent": user_agent,
    }

def generate_imei(user_agent):
    imei_uuid = str(uuid.uuid4())
    imei_hash = hashlib.md5(user_agent.encode()).hexdigest()
    imei = f"{imei_uuid}-{imei_hash}"
    flask_session['imei'] = imei
    return imei

# ------------------------------------------------------------
# ЭТАПЫ QR-ЛОГИНА (транслированы из python-кода)
# ------------------------------------------------------------

def qr_load_login_page(session):
    url = "https://id.zalo.me/account?continue=https%3A%2F%2Fchat.zalo.me%2F"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Referer": "https://chat.zalo.me/",
        "User-Agent": get_user_agent(),
    }
    resp = session.get(url, headers=headers)
    resp.raise_for_status()
    html = resp.text
    match = re.search(r"https:\/\/stc-zlogin\.zdn\.vn\/main-([\d.]+)\.js", html)
    return match.group(1) if match else None

def qr_get_login_info(session, version):
    url = "https://id.zalo.me/account/logininfo"
    headers = get_qr_post_headers(get_user_agent())
    data = {"continue": "https://zalo.me/pc", "v": version}
    resp = session.post(url, headers=headers, data=data)
    resp.raise_for_status()
    return resp.json()

def qr_verify_client(session, version):
    url = "https://id.zalo.me/account/verify-client"
    headers = get_qr_post_headers(get_user_agent())
    data = {"type": "device", "continue": "https://zalo.me/pc", "v": version}
    resp = session.post(url, headers=headers, data=data)
    resp.raise_for_status()
    return resp.json()

def qr_generate(session, version):
    url = "https://id.zalo.me/account/authen/qr/generate"
    headers = get_qr_post_headers(get_user_agent())
    data = {"continue": "https://zalo.me/pc", "v": version}
    resp = session.post(url, headers=headers, data=data)
    resp.raise_for_status()
    result = resp.json()
    if result.get("error_code") != 0:
        raise Exception(f"QR generation failed: {result.get('error_message')}")
    return result.get("data")

def qr_wait_for_scan(session, version, code, timeout=100):
    url = "https://id.zalo.me/account/authen/qr/waiting-scan"
    headers = get_qr_post_headers(get_user_agent())
    data = {"code": code, "continue": "https://chat.zalo.me/", "v": version}
    # ВАЖНО: Мы не можем держать соединение открытым 100 секунд в serverless-функции.
    # Поэтому здесь мы делаем однократную проверку, а фронтенд будет опрашивать нас.
    resp = session.post(url, headers=headers, data=data, timeout=5)
    resp.raise_for_status()
    result = resp.json()
    return result

def qr_wait_for_confirm(session, version, code, timeout=100):
    url = "https://id.zalo.me/account/authen/qr/waiting-confirm"
    headers = get_qr_post_headers(get_user_agent())
    data = {
        "code": code, "gToken": "", "gAction": "CONFIRM_QR",
        "continue": "https://chat.zalo.me/", "v": version
    }
    resp = session.post(url, headers=headers, data=data, timeout=5)
    resp.raise_for_status()
    result = resp.json()
    return result

def qr_check_session(session):
    url = "https://id.zalo.me/account/checksession?continue=https%3A%2F%2Fchat.zalo.me%2Findex.html"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Referer": "https://id.zalo.me/account?continue=https%3A%2F%2Fchat.zalo.me%2F",
        "User-Agent": get_user_agent(),
    }
    resp = session.get(url, headers=headers)
    resp.raise_for_status()
    return resp

def qr_get_user_info(session):
    url = "https://jr.chat.zalo.me/jr/userinfo"
    headers = {
        "Accept": "*/*",
        "Referer": "https://chat.zalo.me/",
        "User-Agent": get_user_agent(),
    }
    resp = session.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def finalize_login_session(session):
    """Получает IMEI и секретные ключи, как в исходной логике."""
    user_agent = get_user_agent()
    imei = generate_imei(user_agent)
    url = f"https://wpa.chat.zalo.me/api/login/getLoginInfo?imei={imei}&type=30&client_version=650&ts={int(time.time()*1000)}"
    resp = session.get(url, headers={"User-Agent": user_agent})
    resp.raise_for_status()
    data = resp.json()
    if data.get("error_code") == 0 and "data" in data:
        login_data = data["data"]
        # Сохраняем конфиг
        flask_session['config'] = {
            "phone_number": login_data.get("phone_number"),
            "secret_key": login_data.get("zpw_enk"),
            "send2me_id": str(login_data.get("uid")),
            "zpw_ws": login_data.get("zpw_ws"),
        }
        flask_session['uid'] = flask_session['config']['send2me_id']
        flask_session['logged_in'] = True
        return flask_session['config']
    else:
        raise Exception(f"GetLoginInfo failed: {data.get('error_message')}")

# ------------------------------------------------------------
# API-МАРШРУТЫ ДЛЯ ФРОНТЕНДА
# ------------------------------------------------------------

@app.route('/api/zalo/start-login', methods=['POST'])
def start_login():
    """Инициализирует сессию и возвращает base64 QR-кода."""
    try:
        session = get_session()
        version = qr_load_login_page(session)
        if not version:
            return jsonify({"error": "Не удалось определить версию логина Zalo"}), 500
        flask_session['login_version'] = version

        qr_get_login_info(session, version)
        qr_verify_client(session, version)
        qr_data = qr_generate(session, version)
        
        qr_code = qr_data.get("code")
        qr_image_b64 = qr_data.get("image", "").replace("data:image/png;base64,", "")
        if not (qr_code and qr_image_b64):
            return jsonify({"error": f"Сбой генерации QR: {qr_data}"}), 500

        flask_session['qr_code'] = qr_code
        flask_session['login_step'] = 'waiting_scan'
        save_session(session)
        
        return jsonify({"qr_code": qr_code, "qr_image": qr_image_b64})
    except Exception as e:
        logger.error(f"Ошибка старта логина: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/zalo/check-scan', methods=['POST'])
def check_scan():
    """Проверяет, отсканирован ли QR-код (вызывается фронтендом в цикле)."""
    try:
        session = get_session()
        version = flask_session.get('login_version')
        qr_code = flask_session.get('qr_code')
        if not version or not qr_code:
            return jsonify({"error": "Нет активной сессии логина"}), 400
        
        result = qr_wait_for_scan(session, version, qr_code)
        save_session(session)
        
        if result.get("error_code") == 0 and result.get("data"):
            display_name = result["data"].get("display_name", "Неизвестный")
            flask_session['login_step'] = 'waiting_confirm'
            return jsonify({"status": "scanned", "display_name": display_name})
        elif result.get("error_code") == 8:
            return jsonify({"status": "waiting_scan"})
        else:
            return jsonify({"status": "error", "message": result.get("error_message")})
    except Exception as e:
        logger.error(f"Ошибка проверки скана: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/zalo/check-confirm', methods=['POST'])
def check_confirm():
    """Проверяет, подтвержден ли вход на телефоне."""
    try:
        session = get_session()
        version = flask_session.get('login_version')
        qr_code = flask_session.get('qr_code')
        if not version or not qr_code:
            return jsonify({"error": "Нет активной сессии логина"}), 400
        
        result = qr_wait_for_confirm(session, version, qr_code)
        save_session(session)
        
        if result.get("error_code") == 0:
            # Подтверждение успешно, завершаем логин
            qr_check_session(session)
            user_info = qr_get_user_info(session)
            if not user_info.get("data", {}).get("logged"):
                return jsonify({"status": "error", "message": "Финальная проверка сессии не удалась"}), 500
            
            config = finalize_login_session(session)
            save_session(session)
            
            # Формируем ответ с данными IMEI и Cookies
            cookies_for_output = session.cookies.get_dict()
            
            return jsonify({
                "status": "confirmed",
                "user_name": user_info['data']['info']['name'],
                "imei": flask_session.get('imei'),
                "cookies_python": cookies_for_output,
                "cookies_js_format": generate_js_cookie_format(cookies_for_output, flask_session.get('imei'))
            })
        elif result.get("error_code") == -13:
            flask_session['login_step'] = 'init'
            return jsonify({"status": "declined", "message": "Вход отклонен на телефоне"})
        elif result.get("error_code") == 8:
            return jsonify({"status": "waiting_confirm"})
        else:
            return jsonify({"status": "error", "message": result.get("error_message")})
    except Exception as e:
        logger.error(f"Ошибка подтверждения: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

def generate_js_cookie_format(cookies_dict, imei):
    """Генерирует формат cookies, аналогичный JS-коду."""
    cookies_list = []
    for name, value in cookies_dict.items():
        if name == "zpw_sek":
            cookies_list.append({
                "domain": ".chat.zalo.me",
                "expirationDate": None,
                "hostOnly": False,
                "httpOnly": True,
                "name": name,
                "path": "/",
                "sameSite": "no_restriction",
                "secure": True,
                "session": True,
                "storeId": "0",
                "value": value
            })
        else:
            cookies_list.append({"name": name, "value": value})
    return {
        "url": "https://chat.zalo.me",
        "cookies": cookies_list
    }

@app.route('/api/zalo/status', methods=['GET'])
def get_status():
    """Возвращает текущий статус сессии."""
    return jsonify({
        "step": flask_session.get('login_step', 'init'),
        "logged_in": flask_session.get('logged_in', False),
        "uid": flask_session.get('uid')
    })

# Для Vercel:
app = app

if __name__ == '__main__':
    app.run(debug=True)
