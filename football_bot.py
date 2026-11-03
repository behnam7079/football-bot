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


# لیگ‌های اروپایی؛ منبع: football-data.org
EUROPE_LEAGUES = {
    "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 لیگ برتر انگلیس",
    "SA": "🇮🇹 سری آ ایتالیا",
    "BL1": "🇩🇪 بوندس‌لیگا آلمان",
    "PD": "🇪🇸 لالیگا اسپانیا",
    "FL1": "🇫🇷 لوشامپیونه فرانسه",
    "CL": "🇪🇺 لیگ قهرمانان اروپا",
    "EL": "🇪🇺 لیگ اروپا",
}

# لیگ‌های ایران و آسیا؛ منبع: API-Sports
ASIAN_AND_IRAN_LEAGUES = {
    290: "🇮🇷 لیگ برتر ایران",
    17: "🌏 لیگ نخبگان آسیا",
}

# جام‌های حذفی؛ منبع: API-Sports
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
    """تاریخ API را به یک زمان دارای منطقهٔ زمانی تبدیل می‌کند."""
    moment = datetime.fromisoformat(date_text.strip().replace("Z", "+00:00"))

    if moment.tzinfo is None:
        moment = pytz.UTC.localize(moment)

    return moment


def convert_to_tehran(date_text):
    local = parse_datetime(date_text).astimezone(TEHRAN)
    return jalali_date_of(local.date()), local.strftime("%H:%M")


def fd_request(url, params, label):
    """درخواست football-data.org؛ خطا را در لاگ نشان می‌دهد."""
    for attempt in range(2):
        try:
            response = requests.get(
                url,
                headers={"X-Auth-Token": FOOTBALL_API_KEY},
                params=params,
                timeout=20,
            )

            if response.status_code == 429 and attempt == 0:
                print(f"⚠️ محدودیت موقت football-data.org برای {label}؛ ۶۵ ثانیه صبر")
                time.sleep(65)
                continue

            if response.status_code != 200:
                print(
                    f"❌ football-data.org / {label}: "
                    f"HTTP {response.status_code}"
                )
                return None

            return response.json()

        except (requests.RequestException, ValueError) as exc:
            print(f"❌ football-data.org / {label}: {exc}")
            return None

    return None


def as_request(params, label):
    """
    درخواست API-Sports.
    None یعنی خطا؛ فهرست خالی یعنی درخواست موفق اما بدون مسابقه.
    """
    try:
        response = requests.get(
            f"{BASE_URL_AF}/fixtures",
            headers={"x-apisports-key": API_FOOTBALL_KEY},
            params=params,
            timeout=30,
        )

        remaining = response.headers.get(
            "x-ratelimit-requests-remaining", "نامشخص"
        )

        try:
            data = response.json()
        except ValueError:
            print(
                f"❌ API-Sports / {label}: HTTP {response.status_code}؛ "
                "پاسخ JSON معتبر نیست"
            )
            return None

        errors = data.get("errors") if isinstance(data, dict) else None

        if response.status_code != 200 or errors:
            # اگر متن خطا اتفاقاً حاوی کلید بود، کلید در لاگ چاپ نشود.
            error_text = str(errors).replace(
                API_FOOTBALL_KEY, "[REDACTED]"
            )
            print(
                f"❌ API-Sports / {label}: HTTP {response.status_code}؛ "
                f"errors={error_text}؛ سهمیهٔ باقی‌مانده={remaining}"
            )
            return None

        matches = data.get("response")
        if not isinstance(matches, list):
            print(
                f"❌ API-Sports / {label}: "
                "فهرست response در پاسخ موجود نیست"
            )
            return None

        print(
            f"🔎 API-Sports / {label}: HTTP 200؛ "
            f"results={data.get('results')}؛ "
            f"سهمیهٔ باقی‌مانده={remaining}"
        )
        return matches

    except requests.RequestException as exc:
        print(f"❌ API-Sports / {label}: خطای اتصال: {exc}")
        return None


def match_form_record(match, team_id, source):
    """
    نتیجهٔ یک بازی را برای تیم موردنظر برمی‌گرداند:
    (نماد نتیجه، اختلاف گل از دید تیم)
    """
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

        if home.get("winner") is True:
            winner = "home"
        elif away.get("winner") is True:
            winner = "away"
        elif home.get("winner") is False and away.get("winner") is False:
            winner = "draw"
        else:
            winner = None

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

        winner = {
            "HOME_TEAM": "home",
            "AWAY_TEAM": "away",
            "DRAW": "draw",
        }.get(score.get("winner"))

    if team_id not in (home_id, away_id):
        return None

    if winner is None:
        if not isinstance(home_goals, int) or not isinstance(
            away_goals, int
        ):
            return None

        if home_goals > away_goals:
            winner = "home"
        elif away_goals > home_goals:
            winner = "away"
        else:
            winner = "draw"

    if winner == "draw":
        symbol = "⚪️"
    elif (
        (winner == "home" and team_id == home_id)
        or (winner == "away" and team_id == away_id)
    ):
        symbol = "🟢"
    else:
        symbol = "🔴"

    goal_difference = None
    if isinstance(home_goals, int) and isinstance(away_goals, int):
        goal_difference = (
            home_goals - away_goals
            if team_id == home_id
            else away_goals - home_goals
        )

    return symbol, goal_difference


def extract_team_form(matches, team_id, kickoff, source):
    """حداکثر پنج بازی معتبرِ پیش از شروع مسابقه را انتخاب می‌کند."""
    date_key = "date" if source == "as" else "utcDate"

    def get_date(match):
        if source == "as":
            return (match.get("fixture") or {}).get(date_key) or ""
        return match.get(date_key) or ""

    form = []

    for match in sorted(matches, key=get_date, reverse=True):
        date_text = get_date(match)
        if not date_text:
            continue

        try:
            if parse_datetime(date_text) >= kickoff:
                continue
        except (TypeError, ValueError):
            continue

        record = match_form_record(match, team_id, source)
        if record is not None:
            form.append(record)

        if len(form) == 5:
            break

    return form


def get_team_form_fd(team_id, kickoff):
    if not team_id:
        print("⚠️ football-data.org: شناسهٔ تیم موجود نیست")
        return []

    data = fd_request(
        f"{BASE_URL_FD}/teams/{team_id}/matches",
        {"status": "FINISHED", "limit": 20},
        f"فرم تیم {team_id}",
    )

    if not isinstance(data, dict):
        return []

    matches = data.get("matches")
    if not isinstance(matches, list):
        print(f"❌ football-data.org: فهرست بازی‌های تیم {team_id} موجود نیست")
        return []

    form = extract_team_form(matches, team_id, kickoff, "fd")
    print(f"📈 football-data.org: تیم {team_id}؛ {len(form)} بازی معتبر")
    return form


def get_team_form_as(team_id, kickoff, cache):
    if not team_id:
        print("⚠️ API-Sports: شناسهٔ تیم موجود نیست")
        return []

    # بازی‌های دریافتی هر تیم در همین اجرای ربات دوباره درخواست نمی‌شوند.
    if team_id not in cache:
        cache[team_id] = as_request(
            {"team": team_id, "last": 30},
            f"فرم تیم {team_id}",
        )
        time.sleep(2)

    matches = cache[team_id]
    if matches is None:
        return []

    form = extract_team_form(matches, team_id, kickoff, "as")
    print(f"📈 API-Sports: تیم {team_id}؛ {len(form)} بازی معتبر")
    return form


def format_form(form):
    if not form:
        return NO_FORM

    symbols = " ".join(result for result, _ in form)

    if len(form) < 5:
        return f"{symbols} (فقط {len(form)} بازی معتبر در دسترس)"

    return symbols


def calculate_probabilities(home_form, away_form):
    """
    تخمین ساده بر اساس پنج نتیجهٔ اخیر، اختلاف گل و امتیاز میزبانی.
    این خروجی احتمال آماریِ تضمین‌شده یا پیش‌بینی رسمی API نیست.
    """
    if len(home_form) != 5 or len(away_form) != 5:
        return None

    def strength(form):
        points = sum(
            3 if result == "🟢" else 1 if result == "⚪️" else 0
            for result, _ in form
        )
        known_goal_differences = [
            difference
            for _, difference in form
            if difference is not None
        ]

        points_per_match = points / 5

        if known_goal_differences:
            average_goal_difference = (
                sum(known_goal_differences)
                / len(known_goal_differences)
            )
        else:
            average_goal_difference = 0

        # اثر اختلاف گل محدود می‌شود تا یک بازی غیرعادی غلبه نکند.
        average_goal_difference = max(
            -2, min(2, average_goal_difference)
        )

        score = (
            1
            + points_per_match
            + 0.3 * average_goal_difference
        )
        return max(0.1, score), points_per_match

    home_strength, home_ppg = strength(home_form)
    away_strength, away_ppg = strength(away_form)

    home_strength += 0.3
    draw_strength = 1.6 - 0.2 * min(
        2, abs(home_ppg - away_ppg)
    )

    total = home_strength + draw_strength + away_strength
    home_percentage = round(100 * home_strength / total)
    draw_percentage = round(100 * draw_strength / total)
    away_percentage = (
        100 - home_percentage - draw_percentage
    )

    return (
        home_percentage,
        draw_percentage,
        away_percentage,
    )


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
        prediction_text = (
            "⚠️ برای محاسبهٔ برآورد، پنج بازی معتبر "
            "برای هر دو تیم دریافت نشد."
        )
    else:
        p_home, p_draw, p_away = probabilities
        prediction_text = (
            f"🟢 برد {h}: {p_home}%\n"
            f"⚪️ مساوی: {p_draw}%\n"
            f"🔴 برد {a}: {p_away}%"
        )

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

        for match in data.get("matches") or []:
            if match.get("status") not in ("SCHEDULED", "TIMED"):
                continue

            try:
                kickoff = parse_datetime(match["utcDate"])
                match_date, match_time = convert_to_tehran(
                    match["utcDate"]
                )
            except (KeyError, TypeError, ValueError):
                continue

            if match_date == today_jalali:
                selected.append(
                    (match_time, match, match_date, kickoff)
                )

        selected.sort(key=lambda entry: entry[0])
        if not selected:
            continue

        posts = []

        for match_time, match, match_date, kickoff in selected:
            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}

            home_form = get_team_form_fd(
                home.get("id"), kickoff
            )
            time.sleep(2)

            away_form = get_team_form_fd(
                away.get("id"), kickoff
            )
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
        {
            "date": today.isoformat(),
            "timezone": "Asia/Tehran",
        },
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
            match_date, match_time = convert_to_tehran(
                fixture["date"]
            )
        except (KeyError, TypeError, ValueError):
            continue

        if match_date == today_jalali:
            selected.append(
                (
                    league_id,
                    match_time,
                    match_date,
                    kickoff,
                    item,
                )
            )

    selected.sort(key=lambda entry: entry[1])

    posts_by_competition = {}
    team_cache = {}

    for league_id, match_time, match_date, kickoff, item in selected:
        teams = item.get("teams") or {}
        home_team = teams.get("home") or {}
        away_team = teams.get("away") or {}

        home_form = get_team_form_as(
            home_team.get("id"), kickoff, team_cache
        )
        away_form = get_team_form_as(
            away_team.get("id"), kickoff, team_cache
        )

        competition_name = API_SPORTS_COMPETITIONS[league_id]
        post = build_post(
            competition_name,
            home_team.get("name") or "نامشخص",
            away_team.get("name") or "نامشخص",
            match_date,
            match_time,
            home_form,
            away_form,
        )

        posts_by_competition.setdefault(
            competition_name, []
        ).append(post)

    return posts_by_competition


async def safe_send_message(bot, chat_id, text, parse_mode="HTML"):
    while True:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
            )
            return True

        except RetryAfter as exc:
            wait = exc.retry_after

            if isinstance(wait, timedelta):
                wait = wait.total_seconds()

            wait_seconds = max(0, float(wait)) + 2
            print(
                f"⏳ محدودیت تلگرام؛ "
                f"{wait_seconds:.0f} ثانیه صبر و تلاش مجدد"
            )
            await asyncio.sleep(wait_seconds)

        except TelegramError as exc:
            print(f"❌ خطا در ارسال پیام تلگرام: {exc}")
            return False


async def main():
    print("🔄 در حال بررسی مسابقات امروز به وقت تهران...")

    posts_by_league = fetch_european_matches()
    posts_by_league.update(fetch_api_sports_matches())

    if not posts_by_league:
        print(
            "⚠️ مسابقهٔ شروع‌نشده‌ای پیدا نشد، "
            "یا دریافت اطلاعات مسابقات با خطا روبه‌رو شد؛ "
            "لاگ‌های بالا را بررسی کن."
        )
        return

    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        for competition_name, posts in posts_by_league.items():
            print(
                f"📌 ارسال {competition_name}: "
                f"{len(posts)} بازی"
            )

            header_sent = await safe_send_message(
                bot,
                CHANNEL_ID,
                (
                    "📢 <b>بازی‌های امروز در "
                    f"{escape(competition_name)}</b>"
                ),
            )

            if not header_sent:
                continue

            for post in posts:
                await asyncio.sleep(3)
                await safe_send_message(
                    bot, CHANNEL_ID, post
                )

    print("🏁 ارسال بازی‌های یافت‌شده تمام شد.")


if __name__ == "__main__":
    asyncio.run(main())
