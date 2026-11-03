import asyncio
import os
import time
from datetime import datetime, timedelta
from html import escape

import jdatetime
import pytz
import requests
from telegram import Bot
from telegram.error import RetryAfter, TelegramError

# ==================== کلیدها و تنظیمات ====================
TELEGRAM_BOT_TOKEN = "9214310265:AAFNu67-vsLbBksZq4uMP0-1QPCwZZRXTuA"
FOOTBALL_API_KEY = "2e7733d64c92451b871ddf1dfba3ff71"
API_FOOTBALL_KEY = "35e40e3c03a67c55038905a33c06c74b"

CHANNEL_ID = "@footbal7079"
TEHRAN = pytz.timezone("Asia/Tehran")

# ۱. لیگ‌های معتبر اروپایی (از سرویس football-data.org)
EUROPE_LEAGUES = {
    "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 لیگ برتر انگلیس",
    "SA": "🇮🇹 سری آ ایتالیا",
    "BL1": "🇩🇪 بوندس‌لیگا آلمان",
    "PD": "🇪🇸 لالیگا اسپانیا",
    "FL1": "🇫🇷 لوشامپیونه فرانسه",
    "CL": "🇪🇺 لیگ قهرمانان اروپا",
    "EL": "🇪🇺 لیگ اروپا",
}

# ۲. لیگ‌های ایران و آسیا (از سرویس api-sports.io)
ASIAN_AND_IRAN_LEAGUES = {
    290: "🇮🇷 لیگ برتر ایران",
    17: "🌏 لیگ نخبگان آسیا",
}

# ۳. جام‌های حذفی کشورها (از سرویس api-sports.io)
DOMESTIC_CUPS = {
    495: "🇮🇷 جام حذفی ایران",
    45: "🏴󠁧󠁢󠁥󠁮󠁧󠁿 جام حذفی انگلیس (FA Cup)",
    143: "🇪🇸 کوپا دل ری اسپانیا",
    137: "🇮🇹 کوپا ایتالیا",
    81: "🇩🇪 جام حذفی آلمان",
    66: "🇫🇷 جام حذفی فرانسه",
}

API_SPORTS_COMPETITIONS = {**ASIAN_AND_IRAN_LEAGUES, **DOMESTIC_CUPS}

BASE_URL_FD = "https://api.football-data.org/v4"
BASE_URL_AF = "https://v3.football.api-sports.io"


def tehran_today():
    return datetime.now(TEHRAN).date()


def jalali_date_of(day):
    return jdatetime.date.fromgregorian(date=day).strftime("%Y/%m/%d")


def convert_to_tehran(date_text):
    date_text = date_text.strip().replace("Z", "+00:00")
    moment = datetime.fromisoformat(date_text)

    if moment.tzinfo is None:
        moment = pytz.UTC.localize(moment)

    local = moment.astimezone(TEHRAN)
    return jalali_date_of(local.date()), local.strftime("%H:%M")


def fd_request(url, params):
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}

    for attempt in range(2):
        try:
            response = requests.get(
                url, headers=headers, params=params, timeout=20
            )

            if response.status_code == 429 and attempt == 0:
                time.sleep(65)
                continue

            if response.status_code != 200:
                return None

            return response.json()
        except Exception:
            return None
    return None


def get_team_form_fd(team_id):
    if not team_id:
        return "اطلاعاتی ثبت نشده"

    data = fd_request(
        f"{BASE_URL_FD}/teams/{team_id}/matches",
        {"status": "FINISHED", "limit": 5},
    )

    if data is None:
        return "اطلاعاتی ثبت نشده"

    matches = sorted(
        data.get("matches", []),
        key=lambda match: match.get("utcDate", ""),
        reverse=True,
    )

    form = []
    for match in matches[:5]:
        winner = (match.get("score") or {}).get("winner")
        home_id = (match.get("homeTeam") or {}).get("id")

        if winner == "DRAW":
            form.append("⚪️")
        elif (
            (winner == "HOME_TEAM" and home_id == team_id)
            or (winner == "AWAY_TEAM" and home_id != team_id)
        ):
            form.append("🟢")
        elif winner in ("HOME_TEAM", "AWAY_TEAM"):
            form.append("🔴")

    return " ".join(form) if form else "اطلاعاتی ثبت نشده"


def get_team_form_as(team_id):
    if not team_id:
        return "اطلاعاتی ثبت نشده"

    try:
        response = requests.get(
            f"{BASE_URL_AF}/fixtures",
            headers={"x-apisports-key": API_FOOTBALL_KEY},
            params={"team": team_id, "last": 5, "status": "FT"},
            timeout=20,
        )
        if response.status_code != 200:
            return "اطلاعاتی ثبت نشده"

        data = response.json().get("response", [])
        if not data:
            return "اطلاعاتی ثبت نشده"

        form = []
        for match in data:
            teams = match.get("teams", {})
            goals = match.get("goals", {})
            home_id = teams.get("home", {}).get("id")

            home_goals = goals.get("home")
            away_goals = goals.get("away")

            if home_goals is None or away_goals is None:
                continue

            if home_goals == away_goals:
                form.append("⚪️")
            elif home_id == team_id:
                if home_goals > away_goals:
                    form.append("🟢")
                else:
                    form.append("🔴")
            else:
                if away_goals > home_goals:
                    form.append("🟢")
                else:
                    form.append("🔴")

        return " ".join(form) if form else "اطلاعاتی ثبت نشده"
    except Exception:
        return "اطلاعاتی ثبت نشده"


def calculate_probabilities(home_form, away_form):
    if (
        home_form == "اطلاعاتی ثبت نشده"
        or away_form == "اطلاعاتی ثبت نشده"
        or not home_form.strip()
        or not away_form.strip()
    ):
        return 45, 25, 30

    home_score = home_form.count("🟢") * 3 + home_form.count("⚪️") + 2
    away_score = away_form.count("🟢") * 3 + away_form.count("⚪️")
    draw_score = 3

    total = home_score + away_score + draw_score
    if total <= 0:
        return 45, 25, 30

    home = round(home_score / total * 100)
    draw = round(draw_score / total * 100)
    away = 100 - home - draw

    return home, draw, away


def fetch_european_matches():
    posts_by_league = {}
    today = tehran_today()
    today_jalali = jalali_date_of(today)

    date_from = (today - timedelta(days=1)).isoformat()
    date_to = (today + timedelta(days=1)).isoformat()

    for code, league_name in EUROPE_LEAGUES.items():
        data = fd_request(
            f"{BASE_URL_FD}/competitions/{code}/matches",
            {"dateFrom": date_from, "dateTo": date_to},
        )

        if data is None:
            continue

        selected = []
        for match in data.get("matches", []):
            if match.get("status") not in ("SCHEDULED", "TIMED"):
                continue

            try:
                match_date, match_time = convert_to_tehran(match["utcDate"])
            except Exception:
                continue

            if match_date == today_jalali:
                selected.append((match_time, match, match_date))

        selected.sort(key=lambda entry: entry[0])
        if not selected:
            continue

        league_posts = []
        for match_time, match, match_date in selected:
            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}

            home_name = home.get("name") or "نامشخص"
            away_name = away.get("name") or "نامشخص"

            home_form = get_team_form_fd(home.get("id"))
            time.sleep(2)
            away_form = get_team_form_fd(away.get("id"))
            time.sleep(2)

            p_home, p_draw, p_away = calculate_probabilities(
                home_form, away_form
            )

            h = escape(home_name)
            a = escape(away_name)

            post = (
                f"🏆 <b>{escape(league_name)}</b>\n"
                "⚽️ <b>تحلیل و پیش‌بینی مسابقهٔ امروز</b>\n\n"
                f"🏟 <b>{h}</b> 🆚 <b>{a}</b>\n"
                f"📅 تاریخ: {match_date} | ⏰ ساعت: {match_time}\n\n"
                "━━━━━━━━━━━━━━\n"
                "📊 <b>برآورد تقریبی نتیجه:</b>\n"
                f"🟢 برد {h}: {p_home}%\n"
                f"⚪️ مساوی: {p_draw}%\n"
                f"🔴 برد {a}: {p_away}%\n\n"
                "━━━━━━━━━━━━━━\n"
                "📈 <b>فرم پنج بازی گذشته:</b>\n"
                f"▫️ {h}: {home_form}\n"
                f"▫️ {a}: {away_form}\n"
                "(🟢 برد | ⚪️ مساوی | 🔴 باخت)\n\n"
                "━━━━━━━━━━━━━━\n"
                f"🆔 {CHANNEL_ID}"
            )
            league_posts.append(post)

        posts_by_league[league_name] = league_posts

    return posts_by_league


def fetch_api_sports_matches():
    today = tehran_today()
    today_jalali = jalali_date_of(today)

    response = requests.get(
        f"{BASE_URL_AF}/fixtures",
        headers={"x-apisports-key": API_FOOTBALL_KEY},
        params={"date": today.isoformat(), "timezone": "Asia/Tehran"},
        timeout=30,
    )

    if response.status_code != 200:
        return {}

    data = response.json()
    fixtures = data.get("response", [])
    if not isinstance(fixtures, list):
        return {}

    posts_by_competition = {
        name: [] for name in API_SPORTS_COMPETITIONS.values()
    }

    for item in fixtures:
        league_id = (item.get("league") or {}).get("id")

        if league_id not in API_SPORTS_COMPETITIONS:
            continue

        fixture = item.get("fixture") or {}
        status = (fixture.get("status") or {}).get("short")

        if status != "NS":
            continue

        try:
            match_date, match_time = convert_to_tehran(fixture["date"])
        except Exception:
            continue

        if match_date != today_jalali:
            continue

        teams = item.get("teams") or {}
        home_team = teams.get("home") or {}
        away_team = teams.get("away") or {}

        home = home_team.get("name") or "نامشخص"
        away = away_team.get("name") or "نامشخص"

        home_form = get_team_form_as(home_team.get("id"))
        time.sleep(2)
        away_form = get_team_form_as(away_team.get("id"))
        time.sleep(2)

        p_home, p_draw, p_away = calculate_probabilities(home_form, away_form)
        competition_name = API_SPORTS_COMPETITIONS[league_id]

        h = escape(home)
        a = escape(away)

        post = (
            f"🏆 <b>{escape(competition_name)}</b>\n"
            "⚽️ <b>تحلیل و پیش‌بینی مسابقهٔ امروز</b>\n\n"
            f"🏟 <b>{h}</b> 🆚 <b>{a}</b>\n"
            f"📅 تاریخ: {match_date} | ⏰ ساعت: {match_time}\n\n"
            "━━━━━━━━━━━━━━\n"
            "📊 <b>برآورد تقریبی نتیجه:</b>\n"
            f"🟢 برد {h}: {p_home}%\n"
            f"⚪️ مساوی: {p_draw}%\n"
            f"🔴 برد {a}: {p_away}%\n\n"
            "━━━━━━━━━━━━━━\n"
            "📈 <b>فرم پنج بازی گذشته:</b>\n"
            f"▫️ {h}: {home_form}\n"
            f"▫️ {a}: {away_form}\n"
            "(🟢 برد | ⚪️ مساوی | 🔴 باخت)\n\n"
            "━━━━━━━━━━━━━━\n"
            f"🆔 {CHANNEL_ID}"
        )

        posts_by_competition[competition_name].append(post)

    return {
        comp_name: posts
        for comp_name, posts in posts_by_competition.items()
        if posts
    }


async def safe_send_message(bot, chat_id, text, parse_mode="HTML"):
    while True:
        try:
            await bot.send_message(
                chat_id=chat_id, text=text, parse_mode=parse_mode
            )
            break
        except RetryAfter as e:
            wait_time = e.retry_after + 2
            await asyncio.sleep(wait_time)
        except TelegramError as e:
            print(f"❌ خطا در ارسال پیام: {e}")
            break


async def main():
    print("🔄 در حال بررسی مسابقات امروز به وقت تهران...")

    posts_by_league = fetch_european_matches()
    posts_by_league.update(fetch_api_sports_matches())

    if not posts_by_league:
        print("⚠️ امروز بازیِ شروع‌نشده‌ای در رقابت‌های هدف پیدا نشد.")
        return

    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        for comp_name, posts in posts_by_league.items():
            print(f"📌 ارسال {comp_name}: {len(posts)} بازی")

            await safe_send_message(
                bot,
                CHANNEL_ID,
                f"📢 <b>بازی‌های امروز در {escape(comp_name)}</b>",
            )

            for post in posts:
                await asyncio.sleep(3)
                await safe_send_message(bot, CHANNEL_ID, post)

    print("🏁 ارسال بازی‌های یافت‌شده تمام شد.")


if __name__ == "__main__":
    asyncio.run(main())
