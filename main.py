import discord
from discord.ext import commands, tasks
import requests
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1378839178674176020
WIKI_API_URL = "https://growagarden2wiki.net/api/stock"

LAST_SEEN_SEEDS = []

# --- THE FIX: FAKE SERVER TO TRICK RENDER'S PORT SCANNER ---
class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_server():
    # Render tells our app what port to use via the PORT environment variable
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
    server.serve_forever()

# Start the web server in the background so Render is happy
threading.Thread(target=run_health_server, daemon=True).start()

# --- DISCORD BOT CODE ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"GAG2 Tracker Active: Logged in as {bot.user.name}")
    check_wiki_stock.start()

@tasks.loop(seconds=30)
async def check_wiki_stock():
    global LAST_SEEN_SEEDS
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    try:
        response = requests.get(WIKI_API_URL, timeout=10)
        if response.status_code != 200:
            return
            
        data = response.json()
        current_seeds = data.get("seeds", [])
        current_gear = data.get("gear", data.get("gears", []))
        current_weather = data.get("weather", "Clear")
        
        if current_seeds == LAST_SEEN_SEEDS or not current_seeds:
            return
            
        LAST_SEEN_SEEDS = current_seeds
        
        embed = discord.Embed(
            title="🌳 Grow a Garden 2 Stock Alert! 🌳", 
            color=discord.Color.brand_green(),
            url="https://growagarden2wiki.net/stock/"
        )
        embed.add_field(name="⛅ Current Weather", value=current_weather, inline=False)
        embed.add_field(name="🌱 New Seeds", value=", ".join(current_seeds), inline=True)
        embed.add_field(name="🛠️ New Gear", value=", ".join(current_gear), inline=True)
        embed.set_footer(text="Data fetched from growagarden2wiki.net")
        
        ping_content = ""
        rare_keywords = ["Super", "Mythic", "Divine", "Golden", "Prismatic", "Beanstalk"]
        
        if any(keyword in "".join(current_seeds) for keyword in rare_keywords):
            ping_content = "🚨 **HIGH PRIORITY DROPS IN STOCK!** @everyone"
            
        await channel.send(content=ping_content, embed=embed)

    except Exception as e:
        print(f"Error reading wiki stock data: {e}")

@check_wiki_stock.before_loop
async def before_check():
    await bot.wait_until_ready()

bot.run(TOKEN)
