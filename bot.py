import requests
from datetime import datetime, timedelta
import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def get_games():
    yesterday = "2025-12-15"
    url = f"https://api-web.nhle.com/v1/score/{yesterday}"
    return requests.get(url).json()

def extract(data):
    games = []

    for g in data.get("games", []):
        try:
            home = g["homeTeam"].get("placeName", {}).get("default", g["homeTeam"].get("abbrev", "HOME"))
            away = g["awayTeam"].get("placeName", {}).get("default", g["awayTeam"].get("abbrev", "AWAY"))

            hs = g["homeTeam"].get("score", 0)
            as_ = g["awayTeam"].get("score", 0)

            games.append(f"{away} - {home} {as_}-{hs}")
        except:
            continue

    return games

def build_report(games):
    if not games:
        return "Ei NHL-pelejä viime yönä."

    msg = "🏒 NHL RAPORTTI\n\n"

    for g in games:
        msg += g + "\n"

    msg += "\n🔥 Yhteenveto:\n- Automaattinen NHL-kooste\n"

    return msg

def run():
    data = get_games()
    games = extract(data)
    send(build_report(games))

def check_updates():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    r = requests.get(url).json()

    for update in r.get("result", []):
        msg = update.get("message", {}).get("text", "")

        if msg.strip().lower() == "/nhl":
            run()

def main():
    check_updates()
    run()

main()
