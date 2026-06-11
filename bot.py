import requests
from datetime import datetime, timedelta
import os
import json

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

_FINNISH_IDS = None

def get_finnish_player_ids():
    global _FINNISH_IDS
    if _FINNISH_IDS is not None:
        return _FINNISH_IDS

    season = "20252026"
    ids = set()

    r = requests.get(
        f"https://api.nhle.com/stats/rest/en/skater/bios"
        f"?limit=-1&start=0&cayenneExp=seasonId={season} and nationalityCode=\"FIN\""
    ).json()
    for p in r.get("data", []):
        ids.add(p["playerId"])

    r2 = requests.get(
        f"https://api.nhle.com/stats/rest/en/goalie/bios"
        f"?limit=-1&start=0&cayenneExp=seasonId={season} and nationalityCode=\"FIN\""
    ).json()
    for p in r2.get("data", []):
        ids.add(p["playerId"])

    _FINNISH_IDS = ids
    return _FINNISH_IDS

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    })

def get_yesterday():
    return (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

def get_games(date):
    return requests.get(f"https://api-web.nhle.com/v1/score/{date}").json()

def get_boxscore(game_id):
    try:
        return requests.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore").json()
    except:
        return {}

def get_play_by_play(game_id):
    try:
        return requests.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play").json()
    except:
        return {}

def build_pbp_roster(pbp):
    roster = {}
    for spot in pbp.get("rosterSpots", []):
        pid = spot.get("playerId")
        if pid:
            roster[pid] = spot
    return roster

def format_goal(play, roster, home_team_id):
    details = play.get("details", {})
    period = play.get("periodDescriptor", {}).get("number", "?")
    time_in_period = play.get("timeInPeriod", "??:??")
    period_label = {1: "1.", 2: "2.", 3: "3.", 4: "JA", 5: "RL"}.get(period, str(period))

    scorer_id = details.get("scoringPlayerId")
    assist1_id = details.get("assist1PlayerId")
    assist2_id = details.get("assist2PlayerId")

    def get_name(pid):
        if not pid:
            return None
        p = roster.get(pid, {})
        fn = p.get("firstName", {}).get("default", "")
        ln = p.get("lastName", {}).get("default", "")
        return f"{fn} {ln}".strip() if fn or ln else f"#{pid}"

    scorer = get_name(scorer_id) or "Tuntematon"
    assists = [get_name(a) for a in [assist1_id, assist2_id] if a]

    goal_str = f"  {period_label} {time_in_period}  {scorer}"
    if assists:
        goal_str += f" ({', '.join(assists)})"

    # situationCode esim "1451":
    # [0] = vieraan MV (1=kentällä), [1] = vieraan kenttäpelaajat
    # [2] = kodin MV (1=kentällä),   [3] = kodin kenttäpelaajat
    situation = play.get("situationCode", "0000")
    try:
        away_skaters = int(situation[1])
        home_skaters = int(situation[2])
        if away_skaters != home_skaters:
            scorer_team_id = details.get("eventOwnerTeamId")
            scoring_team_is_home = (scorer_team_id == home_team_id)
            scoring_team_skaters = home_skaters if scoring_team_is_home else away_skaters
            other_team_skaters = away_skaters if scoring_team_is_home else home_skaters
            if scoring_team_skaters > other_team_skaters:
                goal_str += " ⚡YV"
            else:
                goal_str += " ✂️AV"
    except:
        pass

    goal_type = details.get("goalModifier", "")
    if goal_type == "penalty-shot":
        goal_str += " 🎯PS"
    elif goal_type == "empty-net":
        goal_str += " 🥅TM"

    return goal_str

def build_game_report(g):
    game_id = g.get("id")
    home = g["homeTeam"].get("placeName", {}).get("default", g["homeTeam"].get("abbrev", "HOME"))
    away = g["awayTeam"].get("placeName", {}).get("default", g["awayTeam"].get("abbrev", "AWAY"))
    hs = g["homeTeam"].get("score", 0)
    as_ = g["awayTeam"].get("score", 0)

    lines = [f"<b>🏒 {away} – {home}  {as_}–{hs}</b>"]

    period = g.get("periodDescriptor", {}).get("number", 3)
    if period == 4:
        lines[0] += "  <i>(JA)</i>"
    elif period == 5:
        lines[0] += "  <i>(RL)</i>"

    boxscore = get_boxscore(game_id)
    pbp = get_play_by_play(game_id)

    # Kotijoukkueen ID PBP:n ylätasolta
    home_team_id = pbp.get("homeTeam", {}).get("id")

    roster = build_pbp_roster(pbp)
    finnish_ids = get_finnish_player_ids()

    goals = [p for p in pbp.get("plays", []) if p.get("typeDescKey") == "goal"]
    if goals:
        lines.append("\n<b>Maalit:</b>")
        for play in goals:
            lines.append(format_goal(play, roster, home_team_id))

    finnish_stats = []
    pgstats = boxscore.get("playerByGameStats", {})
    for team_key in ["homeTeam", "awayTeam"]:
        team = pgstats.get(team_key, {})
        for pos in ["forwards", "defense"]:
            for player in team.get(pos, []):
                if player.get("playerId") in finnish_ids:
                    name = player.get("name", {}).get("default", "?")
                    g_stat = player.get("goals", 0)
                    a_stat = player.get("assists", 0)
                    pts = g_stat + a_stat
                    toi = player.get("toi", "0:00")
                    shots = player.get("sog", 0)
                    hits = player.get("hits", 0)
                    finnish_stats.append(
                        f"  {name}: {g_stat}+{a_stat}={pts}  🕐{toi}  🎯{shots} laukausta"
                        + (f"  💪{hits} taklaus" if hits else "")
                    )

    if finnish_stats:
        lines.append("\n<b>🇫🇮 Suomalaiset:</b>")
        lines.extend(finnish_stats)

    sog_home = boxscore.get("homeTeam", {}).get("sog", "-")
    sog_away = boxscore.get("awayTeam", {}).get("sog", "-")
    lines.append(f"\n📊 Laukaukset: {away} {sog_away} – {sog_home} {home}")

    return "\n".join(lines)

def run():
    date = get_yesterday()
    data = get_games(date)
    games = data.get("games", [])

    if not games:
        send("🏒 Ei NHL-pelejä viime yönä.")
        return

    header = f"🏒 <b>NHL – {date}</b>\n{'─'*25}"
    reports = [header]

    for g in games:
        try:
            reports.append(build_game_report(g))
        except Exception as e:
            home = g["homeTeam"].get("abbrev", "HOME")
            away = g["awayTeam"].get("abbrev", "AWAY")
            hs = g["homeTeam"].get("score", 0)
            as_ = g["awayTeam"].get("score", 0)
            reports.append(f"🏒 {away} – {home}  {as_}–{hs}  (tiedot puuttuu)")

    full_msg = "\n\n".join(reports)
    if len(full_msg) <= 4096:
        send(full_msg)
    else:
        send(header)
        for report in reports[1:]:
            send(report)

def check_updates():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    r = requests.get(url).json()
    for update in r.get("result", []):
        msg = update.get("message", {}).get("text", "")
        if msg.strip().lower() == "/nhl":
            run()

def debug():
    date = "2025-12-15"
    data = requests.get(f"https://api-web.nhle.com/v1/score/{date}").json()
    g = data["games"][0]
    game_id = g["id"]
    pbp = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play").json()
    penalties = [p for p in pbp.get("plays", []) if p.get("typeDescKey") == "penalty"]
    if penalties:
        send(json.dumps(penalties[0], indent=2)[:3900])
    else:
        send("Ei jaahyja loydy")

def main():
    check_updates()
    run()

debug()
