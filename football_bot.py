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


def fd_request(url, params, label):
    for attempt in range(2):
        try:
            response = requests.get(
                url,
                headers={"X-Auth-Token": FOOTBALL_API_KEY},
                params=params,
                timeout=20,
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


def as_request(params, label):
    try:
        response = requests.get(
            f"{BASE_URL_AF}/fixtures",
            headers={"x-apisports-key": API_FOOTBALL_KEY},
            params=params,
            timeout=30,
        )
        data = response.json()
        if response.status_code != 200 or data.get("errors"):
            return None
        return data.get("response", [])
    except Exception:
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
    return [(symbols[result], None) for result in results]


def as_standings_forms(league_id, season, cache):
    if not league_id or not season:
        return {}
    key = (league_id, season)
    if key not in cache:
        forms = {}
        items = as_detail("standings", {"league": league_id, "season": season})
        for item in items:
            groups = (item.get("league") or {}).get("standings") or []
            for group in groups:
                for row in group:
                    team_id = (row.get("team") or {}).get("id")
                    form = as_form(row.get("form"))
                    if team_id is not None and len(form) > len(forms.get(team_id, [])):
                        forms[team_id] = form
        cache[key] = forms
    return cache[key]


def as_prediction_percent(item):
    raw = ((item.get("predictions") or {}).get("percent") or {})
    try:
        values = tuple(
            int(str(raw[key]).strip().removesuffix("%"))
            for key in ("home", "draw", "away")
        )
    except (KeyError, TypeError, ValueError):
        return None
    if any(value < 0 or value > 100 for value in values):
        return None
    if sum(values) not in (99, 100, 101):
        return None
    return values


def match_form_record(match, team_id, source):
    if source == "as":
        fixture = match.get("fixture") or {}
        if (fixture.get("status") or {}).get("short") not in (
            "FT", "AET", "PEN"
        ):
            return None
        teams = match.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        goals = match.get("goals") or {}
        home_id = home.get("id")
        away_id = away.get("id")
        home_goals = goals.get("home")
        away_goals = goals.get("away")
        winner = "home" if home.get("winner") is True else "away" if away.get("winner") is True else None
    else:
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
        winner = {"HOME_TEAM": "home", "AWAY_TEAM": "away", "DRAW": "draw"}.get(score.get("winner"))

    if team_id not in (home_id, away_id):
        return None

    if winner is None:
        if not isinstance(home_goals, int) or not isinstance(away_goals, int):
            return None
        winner = "home" if home_goals > away_goals else "away" if away_goals > home_goals else "draw"

    symbol = "⚪️" if winner == "draw" else "🟢" if (winner == "home" and team_id == home_id) or (winner == "away" and team_id == away_id) else "🔴"
    goal_difference = (home_goals - away_goals) if team_id == home_id else (away_goals - home_goals) if isinstance(home_goals, int) and isinstance(away_goals, int) else None
    return symbol, goal_difference


def extract_team_form(matches, team_id, kickoff, source):
    date_key = "date" if source == "as" else "utcDate"
    def get_date(match):
        return (match.get("fixture") or {}).get(date_key) or "" if source == "as" else match.get(date_key) or ""

    form = []
    for match in sorted(matches, key=get_date, reverse=True):
        date_text = get_date(match)
        if not date_text:
            continue
        try:
            if parse_datetime(date_text) >= kickoff:
                continue
        except Exception:
            continue
        record = match_form_record(match, team_id, source)
        if record is not None:
            form.append(record)
        if len(form) == 5:
            break
    return form


def get_team_form_fd(team_id, kickoff):
    if not team_id:
        return []
    data = fd_request(
        f"{BASE_URL_FD}/teams/{team_id}/matches",
        {"status": "FINISHED", "limit": 20},
        f"فرم تیم {team_id}",
    )
    if not isinstance(data, dict):
        return []
    return extract_team_form(data.get("matches", []), team_id, kickoff, "fd")


def format_form(form):
    if not form:
        return NO_FORM
    symbols = " ".join(result for result, _ in form)
    if len(form) < 5:
        return f"{symbols} (فقط {len(form)} بازی معتبر)"
    return symbols


def calculate_probabilities(home_form, away_form):
    if len(home_form) != 5 or len(away_form) != 5:
        return None

    def strength(form):
        points = sum(3 if r == "🟢" else 1 if r == "⚪️" else 0 for r, _ in form)
        diffs = [d for _, d in form if d is not None]
        ppg = points / 5
        avg_diff = sum(diffs) / len(diffs) if diffs else 0
        score = 1 + ppg + 0.3 * max(-2, min(2, avg_diff))
        return max(0.1, score), ppg

    home_strength, home_ppg = strength(home_form)
    away_strength, away_ppg = strength(away_form)
    home_strength += 0.3
    draw_strength = 1.6 - 0.2 * min(2, abs(home_ppg - away_ppg))

    total = home_strength + draw_strength + away_strength
    home_pct = round(100 * home_strength / total)
    draw_pct = round(100 * draw_strength / total)
    away_pct = 100 - home_pct - draw_pct
    return home_pct, draw_pct, away_pct


def build_post(
    competition_name,
    home_name,
    away_name,
    match_date,
    match_time,
    home_form,
    away_form,
):
    h = escape(home_name)
    a = escape(away_name)
    probabilities = calculate_probabilities(home_form, away_form)

    if probabilities is None:
        prediction_text = "⚠️ اطلاعات کافی از ۵ بازی اخیر برای محاسبه درصدی ثبت نشده است."
    else:
        p_home, p_draw, p_away = probabilities
        prediction_text = f"🟢 برد {h}: {p_home}%\n⚪️ مساوی: {p_draw}%\n🔴 برد {a}: {p_away}%"

    return (
        f"🏆 <b>{escape(competition_name)}</b>\n"
        "⚽️ <b>تحلیل و برآورد مسابقهٔ امروز</b>\n\n"
        f"🏟 <b>{h}</b> 🆚 <b>{a}</b>\n"
        f"📅 تاریخ: {match_date} | ⏰ ساعت: {match_time}\n\n"
        "━━━━━━━━━━━━━━\n"
        "📊 <b>برآورد تقریبی بر اساس فرم:</b>\n"
        f"{prediction_text}\n\n"
        "━━━━━━━━━━━━━━\n"
        "📈 <b>فرم تا پنج بازی گذشته:</b>\n"
        f"▫️ {h}: {format_form(home_form)}\n"
        f"▫️ {a}: {format_form(away_form)}\n"
        "(🟢 برد | ⚪️ مساوی | 🔴 باخت)\n\n"
        "━━━━━━━━━━━━━━\n"
        f"🆔 {CHANNEL_ID}"
    )


def build_as_post(
    competition_name,
    home_name,
    away_name,
    match_date,
    match_time,
    home_form,
    away_form,
    api_percent,
):
    if api_percent is None:
        return build_post(
            competition_name,
            home_name,
            away_name,
            match_date,
            match_time,
            home_form,
            away_form,
        )

    home = escape(home_name)
    away = escape(away_name)
    home_pct, draw_pct, away_pct = api_percent

    return (
        f"🏆 <b>{escape(competition_name)}</b>\n"
        "⚽️ <b>تحلیل و برآورد مسابقهٔ امروز</b>\n\n"
        f"🏟 <b>{home}</b> 🆚 <b>{away}</b>\n"
        f"📅 تاریخ: {match_date} | ⏰ ساعت: {match_time}\n\n"
        "━━━━━━━━━━━━━━\n"
        "📊 <b>برآورد API-Sports:</b>\n"
        f"🟢 برد {home}: {home_pct}%\n"
        f"⚪️ مساوی: {draw_pct}%\n"
        f"🔴 برد {away}: {away_pct}%\n\n"
        "━━━━━━━━━━━━━━\n"
        "📈 <b>فرم بازی‌های اخیرِ ثبت‌شده در این رقابت:</b>\n"
        f"▫️ {home}: {format_form(home_form)}\n"
        f"▫️ {away}: {format_form(away_form)}\n"
        "(🟢 برد | ⚪️ مساوی | 🔴 باخت)\n\n"
        "━━━━━━━━━━━━━━\n"
        f"🆔 {CHANNEL_ID}"
    )


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
            f"مسابقات {code}",
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

        selected.sort(key=lambda entry: entry[0])
        if not selected:
            continue

        posts = []
        for match_time, match, match_date, kickoff in selected:
            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}
            home_form = get_team_form_fd(home.get("id"), kickoff)
            time.sleep(2)
            away_form = get_team_form_fd(away.get("id"), kickoff)
            time.sleep(2)

            posts.append(
                build_post(
                    league_name,
                    home.get("name") or "نامشخص",
                    away.get("name") or "نامشخص",
                    match_date,
                    match_time,
                    home_form,
                    away_form,
                )
            )
        posts_by_league[league_name] = posts

    return posts_by_league


def fetch_api_sports_matches():
    today = tehran_today()
    today_jalali = jalali_date_of(today)

    fixtures = as_request(
        {"date": today.isoformat(), "timezone": "Asia/Tehran"},
        "مسابقات امروز",
    )
    if fixtures is None:
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
            kickoff = parse_datetime(fixture["date"])
            match_date, match_time = convert_to_tehran(fixture["date"])
        except Exception:
            continue

        if match_date == today_jalali:
            selected.append((league_id, match_time, match_date, kickoff, item))

    selected.sort(key=lambda entry: entry[1])
    posts_by_competition = {}
    standings_cache = {}

    for league_id, match_time, match_date, kickoff, item in selected:
        fixture = item.get("fixture") or {}
        league = item.get("league") or {}
        teams = item.get("teams") or {}
        home_team = teams.get("home") or {}
        away_team = teams.get("away") or {}

        fixture_id = fixture.get("id")
        predictions = as_detail("predictions", {"fixture": fixture_id}) if fixture_id else []
        prediction = predictions[0] if predictions else {}

        prediction_teams = prediction.get("teams") or {}
        home_data = prediction_teams.get("home") or {}
        away_data = prediction_teams.get("away") or {}

        home_form = as_form((home_data.get("league") or {}).get("form"))
        away_form = as_form((away_data.get("league") or {}).get("form"))

        if len(home_form) < 5 or len(away_form) < 5:
            standings = as_standings_forms(league_id, league.get("season"), standings_cache)
            standing_home = standings.get(home_team.get("id"), [])
            standing_away = standings.get(away_team.get("id"), [])
            if len(standing_home) > len(home_form):
                home_form = standing_home
            if len(standing_away) > len(away_form):
                away_form = standing_away

        competition_name = API_SPORTS_COMPETITIONS[league_id]
        post = build_as_post(
            competition_name,
            home_team.get("name") or "نامشخص",
            away_team.get("name") or "نامشخص",
            match_date,
            match_time,
            home_form,
            away_form,
            as_prediction_percent(prediction),
        )
        posts_by_competition.setdefault(competition_name, []).append(post)

    return posts_by_competition


async def safe_send_message(bot, chat_id, text, parse_mode="HTML"):
    while True:
        try:
            await bot.send_message(
                chat_id=chat_id, text=text, parse_mode=parse_mode
            )
            return True
        except RetryAfter as exc:
            wait = float(exc.retry_after.total_seconds()) if isinstance(exc.retry_after, timedelta) else float(exc.retry_after)
            await asyncio.sleep(max(0, wait) + 2)
        except TelegramError:
            return False


async def main():
    print("🔄 در حال بررسی مسابقات امروز به وقت تهران...")

    posts_by_league = fetch_european_matches()
    posts_by_league.update(fetch_api_sports_matches())

    if not posts_by_league:
        print("⚠️ مسابقهٔ شروع‌نشده‌ای پیدا نشد.")
        return

    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        for competition_name, posts in posts_by_league.items():
            print(f"📌 ارسال {competition_name}: {len(posts)} بازی")
            header_sent = await safe_send_message(
                bot,
                CHANNEL_ID,
                f"📢 <b>بازی‌های امروز در {escape(competition_name)}</b>",
            )
            if not header_sent:
                continue

            for post in posts:
                await asyncio.sleep(3)
                await safe_send_message(bot, CHANNEL_ID, post)

    print("🏁 ارسال بازی‌های یافت‌شده تمام شد.")


if __name__ == "__main__":
    asyncio.run(main())
