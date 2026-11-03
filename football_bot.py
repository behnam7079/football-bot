import asyncio
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

BASE_URL_FD = "https://api.football-data.org/v4"
BASE_URL_AF = "https://v3.football.api-sports.io"

NO_FORM = "اطلاعاتی ثبت نشده"

EUROPE_LEAGUES = {
    "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 لیگ برتر انگلیس",
    "SA": "🇮🇹 سری آ ایتالیا",
    "BL1": "🇩🇪 بوندس‌لیگا آلمان",
    "PD": "🇪🇸 لالیگا اسپانیا",
    "FL1": "🇫🇷 لوشامپیونه فرانسه",
    "CL": "🇪🇺 لیگ قهرمانان اروپا",
    "EL": "🇪🇺 لیگ اروپا",
}

ASIAN_AND_IRAN_LEAGUES = {
    290: "🇮🇷 لیگ برتر ایران",
    17: "🌏 لیگ نخبگان آسیا",
}

DOMESTIC_CUPS = {
    495: "🇮🇷 جام حذفی ایران",
    45: "🏴󠁧󠁢󠁥󠁮󠁧󠁿 جام حذفی انگلیس (FA Cup)",
    143: "🇪🇸 کوپا دل ری اسپانیا",
    137: "🇮🇹 کوپا ایتالیا",
    81: "🇩🇪 جام حذفی آلمان",
    66: "🇫🇷 جام حذفی فرانسه",
}

API_SPORTS_COMPETITIONS = {
    **ASIAN_AND_IRAN_LEAGUES,
    **DOMESTIC_CUPS,
}


def tehran_today():
    return datetime.now(TEHRAN).date()


def jalali_date_of(day):
    return jdatetime.date.fromgregorian(date=day).strftime("%Y/%m/%d")


def parse_datetime(date_text):
    moment = datetime.fromisoformat(date_text.strip().replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = pytz.UTC.localize(moment)
    return moment


def convert_to_tehran(date_text):
    local = parse_datetime(date_text).astimezone(TEHRAN)
    return jalali_date_of(local.date()), local.strftime("%H:%M")


def fd_request(url, params=None):
    for attempt in range(2):
        try:
            response = requests.get(
                url,
                headers={"X-Auth-Token": FOOTBALL_API_KEY},
                params=params,
                timeout=20,
            )
            if response.status_code == 429 and attempt == 0:
                time.sleep(62)
                continue
            if response.status_code != 200:
                return None
            return response.json()
        except Exception:
            return None
    return None


def as_detail(endpoint, params):
    try:
        response = requests.get(
            f"{BASE_URL_AF}/{endpoint}",
            headers={"x-apisports-key": API_FOOTBALL_KEY},
            params=params,
            timeout=30,
        )
        data = response.json()
        if response.status_code != 200 or data.get("errors"):
            return []
        return data.get("response") or []
    except Exception:
        return []


def as_form(form_text):
    results = [c for c in str(form_text or "").upper() if c in "WDL"][-5:]
    symbols = {"W": "🟢", "D": "⚪️", "L": "🔴"}
    return [(symbols[result], 0) for result in results]


# ==================== دریافت جدول و رتبه‌ها ====================
def get_fd_standings(competition_code, cache):
    if competition_code in cache:
        return cache[competition_code]
    data = fd_request(f"{BASE_URL_FD}/competitions/{competition_code}/standings")
    standings_info = {}
    if data and "standings" in data:
        for st in data["standings"]:
            if st.get("type") == "TOTAL":
                for row in st.get("table", []):
                    team_id = (row.get("team") or {}).get("id")
                    form_str = row.get("form") or ""
                    form_list = as_form(form_str)
                    standings_info[team_id] = {
                        "rank": row.get("position"),
                        "points": row.get("points"),
                        "played": row.get("playedGames"),
                        "form": form_list
                    }
    cache[competition_code] = standings_info
    return standings_info


def get_as_standings(league_id, season, cache):
    key = (league_id, season)
    if key in cache:
        return cache[key]
    items = as_detail("standings", {"league": league_id, "season": season})
    standings_info = {}
    for item in items:
        groups = (item.get("league") or {}).get("standings") or []
        for group in groups:
            for row in group:
                team_id = (row.get("team") or {}).get("id")
                form_str = row.get("form") or ""
                standings_info[team_id] = {
                    "rank": row.get("rank"),
                    "points": row.get("points"),
                    "played": (row.get("all") or {}).get("played"),
                    "form": as_form(form_str)
                }
    cache[key] = standings_info
    return standings_info


def format_form(form):
    if not form:
        return NO_FORM
    symbols = " ".join(result for result, _ in form)
    if len(form) < 5:
        return f"{symbols} (تعداد: {len(form)})"
    return symbols


# ==================== فرمول پیش‌بینی شانس ====================
def calculate_probabilities(home_rank_data, away_rank_data, home_form, away_form):
    # قدرت پایه بر اساس امتیاز در هر بازی (PPG) یا رتبه
    def calc_score(data, form):
        score = 2.0
        if data and data.get("played") and data.get("points") is not None:
            ppg = data["points"] / max(1, data["played"])
            score += ppg * 1.5
        elif data and data.get("rank"):
            score += max(0.5, 4.0 - (data["rank"] * 0.15))
        
        # تاثیر ۵ بازی اخیر
        if form:
            form_points = sum(3 if r == "🟢" else 1 if r == "⚪️" else 0 for r, _ in form)
            score += (form_points / max(1, len(form))) * 0.8
        return max(0.5, score)

    home_score = calc_score(home_rank_data, home_form) + 0.5  # مزیت میزبانی
    away_score = calc_score(away_rank_data, away_form)

    # شانس مساوی بر اساس نزدیکی قدرت دو تیم
    diff = abs(home_score - away_score)
    draw_score = max(1.2, 2.5 - (diff * 0.35))

    total = home_score + draw_score + away_score
    home_pct = round((home_score / total) * 100)
    draw_pct = round((draw_score / total) * 100)
    away_pct = 100 - home_pct - draw_pct

    # تنظیم مرزها
    return max(5, home_pct), max(5, draw_pct), max(5, away_pct)


# ==================== تولید پیام پست ====================
def build_post(
    competition_name,
    home_name,
    away_name,
    match_date,
    match_time,
    home_rank_data,
    away_rank_data,
    home_form,
    away_form,
):
    h = escape(home_name)
    a = escape(away_name)

    # قالب نمایش رتبه
    def rank_label(data):
        if not data or not data.get("rank"):
            return "رتبه ثبت نشده"
        pts = f" ({data['points']} امتیاز)" if data.get("points") is not None else ""
        return f"رتبه {data['rank']}{pts}"

    p_home, p_draw, p_away = calculate_probabilities(home_rank_data, away_rank_data, home_form, away_form)

    return (
        f"🏆 <b>{escape(competition_name)}</b>\n"
        "⚽️ <b>اطلاعات و تحلیل مسابقه</b>\n\n"
        f"🏟 <b>{h}</b> 🆚 <b>{a}</b>\n"
        f"📅 تاریخ: {match_date} | ⏰ ساعت: {match_time}\n\n"
        "━━━━━━━━━━━━━━\n"
        "📊 <b>جایگاه در جدول:</b>\n"
        f"▫️ {h}: <b>{rank_label(home_rank_data)}</b>\n"
        f"▫️ {a}: <b>{rank_label(away_rank_data)}</b>\n\n"
        "━━━━━━━━━━━━━━\n"
        "📈 <b>فرم ۵ بازی اخیر:</b>\n"
        f"▫️ {h}: {format_form(home_form)}\n"
        f"▫️ {a}: {format_form(away_form)}\n"
        "(🟢 برد | ⚪️ مساوی | 🔴 باخت)\n\n"
        "━━━━━━━━━━━━━━\n"
        "🎲 <b>پیش‌بینی شانس نتیجه:</b>\n"
        f"🟢 برد {h}: <b>{p_home}%</b>\n"
        f"⚪️ مساوی: <b>{p_draw}%</b>\n"
        f"🔴 برد {a}: <b>{p_away}%</b>\n\n"
        "━━━━━━━━━━━━━━\n"
        f"🆔 {CHANNEL_ID}"
    )


# ==================== دریافت لیگ‌های اروپا ====================
def fetch_european_matches():
    posts_by_league = {}
    today = tehran_today()
    today_jalali = jalali_date_of(today)
    date_from = (today - timedelta(days=1)).isoformat()
    date_to = (today + timedelta(days=1)).isoformat()
    standings_cache = {}

    for code, league_name in EUROPE_LEAGUES.items():
        data = fd_request(
            f"{BASE_URL_FD}/competitions/{code}/matches",
            {"dateFrom": date_from, "dateTo": date_to},
        )
        if not isinstance(data, dict):
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

        if not selected:
            continue

        standings = get_fd_standings(code, standings_cache)
        posts = []
        for match_time, match, match_date in selected:
            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}
            home_id = home.get("id")
            away_id = away.get("id")

            home_rank = standings.get(home_id, {})
            away_rank = standings.get(away_id, {})
            home_form = home_rank.get("form", [])
            away_form = away_rank.get("form", [])

            posts.append(
                build_post(
                    league_name,
                    home.get("name") or "نامشخص",
                    away.get("name") or "نامشخص",
                    match_date,
                    match_time,
                    home_rank,
                    away_rank,
                    home_form,
                    away_form,
                )
            )
        posts_by_league[league_name] = posts

    return posts_by_league


# ==================== دریافت مسابقات ایران و آسیا ====================
def fetch_api_sports_matches():
    today = tehran_today()
    today_jalali = jalali_date_of(today)

    fixtures = as_detail("fixtures", {"date": today.isoformat(), "timezone": "Asia/Tehran"})
    if not fixtures:
        return {}

    selected = []
    for item in fixtures:
        league_id = (item.get("league") or {}).get("id")
        if league_id not in API_SPORTS_COMPETITIONS:
            continue
        fixture = item.get("fixture") or {}
        if (fixture.get("status") or {}).get("short") != "NS":
            continue
        try:
            match_date, match_time = convert_to_tehran(fixture["date"])
        except Exception:
            continue

        if match_date == today_jalali:
            selected.append((league_id, match_time, match_date, item))

    posts_by_competition = {}
    standings_cache = {}

    for league_id, match_time, match_date, item in selected:
        league = item.get("league") or {}
        teams = item.get("teams") or {}
        home_team = teams.get("home") or {}
        away_team = teams.get("away") or {}
        home_id = home_team.get("id")
        away_id = away_team.get("id")
        season = league.get("season")

        standings = get_as_standings(league_id, season, standings_cache)
        home_rank = standings.get(home_id, {})
        away_rank = standings.get(away_id, {})

        home_form = home_rank.get("form", [])
        away_form = away_rank.get("form", [])

        competition_name = API_SPORTS_COMPETITIONS[league_id]
        post = build_post(
            competition_name,
            home_team.get("name") or "نامشخص",
            away_team.get("name") or "نامشخص",
            match_date,
            match_time,
            home_rank,
            away_rank,
            home_form,
            away_form,
        )
        posts_by_competition.setdefault(competition_name, []).append(post)

    return posts_by_competition


# ==================== ارسال تلگرام ====================
async def safe_send_message(bot, chat_id, text, parse_mode="HTML"):
    while True:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return True
        except RetryAfter as exc:
            wait = float(exc.retry_after.total_seconds()) if isinstance(exc.retry_after, timedelta) else float(exc.retry_after)
            await asyncio.sleep(max(0, wait) + 2)
        except TelegramError:
            return False


async def main():
    print("🔄 در حال دریافت بازی‌ها، جدول رده‌بندی و محاسبه احتمالات...")

    posts_by_league = fetch_european_matches()
    posts_by_league.update(fetch_api_sports_matches())

    if not posts_by_league:
        print("⚠️ مسابقهٔ شروع‌نشده‌ای برای امروز یافت نشد.")
        return

    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        for competition_name, posts in posts_by_league.items():
            print(f"📌 ارسال {competition_name}: {len(posts)} مسابقه")
            header_sent = await safe_send_message(
                bot,
                CHANNEL_ID,
                f"📢 <b>مسابقات امروز | {escape(competition_name)}</b>",
            )
            if not header_sent:
                continue

            for post in posts:
                await asyncio.sleep(2.5)
                await safe_send_message(bot, CHANNEL_ID, post)

    print("🏁 تمام پست‌ها با موفقیت در کانال منتشر شدند.")


if __name__ == "__main__":
    asyncio.run(main())
