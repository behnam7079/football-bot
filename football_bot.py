import asyncio
from datetime import datetime
import pytz
import os
import requests
from telegram import Bot

# ==================== تنظیمات شخصی ====================
TELEGRAM_BOT_TOKEN = "9214310265:AAGUV7yYcmWWare4eTql2dzYOuLFT89h310"
CHANNEL_ID = "@footbal7079"            # آیدی کانال با @ (مثلاً: @my_channel)
FOOTBALL_API_KEY = "2e7733d64c92451b871ddf1dfba3ff71" # توکن سایت football-data.org

# اگر از سیستم شخصی در ایران اجرا می‌کنید، آدرس پروکسی را بگذارید؛ اگر سرور خارجی دارید مقدار را None بگذارید
PROXY_URL = None  # مثلا: "socks5://127.0.0.1:2080" یا "http://127.0.0.1:10809"

HEADERS = {
    "X-Auth-Token": FOOTBALL_API_KEY
}

# کد لیگ‌ها در football-data:
# PL = لیگ انگلیس | PD = لالیگا | SA = سری آ | BL1 = بوندسلیگا | CL = لیگ قهرمانان
LEAGUE_CODE = "PL"


def convert_utc_to_tehran(utc_date_str):
    """تبدیل فرمت تاریخ و ساعت میلادی UTC به تاریخ و ساعت ایران"""
    try:
        utc_dt = datetime.strptime(utc_date_str, "%Y-%m-%dT%H:%M:%SZ")
        utc_zone = pytz.timezone("UTC")
        tehran_zone = pytz.timezone("Asia/Tehran")
        tehran_dt = utc_zone.localize(utc_dt).astimezone(tehran_zone)
        return tehran_dt.strftime("%Y-%m-%d  ⏰ %H:%M")
    except Exception:
        return utc_date_str.replace("T", " ").replace("Z", "")


def get_team_form(team_id):
    """دریافت ۵ بازی اخیر تیم و تبدیل به ایموجی"""
    url = f"https://api.football-data.org/v4/teams/{team_id}/matches?status=FINISHED&limit=5"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return "در دسترس نیست"
        
        matches = res.json().get("matches", [])
        form_emojis = []
        
        for m in matches:
            winner = m.get("score", {}).get("winner")
            home_id = m.get("homeTeam", {}).get("id")
            
            if winner == "DRAW":
                form_emojis.append("⚪️")
            elif (winner == "HOME_TEAM" and home_id == team_id) or (winner == "AWAY_TEAM" and home_id != team_id):
                form_emojis.append("🟢")
            else:
                form_emojis.append("🔴")
                
        return " ".join(form_emojis) if form_emojis else "اطلاعاتی ثبت نشده"
    except Exception:
        return "خطا در دریافت وضعیت"


def calculate_probabilities(home_form, away_form):
    """محاسبه احتمالاتی نتیجه بر پایه فرم ۵ بازی و امتیاز میزبانی"""
    home_score = home_form.count("🟢") * 3 + home_form.count("⚪️") * 1 + 2
    away_score = away_form.count("🟢") * 3 + away_form.count("⚪️") * 1

    total_weight = home_score + away_score + 4
    if total_weight == 0:
        return 33, 34, 33

    prob_home = round((home_score / total_weight) * 100)
    prob_away = round((away_score / total_weight) * 100)
    prob_draw = max(0, 100 - (prob_home + prob_away))

    return prob_home, prob_draw, prob_away


def generate_match_posts():
    """دریافت بازی‌های آینده لیگ و ساخت پیام‌های زیبا"""
    url = f"https://api.football-data.org/v4/competitions/{LEAGUE_CODE}/matches?status=SCHEDULED"
    res = requests.get(url, headers=HEADERS, timeout=10)
    
    if res.status_code != 200:
        print(f"❌ خطا در دریافت مسابقات: وضعیت {res.status_code} - {res.text}")
        return []

    data = res.json()
    matches = data.get("matches", [])
    posts = []

    # بررسی ۳ بازی اول پیش‌رو
    for match in matches[:3]:
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]
        home_id = match["homeTeam"]["id"]
        away_id = match["awayTeam"]["id"]
        
        match_time_tehran = convert_utc_to_tehran(match["utcDate"])

        # مکث ۱ ثانیه‌ای برای جلوگیری از لیمیت API
        import time
        time.sleep(1)

        home_form = get_team_form(home_id)
        away_form = get_team_form(away_id)
        p_home, p_draw, p_away = calculate_probabilities(home_form, away_form)

        post = (
            f"⚽️ **تحلیل و پیش‌بینی مسابقه پیش‌رو**\n\n"
            f"🏟 **{home_team}** 🆚 **{away_team}**\n"
            f"📅 زمان مسابقه (به وقت ایران):\n"
            f"`{match_time_tehran}`\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"📊 **برآورد آماری نتیجه:**\n"
            f"🟢 برد {home_team}: `{p_home}%`\n"
            f"⚪️ مساوی: `{p_draw}%`\n"
            f"🔴 برد {away_team}: `{p_away}%`\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"📈 **فرم ۵ بازی گذشته:**\n"
            f"▫️ {home_team}: {home_form}\n"
            f"▫️ {away_team}: {away_form}\n"
            f"*(🟢 برد | ⚪️ مساوی | 🔴 باخت)*\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"🆔 {CHANNEL_ID}"
        )
        posts.append(post)

    return posts


async def main():
    if PROXY_URL:
        # اتصال تلگرام با پروکسی (در صورت نیاز به اجرای محلی در ایران)
        bot = Bot(token=TELEGRAM_BOT_TOKEN, request=None) 
    else:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

    print("🔄 در حال بررسی و دریافت لیست بازی‌ها...")
    posts = generate_match_posts()
    
    if not posts:
        print("⚠️ مسابقه جدیدی در این لیگ پیدا نشد.")
        return

    print(f"✅ {len(posts)} مسابقه دریافت شد. در حال ارسال به کانال...")
    for post in posts:
        try:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=post,
                parse_mode="Markdown"
            )
            print("🚀 یک پست با موفقیت در کانال منتشر شد.")
            await asyncio.sleep(2)
        except Exception as err:
            print(f"❌ خطا در ارسال به کانال: {err}")


if __name__ == "__main__":
    asyncio.run(main())
