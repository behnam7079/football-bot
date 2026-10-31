import asyncio
import os
import time
from datetime import datetime

import pytz
import requests
from telegram import Bot
from telegram.error import TelegramError

# ==================== کلیدها (قرار داده‌شده مستقیماً در کد) ====================
TELEGRAM_BOT_TOKEN = "9214310265:AAGUv7yYcmWWare4eTql2dzYOuLFT89h3l0"
FOOTBALL_API_KEY = "2e7733d64c92451b871ddf1dfba3ff71"

CHANNEL_ID = "@footbal7079"

# لیست لیگ‌ها
LEAGUES = {
    "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 لیگ برتر انگلیس",
    "SA": "🇮🇹 سری آ ایتالیا",
    "BL1": "🇩🇪 بوندس‌لیگا آلمان",
    "PD": "🇪🇸 لالیگا اسپانیا",
    "FL1": "🇫🇷 لوشامپیونه فرانسه",
    "CL": "🇪🇺 لیگ قهرمانان اروپا",
    "EL": "🇪🇺 لیگ اروپا"
}

HEADERS = {"X-Auth-Token": FOOTBALL_API_KEY}
API_BASE_URL = "https://api.football-data.org/v4"


def convert_utc_to_tehran(utc_date_str):
    """تبدیل زمان UTC مسابقه به زمان تهران."""
    try:
        utc_dt = datetime.strptime(utc_date_str, "%Y-%m-%dT%H:%M:%SZ")
        utc_dt = pytz.UTC.localize(utc_dt)
        tehran_dt = utc_dt.astimezone(pytz.timezone("Asia/Tehran"))
        return tehran_dt.strftime("%Y-%m-%d  ⏰ %H:%M")
    except (ValueError, TypeError):
        return utc_date_str


def get_team_form(team_id):
    """دریافت نتیجهٔ پنج مسابقهٔ تمام‌شدهٔ اخیر تیم."""
    url = f"{API_BASE_URL}/teams/{team_id}/matches"
    params = {"status": "FINISHED", "limit": 5}

    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=20)
        if response.status_code != 200:
            return "اطلاعاتی ثبت نشده"
            
        matches = response.json().get("matches", [])

        matches = sorted(
            matches,
            key=lambda match: match.get("utcDate", ""),
            reverse=True,
        )

        form = []
        for match in matches[:5]:
            winner = match.get("score", {}).get("winner")
            home_id = match.get("homeTeam", {}).get("id")

            if winner == "DRAW":
                form.append("⚪️")
            elif (
                (winner == "HOME_TEAM" and home_id == team_id)
                or (winner == "AWAY_TEAM" and home_id != team_id)
            ):
                form.append("🟢")
            else:
                form.append("🔴")

        return " ".join(form) if form else "اطلاعاتی ثبت نشده"

    except requests.RequestException as error:
        print(f"خطا در دریافت فرم تیم {team_id}: {error}")
        return "در دسترس نیست"


def calculate_probabilities(home_form, away_form):
    """برآورد ساده بر پایهٔ فرم اخیر."""
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


def generate_match_posts():
    """گرفتن بازی‌های آینده از تمام لیگ‌ها و ساخت پست‌ها."""
    all_posts = []

    for league_code, league_name in LEAGUES.items():
        url = f"{API_BASE_URL}/competitions/{league_code}/matches"
        params = {"status": "SCHEDULED"}

        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=20)
            if response.status_code != 200:
                print(f"خطا در دریافت مسابقات {league_name}: کد {response.status_code}")
                continue
            matches = response.json().get("matches", [])
        except requests.RequestException as error:
            print(f"خطا در دریافت مسابقات {league_name}: {error}")
            continue

        matches.sort(key=lambda match: match.get("utcDate", ""))

        for match in matches[:1]:
            home_team = match["homeTeam"]["name"]
            away_team = match["awayTeam"]["name"]
            home_id = match["homeTeam"]["id"]
            away_id = match["awayTeam"]["id"]
            match_time = convert_utc_to_tehran(match.get("utcDate", ""))

            # افزایش زمان مکث به ۳ ثانیه برای جلوگیری از خطای 429
            time.sleep(3)
            home_form = get_team_form(home_id)

            time.sleep(3)
            away_form = get_team_form(away_id)

            p_home, p_draw, p_away = calculate_probabilities(home_form, away_form)

            post = (
                f"🏆 *{league_name}*\n"
                "⚽️ *تحلیل و پیش‌بینی مسابقهٔ پیش‌رو*\n\n"
                f"🏟 *{home_team}* 🆚 *{away_team}*\n"
                "📅 زمان مسابقه (به وقت ایران):\n"
                f"`{match_time}`\n\n"
                "━━━━━━━━━━━━━━\n"
                "📊 *برآورد آماری نتیجه:*\n"
                f"🟢 برد {home_team}: `{p_home}%`\n"
                f"⚪️ مساوی: `{p_draw}%`\n"
                f"🔴 برد {away_team}: `{p_away}%`\n\n"
                "━━━━━━━━━━━━━━\n"
                "📈 *فرم پنج بازی گذشته:*\n"
                f"▫️ {home_team}: {home_form}\n"
                f"▫️ {away_team}: {away_form}\n"
                "*(🟢 برد | ⚪️ مساوی | 🔴 باخت)*\n\n"
                "━━━━━━━━━━━━━━\n"
                f"🆔 {CHANNEL_ID}"
            )

            all_posts.append(post)

    return all_posts


async def main():
    print("🔄 در حال دریافت فهرست مسابقات لیگ‌های مختلف...")
    posts = generate_match_posts()

    if not posts:
        print("⚠️ مسابقهٔ آینده‌ای برای انتشار پیدا نشد.")
        return

    print(f"✅ {len(posts)} مسابقه دریافت شد؛ ارسال به کانال شروع می‌شود.")

    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        for post in posts:
            try:
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=post,
                    parse_mode="Markdown",
                )
                print("🚀 پیام با موفقیت در کانال منتشر شد.")
                await asyncio.sleep(3)

            except TelegramError as error:
                print(f"❌ خطای تلگرام هنگام ارسال: {error}")


if __name__ == "__main__":
    asyncio.run(main())
