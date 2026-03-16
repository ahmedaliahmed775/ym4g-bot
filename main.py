import os
import time
import re
import threading
import json
import base64
import hashlib
import requests
import logging
import telebot
from telebot import TeleBot

# ================= الإعدادات =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8651111573:AAFUnC1pLioFKdPxLmk_7GA54-KkGCNvcNk")
CHAT_ID = os.getenv("CHAT_ID", "1330666633")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "101145238")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "3600"))   # افتراضياً كل ساعة
LOW_BALANCE_KEYWORD = os.getenv("LOW_BALANCE_KEYWORD", "1") # للتنبيه إذا صار أقل من 1 جيجا تقريباً

telebot.logger.setLevel(logging.CRITICAL)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

bot = TeleBot(BOT_TOKEN)

proxy_list = []
last_low_balance_alert = None
last_report_sent = None


def get_free_yemen_proxies():
    proxies = []
    sources = [
        "https://proxyscrape.com/free-proxy-list/yemen",
        "https://www.proxynova.com/proxy-server-list/country-ye/",
        "https://spys.one/free-proxy-list/YE/"
    ]

    for url in sources:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, headers=headers, timeout=10)
            found = re.findall(r'\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}', res.text)
            proxies.extend(found)
        except Exception:
            continue

    return list(set(proxies))


def solve_altcha(challenge_json):
    salt = challenge_json.get("salt", "")
    target = challenge_json.get("challenge", "")

    for number in range(1000000):
        text = salt + str(number)
        hash_result = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if hash_result == target:
            payload = {
                "algorithm": "SHA-256",
                "challenge": target,
                "number": number,
                "salt": salt,
                "signature": challenge_json.get("signature", "")
            }
            return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    return None


def parse_balance_text(report_text):
    internet_balance = None

    match = re.search(r'رصيد الإنترنت:\s*(.+)', report_text)
    if match:
        internet_balance = match.group(1).strip()

    return internet_balance


def is_low_balance(balance_text):
    if not balance_text:
        return False

    text = balance_text.replace("جيجا", "").replace("GB", "").strip()

    num_match = re.search(r'(\d+(?:\.\d+)?)', text)
    if not num_match:
        return False

    try:
        value = float(num_match.group(1))
        return value <= 1.0
    except Exception:
        return False


def get_balance_with_retry():
    global proxy_list

    if not proxy_list:
        proxy_list = get_free_yemen_proxies()

    max_attempts = min(len(proxy_list), 5) if proxy_list else 1

    for _ in range(max_attempts + 1):
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})

        proxy_config = None
        if proxy_list:
            p = proxy_list.pop(0)
            proxy_config = {"http": f"http://{p}", "https": f"http://{p}"}
            session.proxies.update(proxy_config)
            logging.info(f"Trying proxy: {p}")

        try:
            res = session.get("https://ptc.gov.ye/?page_id=9017", timeout=15)

            if "challengeurl" not in res.text:
                if proxy_config:
                    logging.warning("Proxy did not bypass site restriction, trying next.")
                    continue
                return "⚠️ الموقع لا يفتح من هذا الـ IP أو يتطلب IP مناسب."

            match = re.search(r'challengeurl="([^"]+)"', res.text)
            if not match:
                return "⚠️ تعذر العثور على challengeurl."

            challenge_url = match.group(1).replace("&amp;", "&")
            if not challenge_url.startswith("http"):
                challenge_url = "https://ptc.gov.ye" + challenge_url

            challenge_res = session.get(challenge_url, timeout=15)
            altcha_payload = solve_altcha(challenge_res.json())

            if not altcha_payload:
                return "⚠️ تعذر حل Altcha."

            hidden_inputs = re.findall(
                r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"',
                res.text
            )
            data = {name: value for name, value in hidden_inputs}
            data.update({
                "phone4gidnew": PHONE_NUMBER,
                "security_token_4gbill": altcha_payload,
                "qsubmitnew": "استعلام"
            })

            post_res = session.post("https://ptc.gov.ye/?page_id=9017", data=data, timeout=15)

            if "تجاوزت عدد مرات الاستعلام" in post_res.text:
                return "⏳ الموقع يطلب الانتظار بسبب كثرة المحاولات."

            table_match = re.search(
                r'<table class="transdetail"[^>]*>(.*?)</table>',
                post_res.text,
                re.DOTALL | re.IGNORECASE
            )

            if table_match:
                table_html = table_match.group(1)
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
                info = []

                for row in rows:
                    cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL | re.IGNORECASE)
                    if len(cells) >= 2:
                        key = re.sub(r'<[^>]+>', '', cells[0]).strip()
                        val = re.sub(r'<[^>]+>', '', cells[1]).strip()

                        if "رصيد الحساب" in key or "الرصيد المالي" in key:
                            info.append(f"💰 الرصيد المالي: {val}")
                        elif "الرصيد المتاح" in key or "رصيد الإنترنت" in key:
                            info.append(f"🌐 رصيد الإنترنت: {val}")
                        elif "تاريخ انتهاء" in key:
                            info.append(f"🗓️ تاريخ الانتهاء: {val}")

                if info:
                    return "\n".join(info)

            msg_match = re.search(
                r'<div[^>]*id="qbillmsgnew"[^>]*>(.*?)</div>',
                post_res.text,
                re.DOTALL | re.IGNORECASE
            )
            if msg_match:
                clean_msg = re.sub(r'<[^>]+>', '', msg_match.group(1)).strip()
                return f"⚠️ رسالة الموقع: {clean_msg}"

        except Exception as e:
            logging.error(f"Attempt failed: {e}")
            continue

    return "❌ فشل الاستعلام بعد عدة محاولات. قد تكون البروكسيات المجانية غير صالحة حالياً."


def auto_report():
    global last_low_balance_alert, last_report_sent

    while True:
        try:
            report = get_balance_with_retry()
            logging.info(report)

            if "💰" in report or "🌐" in report:
                if report != last_report_sent:
                    bot.send_message(CHAT_ID, f"📊 تقرير الرصيد:\n\n{report}")
                    last_report_sent = report

                balance_text = parse_balance_text(report)
                if is_low_balance(balance_text):
                    if balance_text != last_low_balance_alert:
                        bot.send_message(CHAT_ID, f"🚨 تنبيه: رصيد الإنترنت منخفض\n\n{report}")
                        last_low_balance_alert = balance_text
            else:
                bot.send_message(CHAT_ID, report)

        except Exception as e:
            logging.error(f"auto_report error: {e}")

        time.sleep(CHECK_INTERVAL)


@bot.message_handler(commands=["start"])
def start_message(message):
    bot.reply_to(
        message,
        "أهلاً بك\n\n"
        "الأوامر المتاحة:\n"
        "/check - فحص الرصيد الآن\n"
        ". - فحص سريع\n"
    )


@bot.message_handler(commands=["check"])
def check_balance(message):
    bot.reply_to(message, "⏳ جاري فحص الرصيد...")
    result = get_balance_with_retry()
    bot.send_message(message.chat.id, result)


@bot.message_handler(func=lambda message: message.text == ".")
def manual_check(message):
    bot.reply_to(message, "⏳ جاري محاولة جلب الرصيد...")
    result = get_balance_with_retry()
    bot.send_message(message.chat.id, result)


if __name__ == "__main__":
    print("البوت يعمل الآن...")
    threading.Thread(target=auto_report, daemon=True).start()
    bot.polling(none_stop=True, interval=1, timeout=30)
