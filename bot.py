
import os
import html
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

BASE_NHL = "https://api-web.nhle.com/v1"
STATS_NHL = "https://api.nhle.com/stats/rest/en"
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

TIMEOUT = 20
MAX_MESSAGE_LENGTH = 3900

logging.basicConfig(level=logging.INFO)
session = requests.Session()
_FINNISH_IDS = None


def get_json(url, params=None):
    """Hae JSON-vastaus aikakatkaisulla ja virheenkäsittelyllä."""
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_finnish_player_ids():
    """Hae suomalaiset pelaajat nykyiseltä ja edelliseltä kaudelta."""
    global _FINNISH_IDS

    if _FINNISH_IDS is not None:
        return _FINNISH_IDS

    ids = set()

    for season in ("20262027", "20252026"):
        for position in ("skater", "goalie"):
            url = f"{STATS_NHL}/{position}/bios"
            params = {
                "limit": -1,
                "start": 0,
                "cayenneExp": (
                    f'seasonId={season} and nationalityCode="FIN"'
                ),
            }

            try:
                data = get_json(url, params=params)
                for player in data.get("data", []):
                    pid = player.get("playerId")
                    if pid:
                        ids.add(pid)
            except requests.RequestException:
                logging.warning(
                    "Suomalaisten haku epäonnistui: %s, kausi %s",
                    position, season
                )

    _FINNISH_IDS = ids
    logging.info("Suomalaisia pelaaja-ID:itä löytyi %d", len(ids))
    return ids


def send(message):
    """Lähetä Telegram-viesti ja jaa pitkä teksti tarvittaessa."""
    chunks = []
    current = ""

    # Raportin rivit sisältävät valmiiksi tasapainotetut HTML-tagit.
    for line in message.split("\n"):
        candidate = f"{current}\n{line}" if current else line

        if len(candidate) <= MAX_MESSAGE_LENGTH:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = line

            # Varasuoja poikkeuksellisen pitkälle yksittäiselle riville.
            while len(current) > MAX_MESSAGE_LENGTH:
                chunks.append(current[:MAX_MESSAGE_LENGTH])
                current = current[MAX_MESSAGE_LENGTH:]

    if current:
        chunks.append(current)

    for chunk in chunks:
        response = session.post(
            TELEGRAM_URL,
            data={
                "chat_id": CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()

        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram-virhe: {result}")


def get_yesterday():
    """Edellinen kalenteripäivä Suomen ajassa."""
    today = datetime.now(ZoneInfo("Europe/Helsinki")).date()
    return (today - timedelta(days=1)).isoformat()


def get_games(date):
    return get_json(f"{BASE_NHL}/score/{date}").get("games", [])


def get_boxscore(game_id):
    try:
        return get_json(f"{BASE_NHL}/gamecenter/{game_id}/boxscore")
    except (requests.RequestException, ValueError):
        logging.exception("Boxscore-haku epäonnistui: %s", game_id)
        return {}


def get_play_by_play(game_id):
    try:
        return get_json(
            f"{BASE_NHL}/gamecenter/{game_id}/play-by-play"
        )
    except (requests.RequestException, ValueError):
        logging.exception("Play-by-play-haku epäonnistui: %s", game_id)
        return {}


def build_pbp_roster(pbp):
    roster = {}
    for spot in pbp.get("rosterSpots", []):
        pid = spot.get("playerId")
        if pid:
            roster[pid] = spot
    return roster


def localized(value):
    if isinstance(value, dict):
        return value.get("default", "")
    return value or ""


def format_name(pid, roster, finnish_ids):
    if not pid:
        return None

    player = roster.get(pid, {})
    first = localized(player.get("firstName"))
    last = localized(player.get("lastName"))
    name = f"{first} {last}".strip() or f"#{pid}"
    name = html.escape(name)

    if pid in finnish_ids:
        return f"<b>{name}</b>"
    return name


def format_goal(play, roster, home_team_id, finnish_ids):
    details = play.get("details", {})
    period = play.get("periodDescriptor", {}).get("number", "?")
    time_in_period = html.escape(play.get("timeInPeriod", "??:??"))

    period_label = {
        1: "1.", 2: "2.", 3: "3.", 4: "JA", 5: "RL"
    }.get(period, str(period))

    scorer_id = details.get("scoringPlayerId")
    assists_ids = [
        details.get("assist1PlayerId"),
        details.get("assist2PlayerId"),
    ]

    away_score = details.get("awayScore", "?")
    home_score = details.get("homeScore", "?")
    score = f"{away_score}–{home_score}"

    scorer = format_name(scorer_id, roster, finnish_ids) or "Tuntematon"
    assists = [
        format_name(pid, roster, finnish_ids)
        for pid in assists_ids if pid
    ]
    assists = [name for name in assists if name]

    text = f"  {period_label} {time_in_period} ({score}) {scorer}"
    if assists:
        text += f" ({', '.join(assists)})"

    situation = str(play.get("situationCode", ""))
    if len(situation) >= 3 and situation[1:3].isdigit():
        away_skaters = int(situation[1])
        home_skaters = int(situation[2])

        if away_skaters != home_skaters:
            scorer_team_id = details.get("eventOwnerTeamId")
            scoring_home = scorer_team_id == home_team_id
            scoring_count = home_skaters if scoring_home else away_skaters
            other_count = away_skaters if scoring_home else home_skaters

            if scoring_count > other_count:
                text += " ⚡YV"
            else:
                text += " ✂️AV"

    goal_type = details.get("goalModifier", "")
    if goal_type == "penalty-shot":
        text += " 🎯PS"
    elif goal_type == "empty-net":
        text += " 🥅TM"

    return text


def format_penalty(play, roster, finnish_ids):
    details = play.get("details", {})
    period = play.get("periodDescriptor", {}).get("number", "?")
    time_in_period = html.escape(play.get("timeInPeriod", "??:??"))

    period_label = {
        1: "1.", 2: "2.", 3: "3.", 4: "JA", 5: "RL"
    }.get(period, str(period))

    pid = details.get("committedByPlayerId")
    name = format_name(pid, roster, finnish_ids) or "Tuntematon"
    description = html.escape(
        details.get("descKey", "jäähy").replace("-", " ")
    )
    duration = details.get("duration", "?")

    return (
        f"  {period_label} {time_in_period} {name} – "
        f"{description} ({duration} min)"
    )


def build_game_report(game):
    game_id = game.get("id")
    home_team = game.get("homeTeam", {})
    away_team = game.get("awayTeam", {})

    home = html.escape(
        localized(home_team.get("placeName"))
        or home_team.get("abbrev", "HOME")
    )
    away = html.escape(
        localized(away_team.get("placeName"))
        or away_team.get("abbrev", "AWAY")
    )

    home_score = home_team.get("score", 0)
    away_score = away_team.get("score", 0)

    lines = [
        f"<b>🏒 {away} – {home}  {away_score}–{home_score}</b>"
    ]

    period_descriptor = game.get("periodDescriptor", {})
    period_type = period_descriptor.get("periodType", "")
    period_number = period_descriptor.get("number")

    if period_type == "OT" or period_number == 4:
        lines[0] += "  <i>(JA)</i>"
    elif period_type == "SO" or period_number == 5:
        lines[0] += "  <i>(RL)</i>"

    boxscore = get_boxscore(game_id)
    pbp = get_play_by_play(game_id)
    home_team_id = pbp.get("homeTeam", {}).get("id")
    roster = build_pbp_roster(pbp)
    finnish_ids = get_finnish_player_ids()

    goals = [
        play for play in pbp.get("plays", [])
        if play.get("typeDescKey") == "goal"
    ]
    if goals:
        lines.append("\n<b>Maalit:</b>")
        lines.extend(
            format_goal(play, roster, home_team_id, finnish_ids)
            for play in goals
        )

    penalties = [
        play for play in pbp.get("plays", [])
        if play.get("typeDescKey") == "penalty"
    ]
    if penalties:
        lines.append("\n<b>Jäähyt:</b>")
        lines.extend(
            format_penalty(play, roster, finnish_ids)
            for play in penalties
        )

    finnish_stats = []
    stats = boxscore.get("playerByGameStats", {})

    for team_key in ("homeTeam", "awayTeam"):
        team = stats.get(team_key, {})

        for position in ("forwards", "defense"):
            for player in team.get(position, []):
                if player.get("playerId") not in finnish_ids:
                    continue

                name = html.escape(
                    localized(player.get("name")) or "?"
                )
                goals_count = player.get("goals", 0) or 0
                assists_count = player.get("assists", 0) or 0
                points = goals_count + assists_count
                toi = html.escape(str(player.get("toi", "0:00")))
                shots = player.get("sog", 0) or 0
                hits = player.get("hits", 0) or 0

                stat_line = (
                    f"  {name}: {goals_count}+{assists_count}={points}"
                    f"  🕐{toi}  🎯{shots} laukausta"
                )
                if hits:
                    stat_line += f"  💪{hits} taklausta"

                finnish_stats.append(stat_line)

    if finnish_stats:
        lines.append("\n<b>🇫🇮 Suomalaiset:</b>")
        lines.extend(finnish_stats)

    home_shots = boxscore.get("homeTeam", {}).get("sog", "-")
    away_shots = boxscore.get("awayTeam", {}).get("sog", "-")
    lines.append(
        f"\n📊 Laukaukset: {away} {away_shots} – "
        f"{home_shots} {home}"
    )

    return "\n".join(lines)


def run():
    date = get_yesterday()
    logging.info("Haetaan NHL-ottelut päivältä %s", date)

    try:
        games = get_games(date)
    except (requests.RequestException, ValueError):
        logging.exception("NHL-tulosten haku epäonnistui")
        send(f"⚠️ NHL-tulosten haku epäonnistui päivältä {date}.")
        raise

    if not games:
        send(f"🏒 Ei NHL-pelejä päivänä {date}.")
        return

    header = f"🏒 <b>NHL – {date}</b>\n{'─' * 20}"
    send(header)

    for game in games:
        try:
            report = build_game_report(game)
        except Exception:
            logging.exception(
                "Otteluraportin muodostaminen epäonnistui: %s",
                game.get("id")
            )
            home = html.escape(
                game.get("homeTeam", {}).get("abbrev", "HOME")
            )
            away = html.escape(
                game.get("awayTeam", {}).get("abbrev", "AWAY")
            )
            home_score = game.get("homeTeam", {}).get("score", 0)
            away_score = game.get("awayTeam", {}).get("score", 0)
            report = (
                f"🏒 {away} – {home} {away_score}–{home_score}\n"
                "⚠️ Ottelun yksityiskohtaisia tietoja ei saatu."
            )

        send(report)


if __name__ == "__main__":
    run()
