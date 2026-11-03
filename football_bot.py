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

# ضرایب تیم‌های شاخص برای بازی‌های حذفی یا مواقع نبود جدول
ELITE_TEAMS = {
    "real madrid": 9.5, "barcelona": 9.2, "atletico madrid": 8.5,
    "manchester city": 9.6, "liverpool": 9.3, "arsenal": 9.1, "chelsea": 8.2, "manchester united": 8.0, "tottenham": 8.0,
    "bayern munich": 9.4, "borussia dortmund": 8.3, "bayer leverkusen": 8.8,
    "inter": 8.9, "juventus": 8.4, "ac milan": 8.3, "napoli": 8.2,
    "paris saint germain": 9.0,
    "persepolis": 8.0, "esteghlal": 7.9, "sepahan": 7.8, "tractor": 7.7,
    "al hilal": 8.8, "al nassr": 8.6, "al ahli": 8.1, "al ittihad": 8.2
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
            timeout=25,
        )
        data = response.json()
        if response.status_code != 200 or data.get("errors"):
            return []
        return data.get("response") or []
    except Exception:
        return []


def as_form(form_text):
    if not form_text:
        return []
    results = [c for c in str(form_text).upper() if c in "WDL"][-5:]
    symbols = {"W": "🟢", "D": "⚪️", "L": "🔴"}
    return [(symbols[result], 0) for result in results]


# ==================== دریافت فرم بازی‌های اروپا (Football-Data) ====================
def match_form_record_fd(match, team_id):
    if match.get("status") != "FINISHED":
        return None
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    score = match.get("score") or {}
    full_time = score.get("fullTime") or {}
    home_id = home.get("id")
    away_id = away.get("id")
    home_goals = full_time.get("home")
    away_goals = full_time.get("away")

    if team_id not in (home_id, away_id):
        return None

    winner = {"HOME_TEAM": "home", "AWAY_TEAM": "away", "DRAW": "draw"}.get(score.get("winner"))
    if winner is None:
        if not isinstance(home_goals, int) or not isinstance(away_goals, int):
            return None
        winner = "home" if home_goals > away_goals else "away" if away_goals > home_goals else "draw"

    symbol = "⚪️" if winner == "draw" else "🟢" if (winner == "home" and team_id == home_id) or (winner == "away" and team_id == away_id) else "🔴"
    goal_diff = (home_goals - away_goals) if team_id == home_id else (away_goals - home_goals) if isinstance(home_goals, int) and isinstance(away_goals, int) else 0
    return symbol, goal_diff


def get_team_form_fd(team_id, kickoff):
    if not team_id:
        return []
    data = fd_request(
        f"{BASE_URL_FD}/teams/{team_id}/matches",
        {"status": "FINISHED", "limit": 10},
    )
    if not isinstance(data, dict):
        return []

    matches = data.get("matches", [])
    form = []
    for match in sorted(matches, key=lambda m: m.get("utcDate", ""), reverse=True):
        utc_date = match.get("utcDate")
        if not utc_date:
            continue
        try:
            if parse_datetime(utc_date) >= kickoff:
                continue
        except Exception:
            continue
        record = match_form_record_fd(match, team_id)
        if record is not None:
            form.append(record)
        if len(form) == 5:
            break
    return form


# ==================== دریافت فرم آسیا و ایران (API-Sports) ====================
def get_team_form_as(team_id):
    if not team_id:
        return []
    items = as_detail("fixtures", {"team": team_id, "last": 5})
    if not items:
        return []
    form = []
    for match in items:
        fixture = match.get("fixture") or {}
        if (fixture.get("status") or {}).get("short") not in ("FT", "AET", "PEN"):
            continue
        teams = match.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        home_id = home.get("id")
        away_id = away.get("id")

        if home.get("winner") is True:
            symbol = "🟢" if team_id == home_id else "🔴"
        elif away.get("winner") is True:
            symbol = "🟢" if team_id == away_id else "🔴"
        else:
            symbol = "⚪️"
        form.append((symbol, 0))
    return form


# ==================== جدول رده‌بندی ====================
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
                    standings_info[team_id] = {
                        "rank": row.get("position"),
                        "points": row.get("points"),
                        "played": row.get("playedGames"),
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
                standings_info[team_id] = {
                    "rank": row.get("rank"),
                    "points": row.get("points"),
                    "played": (row.get("all") or {}).get("played"),
                    "form_str": row.get("form") or "",
                }
    cache[key] = standings_info
    return standings_info


def format_form(form, is_cup=False):
    if form and len(form) > 0:
        return " ".join(result for result, _ in form)
    if is_cup:
        return "⚡️ صعود به این مرحله"
    return "در دسترس نیست"


# ==================== محاسبه درصدهای شانس هوشمند ====================
def get_base_strength(team_name):
    t_lower = team_name.lower()
    for name, rating in ELITE_TEAMS.items():
        if name in t_lower:
            return rating
    return 5.0  # قدرت پیش‌فرض تیم‌های معمولی


def calculate_probabilities(home_name, away_name, home_rank_data, away_rank_data, home_form, away_form, is_cup=False):
    home_base = get_base_strength(home_name)
    away_base = get_base_strength(away_name)

    def calc_score(data, form, base_power):
        score = base_power
        if data and data.get("played") and data.get("points") is not None:
            ppg = data["points"] / max(1, data["played"])
            score += ppg * 1.6
        elif data and data.get("rank"):
            score += max(0.5, 4.0 - (data["rank"] * 0.15))

        if form:
            form_points = sum(3 if r == "🟢" else 1 if r == "⚪️" else 0 for r, _ in form)
            score += (form_points / max(1, len(form))) * 0.7
        return max(1.0, score)

    home_score = calc_score(home_rank_data, home_form, home_base) + 0.35  # مزیت جزئی میزبانی
    away_score = calc_score(away_rank_data, away_form, away_base)

    diff = abs(home_score - away_score)
    base_draw = 1.6 if is_cup else 2.3
    draw_score = max(0.8, base_draw - (diff * 0.25))

    total = home_score + draw_score + away_score
    home_pct = round((home_score / total) * 100)
    draw_pct = round((draw_score / total) * 100)
    away_pct = 100 - home_pct - draw_pct

    # در صورت تفاوت فاحش (مثلا رئال میهمان مقابل تیم ضعیف)، شانس رئال حفظ می‌شود
    return max(5, home_pct), max(8, draw_pct), max(5, away_pct)


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
    is_cup=False,
):
    h = escape(home_name)
    a = escape(away_name)

    def rank_label(data):
        if is_cup:
            return "مرحله حذفی"
        if not data or not data.get("rank"):
            return "مشخص‌نشده"
        pts = f" ({data['points']} امتیاز)" if data.get("points") is not None else ""
        return f"رتبه {data['rank']}{pts}"

    p_home, p_draw, p_away = calculate_probabilities(
        home_name, away_name, home_rank_data, away_rank_data, home_form, away_form, is_cup=is_cup
    )

    form_h_text = format_form(home_form, is_cup)
    form_a_text = format_form(away_form, is_cup)
    legend_line = "(🟢 برد | ⚪️ مساوی | 🔴 باخت)\n\n" if (home_form or away_form) else "\n"

    return (
        f"🏆 <b>{escape(competition_name)}</b>\n"
        "⚽️ <b>اطلاعات و تحلیل مسابقه</b>\n\n"
        f"🏟 <b>{h}</b> 🆚 <b>{a}</b>\n"
        f"📅 تاریخ: {match_date} | ⏰ ساعت: {match_time}\n\n"
        "━━━━━━━━━━━━━━\n"
        "📊 <b>وضعیت جدول / مرحله:</b>\n"
        f"▫️ {h}: <b>{rank_label(home_rank_data)}</b>\n"
        f"▫️ {a}: <b>{rank_label(away_rank_data)}</b>\n\n"
        "━━━━━━━━━━━━━━\n"
        "📈 <b>فرم بازی‌های اخیر:</b>\n"
        f"▫️ {h}: {form_h_text}\n"
        f"▫️ {a}: {form_a_text}\n"
        f"{legend_line}"
        "━━━━━━━━━━━━━━\n"
        "🎲 <b>پیش‌بینی شانس برد:</b>\n"
        f"🟢 برد {h}: <b>{p_home}%</b>\n"
        f"⚪️ مساوی: <b>{p_draw}%</b>\n"
        f"🔴 برد {a}: <b>{p_away}%</b>\n\n"
        "━━━━━━━━━━━━━━\n"
        f"🆔 {CHANNEL_ID}"
    )


# ==================== دریافت مسابقات اروپا ====================
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
                kickoff = parse_datetime(match["utcDate"])
                match_date, match_time = convert_to_tehran(match["utcDate"])
            except Exception:
                continue

            if match_date == today_jalali:
                selected.append((match_time, match, match_date, kickoff))

        if not selected:
            continue

        standings = get_fd_standings(code, standings_cache)
        posts = []
        for match_time, match, match_date, kickoff in selected:
            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}
            home_id = home.get("id")
            away_id = away.get("id")

            home_rank = standings.get(home_id, {})
            away_rank = standings.get(away_id, {})

            home_form = get_team_form_fd(home_id, kickoff)
            time.sleep(1)
            away_form = get_team_form_fd(away_id, kickoff)
            time.sleep(1)

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
                    is_cup=False,
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
        is_cup = league_id in DOMESTIC_CUPS

        home_rank = {}
        away_rank = {}
        home_form = []
        away_form = []

        if not is_cup:
            standings = get_as_standings(league_id, season, standings_cache)
            home_rank = standings.get(home_id, {})
            away_rank = standings.get(away_id, {})
            home_form = as_form(home_rank.get("form_str"))
            away_form = as_form(away_rank.get("form_str"))

        if not home_form:
            home_form = get_team_form_as(home_id)
            time.sleep(0.5)

        if not away_form:
            away_form = get_team_form_as(away_id)
            time.sleep(0.5)

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
            is_cup=is_cup,
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
    print("🔄 در حال دریافت بازی‌ها، رتبه‌ها و فرم ۵ بازی اخیر...")

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

    print("🏁 تمام پست‌ها ارسال شدند.")


if __name__ == "__main__":
    asyncio.run(main())
