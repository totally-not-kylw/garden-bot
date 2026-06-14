import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
import os
import threading
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
# Target the main website URL instead of the backend API
WIKI_HOME_URL = "https://growagarden2wiki.net/"

LAST_SEEN_SEEDS = []
LAST_SEEN_WEATHER = None
SETTINGS_FILE = "bot_settings.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

VALID_SEEDS = ["bamboo", "corn", "cactus", "pineapple", "mushroom", "green bean", "banana", "grape", "coconut", "mango", "dragon fruit", "acorn", "cherry", "sunflower", "venus fly trap", "pomegranate", "poison apple", "moon blossom", "dragon's breath"]
VALID_GEAR = ["common watering can", "common sprinkler", "uncommon sprinkler", "trowel", "rare sprinkler", "jump mushroom", "speed mushroom", "shrink mushroom", "supersize mushroom", "gnome", "flashbang", "basic pot", "legendary sprinkler", "invisibility mushroom", "teleporter", "super watering can", "super sprinkler"]
VALID_CRATES = ["ladder crate", "bench crate", "light crate", "sign crate", "arch crate", "roleplay crate", "bridge crate", "spring crate", "seesaw crate", "conveyor crate", "owner door crate", "bear trap crate", "fence crate", "teleporter pad crate"]
VALID_WEATHER = ["rain", "blizzard", "lightning", "midas", "rainbow moon", "blood moon"]

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {"channels": {"weather": None, "seeds": None, "gear": None, "crates": None}, "roles": {}}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

bot_settings = load_settings()

class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"GAG2 Multi-Tracker Active: Logged in as {bot.user.name}")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def checkapi(ctx):
    """Checks if the bot can read the raw HTML page structure."""
    await ctx.send("🔍 Attempting to read the main website HTML layout...")
    try:
        response = requests.get(WIKI_HOME_URL, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            await ctx.send(f"❌ Landing page returned status code: {response.status_code}")
            return
            
        soup = BeautifulSoup(response.text, 'html.parser')
        # Grab the page title or first few characters to verify readability
        page_title = soup.title.string if soup.title else "No Title Found"
        snippet = response.text[:400].replace("`", "'")
        
        await ctx.send(f"✅ Successfully read page structure!\n**Page Title:** `{page_title}`\n**HTML Snippet:**\n```html\n{snippet}\n```")
    except Exception as e:
        await ctx.send(f"❌ Failed to reach landing page: {e}")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def test(ctx):
    await ctx.send("🎯 Test command ready. Run `!checkapi` to verify the HTML layout access.")

bot.run(TOKEN)
