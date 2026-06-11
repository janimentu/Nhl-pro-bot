import requests
from datetime import datetime, timedelta
import os
import json

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

FINNISH_NAMES = [
    "Barkov", "Lundell", "Mikkola", "Räty", "Pesonen",
    "Kivenmäki", "Heiskanen", "Välimäki", "Nousiainen",
    "Kotkaniemi", "Laine", "Rantanen", "Granlund",
    "Käkönen", "Björninen", "Karjalainen", "Heponiemi",
    "Virtanen", "Kuokkanen", "Ruotsalainen", "Puistola",
    "Aaltonen", "Nurmi", "Peltonen", "Tyni", "Salo"
]

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
    url = f"https://api-web.nhle.com/v1/score/{date}"
    return requests.get(url).json()

def get_boxscore(game_id):
    url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
    try:
        return requests.get(url).json()
    except:
        return {}

def get_play_by_play(game_id):
    url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
    try:
        return requests.get(url).json()
    except:
        return {}

def is_finnish(name):
    return any(fn.lower() in name.lower() for fn in FINNISH_NAMES)

def format_toi(seconds):
    if not seconds:
        return "0:00"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"

def build_pbp_roster(pbp):
    roster = {}
    for spot in pbp.get("rosterSpots", []):
        pid = spot.get("playerId")
        if pid:
            roster[pid] = spot
    return roster

def format_goal(play, roster):
    details = play.get("details", {})
    period = play.get("periodDescriptor", {}).get("number", "?")
    time_in_period = play.get("timeInPeriod", "??:??")

    period_label = {1: "1.", 2: "2.", 3: "3.", 4: "JA", 5: "RL"}.get(period, str(period))

    scorer_id = details.get("scoringPlayerId")
    assist1_id = details.get("assist1PlayerId")
    assist2_id = details.get("assist2PlayerId")

    def get_name(pid):
        if not pid or not roster:
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

    situation = play.get("situationCode", "0000")
    try:
        away_skaters = int(situation[0])
        home_skaters = int(situation[2])
        if away_skaters != home_skaters:
            if away_skaters > home_skaters:
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

    return goal_str, scorer_id, assist1_id, assist2_id

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
    roster = build_pbp_roster(pbp)

    goals = [p for p in pbp.get("plays", []) if p.get("typeDescKey") == "goal"]
    if goals:
        lines.append("\n<b>Maalit:</b>")
        for play in goals:
            goal_line, *_ = format_goal(play, roster)
            lines.append(goal_line)

    finnish_stats = []
    for team_key in ["homeTeam", "awayTeam"]:
        team = boxscore.get(team_key, {})
        stats = team.get("playerByGameStats", {})
        for pos in ["forwards", "defense"]:
            for player in stats.get(pos, []):
                ln = player.get("lastName", {}).get("default", "")
                fn = player.get("firstName", {}).get("default", "")
                if is_finnish(ln):
                    g_stat = player.get("goals", 0)
                    a_stat = player.get("assists", 0)
                    pts = g_stat + a_stat
                    toi = format_toi(player.get("toi"))
                    shots = player.get("shots", 0)
                    hits = player.get("hits", 0)
                    full = f"{fn} {ln}"
                    finnish_stats.append(
                        f"  {full}: {g_stat}+{a_stat}={pts}  🕐{toi}  🎯{shots} laukausta"
                        + (f"  💪{hits} taklaus" if hits else "")
                    )

    if finnish_stats:
        lines.append("\n<b>🇫🇮 Suomalaiset:</b>")
        lines.extend(finnish_stats)

    try:
        home_stats = boxscore.get("homeTeam", {}).get("teamGameStats", [])
        away_stats = boxscore.get("awayTeam", {}).get("teamGameStats", [])

        def get_stat(stats_list, category):
            for s in stats_list:
                if s.get("category") == category:
                    return s.get("value", "-")
            return "-"

        sog_home = get_stat(home_stats, "sog")
        sog_away = get_stat(away_stats, "sog")
        pp_home = get_stat(home_stats, "powerPlayPctg")
        pp_away = get_stat(away_stats, "powerPlayPctg")

        lines.append(f"\n📊 Laukaukset: {away} {sog_away} – {sog_home} {home}")
        lines.append(f"⚡ PP%: {away} {pp_away} – {pp_home} {home}")
    except:
        pass

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


# ============================================================
# DEBUG - poista kun bugit on korjattu, palauta main() tilalle
# ============================================================

date = "2025-12-15"
data = requests.get(f"https://api-web.nhle.com/v1/score/{date}").json()
g = data["games"][0]
game_id = g["id"]

pbp = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play").json()
goals = [p for p in pbp.get("plays", []) if p.get("typeDescKey") == "goal"]
print("=== GOAL situationCode ===")
print(json.dumps({
    "situationCode": goals[0].get("situationCode"),
    "details": goals[0].get("details")
}, indent=2))

box = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore").json()
print("\n=== TEAM GAME STATS ===")
print(json.dumps(box.get("homeTeam", {}).get("teamGameStats"), indent=2))

fwd = box.get("homeTeam", {}).get("playerByGameStats", {}).get("forwards", [])
print("\n=== PLAYER FIELDS ===")
if fwd:
    print(json.dumps(list(fwd[0].keys()), indent=2))
    print("toi arvo:", fwd[0].get("toi"))
    print("playerId:", fwd[0].get("playerId"))

# ============================================================
# Palauta tämä käyttöön kun debug on valmis:
# def main():
#     check_updates()
#     run()
#
# main()
# ============================================================
