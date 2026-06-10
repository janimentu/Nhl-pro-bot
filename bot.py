import requests
from datetime import datetime, timedelta
import os
from openai import OpenAI

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

client = OpenAI(api_key=OPENAI_API_KEY)

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def get_games():
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    url = f"https://api-web.nhle.com/v1/score/{yesterday}"
    return requests.get(url).json()

def extract(data):
    games = []
    for g in data.get("games", []):
        home = g["homeTeam"]["placeName"]["default"]
        away = g["awayTeam"]["placeName"]["default"]
        hs = g["homeTeam"]["score"]
        as_ = g["awayTeam"]["score"]
        games.append(f"{away} - {home} {as_}-{hs}")
    return "\n".join(games)

def ai(text):
    prompt = f"""
Kirjoita NHL-yön suomenkielinen raportti:

- pelien tulokset
- tärkeimmät pelaajat
- suomalaiset jos löytyy
- lyhyt analyysi

PELIT:
{text}
"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return res.choices[0].message.content

def main():
    data = get_games()
    text = extract(data)

    if not text:
        send("Ei NHL-pelejä viime yönä.")
        return

    report = "🏒 NHL PRO YÖKOOSTE\n\n" + ai(text)
    send(report)

main()
