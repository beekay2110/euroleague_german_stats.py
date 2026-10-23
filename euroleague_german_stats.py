import os
import sys
import time
import requests
from datetime import datetime, timedelta
from google import genai
from google.genai.errors import ServerError

# 1. Konfiguration & Secrets
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or "8834628661"

if not GEMINI_API_KEY:
    print("Fehler: GEMINI_API_KEY ist nicht in den GitHub Secrets konfiguriert.")
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)

# Die 3 EuroLeague-Legionäre
TARGET_PLAYERS = [
    "Maodo Lo", "Isaac Bonga", "David Kramer"
]

# 2. Scoreboard & Boxscores via ESPN API (EuroLeague)
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
print(f"Hole EuroLeague Scoreboard-Daten via ESPN für {yesterday}...")

espn_url_el = f"https://site.api.espn.com/apis/site/v2/sports/basketball/euroleague/scoreboard?dates={yesterday}"

try:
    response = requests.get(espn_url_el, timeout=15)
    if response.status_code != 200:
        espn_url_el = f"https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=basketball&league=eur.1&dates={yesterday}"
        response = requests.get(espn_url_el, timeout=15)
        
    response.raise_for_status()
    data = response.json()
except Exception as e:
    print(f"Fehler beim Abruf der ESPN API: {e}")
    sys.exit(1)

events = data.get("events", []) if "events" in data else data.get("sports", [{}])[0].get("leagues", [{}])[0].get("events", [])

if not events:
    print(f"Keine EuroLeague-Spiele für den {yesterday} gefunden.")

game_summaries = []

for event in events:
    game_name = event.get("name", "EuroLeague Game")
    status = event.get("status", {}).get("type", {}).get("detail", "")
    event_id = event.get("id")
    
    summary_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/euroleague/summary?event={event_id}"
    
    boxscore_info = {}
    try:
        sum_res = requests.get(summary_url, timeout=10)
        if sum_res.status_code == 200:
            sum_data = sum_res.json()
            boxscore_info = sum_data.get("boxscore", {})
    except Exception as e:
        print(f"Konnte Details für Spiel {event_id} nicht laden: {e}")

    game_summaries.append({
        "game": game_name,
        "status": status,
        "boxscore": boxscore_info
    })

# 3. Prompt für Gemini erstellen
prompt = f"""
Du bist ein deutscher Basketball-Journalist für ein tägliches Telegram-Update über deutsche EuroLeague-Legionäre.
Hier sind die offiziellen EuroLeague Spieldaten und Boxscores der letzten Nacht ({yesterday}):

{game_summaries}

Deine Aufgabe:
1. Analysiere die Daten speziell bezüglich dieser 3 deutschen Spieler:
   - Maodo Lo (Žalgiris Kaunas)
   - Isaac Bonga (Panathinaikos Athen)
   - David Kramer (Roter Stern Belgrad)

2. Erstelle ein kompaktes, übersichtliches Update auf Deutsch für Telegram.
3. Wenn einer der Spieler gespielt hat, nenne seine Statistiken (Punkte, Rebounds, Assists, Minuten, Wurfquote) und das Spielergebnis seines Teams.
4. Falls sein Team gespielt hat, der Spieler aber DNP (Did Not Play) war oder verletzt fehlte, erwähne das kurz.
5. Falls die Spieler diese Nacht spielfrei hatten, fange dies kurz ab (z. B. "Gestern keine EuroLeague-Einsätze für unsere Legionäre.").
6. Verwende passendes Markdown (fett, kursiv) und Emojis (🇪🇺, 🏀) für gute Lesbarkeit.
"""

# 4. Gemini Bericht generieren
MODELS_TO_TRY = ["gemini-3.8-flash", "gemini-1.5-flash"]
response_text = None

for model_name in MODELS_TO_TRY:
    print(f"Versuche Generierung mit Modell: {model_name}...")
    max_retries = 5
    backoff_delay = 5

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            response_text = response.text
            if response_text:
                break
        except ServerError as e:
            if e.code == 503:
                print(f"Modell {model_name} überlastet (503). Pause {backoff_delay}s... ({attempt + 1}/{max_retries})")
                time.sleep(backoff_delay)
                backoff_delay *= 2
            else:
                print(f"ServerError bei {model_name}: {e}")
                break
        except Exception as e:
            print(f"Fehler bei Modell {model_name}: {e}")
            break

    if response_text:
        print(f"Erfolgreich generiert mit {model_name}!")
        break

if not response_text:
    print("Keines der Gemini-Modelle konnte eine Antwort liefern. Abbruch.")
    sys.exit(1)

print("--- Generierter Bericht ---")
print(response_text)

# 5. Telegram Nachricht senden
if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": response_text,
        "parse_mode": "Markdown"
    }
    res = requests.post(url, json=payload)
    if res.status_code == 200:
        print("Erfolgreich an Telegram gesendet!")
    else:
        payload.pop("parse_mode", None)
        res_fallback = requests.post(url, json=payload)
        if res_fallback.status_code == 200:
            print("Erfolgreich als Plain Text an Telegram gesendet.")
        else:
            print(f"Telegram-Fehler ({res.status_code}): {res.text}")
else:
    print("Telegram Token oder Chat ID fehlen. Nachricht wurde nur in die Konsole gedruckt.")
