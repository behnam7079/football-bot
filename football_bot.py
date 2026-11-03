import asyncio
import os
import time
from datetime import datetime, timedelta

import jdatetime
import pytz
import requests
from telegram import Bot
from telegram.error import TelegramError

# ==================== کلیدها و تنظیمات ====================
TELEGRAM_BOT_TOKEN = "9214310265:AAENQk-mVivaBSsS0TfWeDk3XJ1FGc37-Gg"
FOOTBALL_API_KEY = "FOOTBALL_API_KEY", "2e7733d64c92451b871ddf1dfba3ff71"
API_FOOTBALL_KEY = "API_FOOTBALL_KEY", "35e40e3c03a67c55038905a33c06c74b"

CHANNEL_ID = "@footbal7079"

# لیگ‌های اروپایی (football-data.org)
EUROPE_LEAGUES = {
    "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 لیگ برتر انگلیس",
    "SA": "🇮🇹 سری آ ایتالیا",
    "BL1": "🇩🇪 بوندس‌لیگا آلمان",
    "PD": "🇪🇸 لالیگا اسپانیا",
    "FL1": "🇫🇷 لوشامپیونه فرانسه",
    "CL": "🇪🇺 لیگ قهرمانان اروپا",
    "EL": "🇪🇺 لیگ اروپا"
}

# لیگ‌های ایران، آسیا و جام‌های حذفی (api-football.com)
ASIAN_LEAGUES = {
    290: "🇮🇷 لیگ برتر ایران",
    495: "🇮🇷 جام حذفی ایران",
    17: "🌏 لیگ نخبگان آسیا",
    66: "🇫🇷 جام حذفی فرانسه"
}

HEADERS_FD = {"X-Auth-Token": FOOTBALL_API_KEY}
BASE_URL_FD = "https://api.football-data.org/v4"

HEADERS_AF = {
    "x-rapidapi-host": "v3.football.api-sports.io",
    "x-rapidapi-key": API_FOOTBALL_KEY
}
BASE_URL_AF = "https://v3.football.api-sports.io"


def get_tehran_today_str():
    """تاریخ امروز به وقت تهران (شمسی) برای فیلتر نهایی مسابقات"""
    tehran_tz = pytz.timezone("Asia/Tehran")
    tehran_now = datetime.now(tehran_tz)
    jalali_today = jdatetime.datetime.fromgregorian(datetime=tehran_now)
    return jalali_today.strftime("%Y/%m/%d")


def convert_utc_to_tehran(utc_date_str):
    """تبدیل رشته تاریخ UTC به تاریخ شمسی و ساعت به وقت تهران"""
    try:
        date_str = utc_date_str.strip()
        if date_str.endswith("Z"):
            date_str = date_str[:-1] + "+00:00"

        utc_dt = datetime.fromisoformat(date_str)
        if utc_dt.tzinfo is None:
            utc_dt = pytz.UTC.localize(utc_dt)
        else:
            utc_dt = utc_dt.astimezone(pytz.UTC)

        tehran_tz = pytz.timezone("Asia/Tehran")
        tehran_dt = utc_dt.astimezone(tehran_tz)

        tehran_naive = tehran_dt.replace(tzinfo=None)
        jalali_dt = jdatetime.datetime.fromgregorian(datetime=tehran_naive)

        return jalali_dt.strftime("%Y/%m/%d"), tehran_dt.strftime("%H:%M")
    except Exception as error:
        print(f"خطا در تبدیل زمان مسابقه {utc_date_str}: {error}")
        return "", utc_date_str


def get_team_form_fd(team_id):
    """دریافت فرم ۵ بازی اخیر تیم از football-data.org با مدیریت درخواست‌ها"""
    url = f"{BASE_URL_FD}/teams/{team_id}/matches"
    params = {"status": "FINISHED", "limit": 5}
    try:
        response = requests.get(url, headers=HEADERS_FD, params=params, timeout=15)
        if response.status_code == 429:
            time.sleep(12)  # مکث برای جلوگیری از بلاک شدن لیمیت
            response = requests.get(url, headers=HEADERS_FD, params=params, timeout=15)
        
        if response.status_code != 200:
            return "اطلاعاتی ثبت نشده"

        matches = response.json().get("matches", [])
        matches = sorted(matches, key=lambda m: m.get("utcDate", ""), reverse=True)

        form = []
        for match in matches[:5]:
            winner = match.get("score", {}).get("winner")
            home_id = match.get("homeTeam", {}).get("id")

            if winner == "DRAW":
                form.append("⚪️")
            elif (winner == "HOME_TEAM" and home_id == team_id) or (winner == "AWAY_TEAM" and home_id != team_id):
                form.append("🟢")
            else:
                form.append("🔴")

        return " ".join(form) if form else "اطلاعاتی ثبت نشده"
    except Exception:
        return "در دسترس نیست"


def calculate_probabilities(home_form, away_form):
    """برآورد درصدی نتیجه بازی بر مبنای بازی‌های اخیر"""
    home_score = home_form.count("🟢") * 3 + home_form.count("⚪️") + 2
    away_score = away_form.count("🟢") * 3 + away_form.count("⚪️")
    draw_score = 3

    total = home_score + away_score + draw_score
    if total <= 0:
        return 33, 34, 33

    home = round(home_score / total * 100)
    draw = round(draw_score / total * 100)
    away = 100 - home - draw
    return home, draw, away


def fetch_european_matches():
    """دریافت بازی‌های امروز لیگ‌های اروپایی با رعایت محدودیت نرخ درخواست"""
    league_posts = {}
    today_jalali = get_tehran_today_str()
    
    tehran_tz = pytz.timezone("Asia/Tehran")
    today_tehran = datetime.now(tehran_tz)
    date_from = today_tehran.strftime("%Y-%m-%d")
    date_to = (today_tehran + timedelta(days=1)).strftime("%Y-%m-%d")

    for league_code, league_name in EUROPE_LEAGUES.items():
        url = f"{BASE_URL_FD}/competitions/{league_code}/matches"
        params = {"dateFrom": date_from, "dateTo": date_to}

        try:
            res = requests.get(url, headers=HEADERS_FD, params=params, timeout=20)
            if res.status_code == 429:
                print(f"⚠️ لیمیت درخواست برای لیگ {league_name}، مکث ۱۵ ثانیه‌ای...")
                time.sleep(15)
                res = requests.get(url, headers=HEADERS_FD, params=params, timeout=20)
            
            if res.status_code != 200:
                print(f"خطا در دریافت لیگ {league_name}: استاتوس کد {res.status_code}")
                continue

            matches = res.json().get("matches", [])
        except Exception as e:
            print(f"خطا در ارتباط با لیگ {league_name}: {e}")
            continue

        valid_matches = []
        for match in matches:
            if match.get("status") not in ["SCHEDULED", "TIMED"]:
                continue

            jalali_date, match_time = convert_utc_to_tehran(match.get("utcDate", ""))
            if jalali_date == today_jalali:
                valid_matches.append((match, jalali_date, match_time))

        if not valid_matches:
            time.sleep(3)
            continue

        valid_matches.sort(key=lambda item: item[2])
        league_posts[league_name] = []

        for match, j_date, m_time in valid_matches:
            home_team = match["homeTeam"]["name"]
            away_team = match["awayTeam"]["name"]
            home_id = match["homeTeam"]["id"]
            away_id = match["awayTeam"]["id"]

            time.sleep(2)  # مکث برای جلوگیری از اتمام لیمیت
            h_form = get_team_form_fd(home_id)
            time.sleep(2)
            a_form = get_team_form_fd(away_id)

            p_h, p_d, p_a = calculate_probabilities(h_form, a_form)

            post = (
                f"🏆 *{league_name}*\n"
                "⚽️ *تحلیل و پیش‌بینی مسابقهٔ امروز*\n\n"
                f"🏟 *{home_team}* 🆚 *{away_team}*\n"
                f"📅 تاریخ: `{j_date}` | ⏰ ساعت: `{m_time}`\n\n"
                "━━━━━━━━━━━━━━\n"
                "📊 *برآورد آماری نتیجه:*\n"
                f"🟢 برد {home_team}: `{p_h}%`\n"
                f"⚪️ مساوی: `{p_d}%`\n"
                f"🔴 برد {away_team}: `{p_a}%`\n\n"
                "━━━━━━━━━━━━━━\n"
                "📈 *فرم پنج بازی گذشته:*\n"
                f"▫️ {home_team}: {h_form}\n"
                f"▫️ {away_team}: {a_form}\n"
                "*(🟢 برد | ⚪️ مساوی | 🔴 باخت)*\n\n"
                "━━━━━━━━━━━━━━\n"
                f"🆔 {CHANNEL_ID}"
            )
            league_posts[league_name].append(post)

        time.sleep(4)

    return league_posts


def fetch_asian_and_iran_matches():
    """دریافت بازی‌های لیگ ایران، آسیا و جام‌های حذفی از api-football"""
    if not API_FOOTBALL_KEY:
        return {}

    league_posts = {}
    today_jalali = get_tehran_today_str()
    today_gregorian = datetime.now(pytz.timezone("Asia/Tehran")).strftime("%Y-%m-%d")
    current_season = "2025"  # فصل جاری

    for league_id, league_name in ASIAN_LEAGUES.items():
        url = f"{BASE_URL_AF}/fixtures"
        params = {
            "league": league_id,
            "season": current_season,
            "date": today_gregorian,
            "timezone": "Asia/Tehran"
        }

        try:
            res = requests.get(url, headers=HEADERS_AF, params=params, timeout=20)
            if res.status_code != 200:
                print(f"خطا در دریافت {league_name}: استاتوس کد {res.status_code}")
                continue

            data = res.json()
            fixtures = data.get("response", [])
            if not fixtures:
                continue

            league_posts[league_name] = []
            for item in fixtures:
                home_team = item["teams"]["home"]["name"]
                away_team = item["teams"]["away"]["name"]
                utc_date = item["fixture"]["date"]

                j_date, m_time = convert_utc_to_tehran(utc_date)

                post = (
                    f"🏆 *{league_name}*\n"
                    "⚽️ *برنامهٔ مسابقه امروز*\n\n"
                    f"🏟 *{home_team}* 🆚 *{away_team}*\n"
                    f"📅 تاریخ: `{j_date}` | ⏰ ساعت: `{m_time}`\n\n"
                    "━━━━━━━━━━━━━━\n"
                    f"🆔 {CHANNEL_ID}"
                )
                league_posts[league_name].append(post)
            
            time.sleep(2)

        except Exception as err:
            print(f"خطا در ارتباط با {league_name}: {err}")

    return league_posts


async def main():
    print("🔄 در حال بررسی و دریافت مسابقات امروز...")
    
    # جمع‌آوری مسابقات اروپایی
    all_grouped_posts = fetch_european_matches()

    # جمع‌آوری مسابقات ایران، آسیا و جام‌های حذفی
    asian_posts = fetch_asian_and_iran_matches()
    for league, posts in asian_posts.items():
        all_grouped_posts[league] = posts

    if not all_grouped_posts:
        print("⚠️ برای امروز هیچ مسابقه‌ای در لیگ‌های هدف یافت نشد.")
        return

    # ارسال منظم و تفکیک‌شده به کانال تلگرام
    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        for league_name, posts in all_grouped_posts.items():
            print(f"📌 در حال ارسال بازی‌های {league_name} ({len(posts)} مسابقه)...")
            
            header_text = f"📢 *بازی‌های امروز در {league_name}*"
            try:
                await bot.send_message(chat_id=CHANNEL_ID, text=header_text, parse_mode="Markdown")
                await asyncio.sleep(2)
            except TelegramError as e:
                print(f"خطا در ارسال تیتر لیگ: {e}")

            for post in posts:
                try:
                    await bot.send_message(chat_id=CHANNEL_ID, text=post, parse_mode="Markdown")
                    print("🚀 پست بازی ارسال شد.")
                    await asyncio.sleep(3)
                except TelegramError as e:
                    print(f"❌ خطا در ارسال پست: {e}")

            await asyncio.sleep(3)

    print("🏁 تمام بازی‌های امروز با موفقیت ارسال شدند.")


if __name__ == "__main__":
    asyncio.run(main())
