import time
import uuid
import hmac
import hashlib
import base64
import requests
import threading
import random
import telebot
from telebot import TeleBot

# ================= الإعدادات =================
BOT_TOKEN = "8651111573:AAFUnC1pLioFKdPxLmk_7GA54-KkGCNvcNk"
CHAT_ID = "1330666633"
PHONE_NUMBER = "101145238"
CHECK_INTERVAL = 3600  # الفحص كل ساعة

# إعدادات API موقع adsl-yemen.com 
SUPABASE_URL = "https://kgowhsapgrolcyuiqwzf.supabase.co/functions/v1/telecom-inquiry"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imtnb3doc2FwZ3JvbGN5dWlxd3pmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjYyNTYxNzgsImV4cCI6MjA4MTgzMjE3OH0.3aHxxmaoWswxhzMAcc1aRas02bNnpxbPtf85JtCNe7I"
HMAC_SECRET = "X7k9mP2vQ4wR8tY1uN3bF6hJ0cL5dS9aE2gI4oK7nM"

bot = TeleBot(BOT_TOKEN)

def get_random_proxy():
    """جلب بروكسي عشوائي لتغيير الـ IP وتخطي الحظر"""
    try:
        # جلب قائمة بروكسيات عالمية سريعة
        api_url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all"
        response = requests.get(api_url, timeout=10)
        
        if response.status_code == 200:
            proxies = [p.strip() for p in response.text.strip().split('\n') if p.strip()]
            if proxies:
                selected_proxy = random.choice(proxies)
                return {
                    "http": f"http://{selected_proxy}",
                    "https": f"http://{selected_proxy}"
                }
    except Exception as e:
        print(f"⚠️ فشل جلب البروكسي: {e}")
    
    return None # العودة للاتصال المباشر إذا فشل جلب البروكسي

def generate_signature(timestamp, nonce, mobile, service_type):
    """توليد التوقيع الرقمي المطلوب من قبل الـ API"""
    message = f"{timestamp}:{nonce}:{mobile}:{service_type}"
    signature = hmac.new(
        HMAC_SECRET.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode('utf-8')

def get_balance_from_adsl_yemen():
    """الاستعلام عن الرصيد باستخدام API مع تغيير الـ IP"""
    try:
        timestamp = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())
        service_type = "4g"
        
        signature = generate_signature(timestamp, nonce, PHONE_NUMBER, service_type)
        
        headers = {
            "Content-Type": "application/json",
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "X-Preferred-Language": "ar",
            "X-Request-Timestamp": timestamp,
            "X-Request-Nonce": nonce,
            "X-Request-Signature": signature,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        payload = {
            "type": service_type,
            "mobile": PHONE_NUMBER,
            "action": "query"
        }
        
        # جلب بروكسي عشوائي
        proxy_dict = get_random_proxy()
        
        # إرسال الطلب عبر البروكسي
        response = requests.post(
            SUPABASE_URL, 
            headers=headers, 
            json=payload, 
            proxies=proxy_dict, 
            timeout=20
        )
        result = response.json()
        
        if response.status_code == 200 and result.get("success"):
            data = result.get("data", {})
            balance = data.get("avblnce", "غير متوفر")
            package = data.get("baga_amount", "غير متوفر")
            expiry = data.get("expdate", "غير متوفر")
            
            report = (
                f"📊 **نتيجة استعلام Yemen 4G**\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📞 رقم المودم: `{PHONE_NUMBER}`\n"
                f"💰 الرصيد المتاح: `{balance}`\n"
                f"📦 قيمة الباقة: `{package}`\n"
                f"🗓️ تاريخ الانتهاء: `{expiry}`\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🔗 تم الاستعلام عبر API مع تغيير الـ IP"
            )
            return report
        elif response.status_code == 429:
            return "⚠️ تم تجاوز حد الاستعلامات المسموح به. (جرب مرة أخرى ليقوم البوت بتغيير الـ IP)"
        else:
            error_msg = result.get("error", "حدث خطأ غير معروف")
            return f"❌ فشل الاستعلام: {error_msg}"
            
    except Exception as e:
        return f"📡 خطأ في الاتصال (قد يكون البروكسي بطيئاً، حاول مجدداً): {str(e)}"

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
def command_check(message):
    bot.reply_to(message, "⏳ جاري تغيير الـ IP والاستعلام...")
    report = get_balance_from_adsl_yemen()
    bot.send_message(message.chat.id, report, parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text == '.')
def manual_check(message):
    bot.reply_to(message, "⏳ جاري تغيير الـ IP والاستعلام...")
    report = get_balance_from_adsl_yemen()
    bot.send_message(message.chat.id, report, parse_mode="Markdown")

def auto_report():
    """إرسال تقرير تلقائي بناءً على الوقت المحدد"""
    last_report_sent = None
    
    while True:
        report = get_balance_from_adsl_yemen()
        
        # إرسال التقرير فقط إذا لم يكن هناك خطأ في الاتصال
        if "فشل" not in report and "خطأ" not in report and "تجاوز" not in report:
            if report != last_report_sent:
                bot.send_message(CHAT_ID, f"🔔 **تقرير دوري**\n\n{report}", parse_mode="Markdown")
                last_report_sent = report
                
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    print("البوت يعمل الآن... يتم تغيير الـ IP عند كل استعلام.")
    threading.Thread(target=auto_report, daemon=True).start()
    bot.polling(none_stop=True)
