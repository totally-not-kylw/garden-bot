import discord
from discord.ext import commands, tasks
import requests
import os
import threading
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
WIKI_API_URL = "https://growagarden2wiki.net/api/stock"

LAST_SEEN_SEEDS = []
SETTINGS_FILE = "bot_settings.json"

# Load saved settings (Roles & Channel ID)
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {
        "channel_id": None,
        "weather_role": None,
        "seeds_role": None,
        "gear_role": None
    }

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

bot_settings = load_settings()

# --- THE FIX: FAKE SERVER TO TRICK RENDER'S PORT SCANNER ---
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

# --- DISCORD BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"GAG2 Tracker Active: Logged in as {bot.user.name}")
    check_wiki_stock.start()

# --- IN-SERVER COMMAND TO SET CHANNEL ---
@bot.command()
@commands.has_permissions(manage_channels=True)
async def setchannel(ctx, channel: discord.TextChannel):
    """Sets the channel where stock alerts are posted. Usage: !setchannel #channel-name"""
    bot_settings["channel_id"] = channel.id
    save_settings(bot_settings)
    await ctx.send(f"✅ Stock alerts will now be posted in {channel.mention}!")

# --- IN-SERVER COMMAND TO SET ROLES ---
@bot.command()
@commands.has_permissions(manage_roles=True)
async def setrole(ctx, category: str, role: discord.Role):
    """Assigns a role to a category. Usage: !setrole seeds @RoleName"""
    category = category.lower()
    if category in ["weather", "seeds", "gear"]:
        bot_settings[f"{category}_role"] = role.id
        save_settings(bot_settings)
        await ctx.send(f"✅ Successfully linked {role.mention} to **{category.capitalize()}** alerts!")
    else:
        await ctx.send("❌ Invalid category! Use `weather`, `seeds`, or `gear`.")

# --- BACKGROUND TRACKER (SEPARATED MESSAGES) ---
@tasks.loop(seconds=30)
async def check_wiki_stock():
    global LAST_SEEN_SEEDS
    
    # Don't run if the target channel hasn't been set up yet
    if not bot_settings["channel_id"]:
        return
        
    channel = bot.get_channel(bot_settings["channel_id"])
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
        
        # Stop if data hasn't changed
        if current_seeds == LAST_SEEN_SEEDS or not current_seeds:
            return
            
        LAST_SEEN_SEEDS = current_seeds

        # Get role mentions if configured
        w_ping = f"<@&{bot_settings['weather_role']}>" if bot_settings['weather_role'] else ""
        s_ping = f"<@&{bot_settings['seeds_role']}>" if bot_settings['seeds_role'] else ""
        g_ping = f"<@&{bot_settings['gear_role']}>" if bot_settings['gear_role'] else ""

        # 1. Weather Message
        embed_weather = discord.Embed(title="⛅ Weather Update", description=f"The current weather is now: **{current_weather}**", color=discord.Color.blue())
        await channel.send(content=w_ping, embed=embed_weather)

        # 2. Seeds Message
        embed_seeds = discord.Embed(title="🌱 Seed Shop Stock", description="\n".join([f"• {seed}" for seed in current_seeds]), color=discord.Color.green())
        await channel.send(content=s_ping, embed=embed_seeds)

        # 3. Gear Message
        if current_gear:
            embed_gear = discord.Embed(title="🛠️ Gear Shop Stock", description="\n".join([f"• {item}" for item in current_gear]), color=discord.Color.orange())
            await channel.send(content=g_ping, embed=embed_gear)

    except Exception as e:
        print(f"Error reading wiki stock data: {e}")

@check_wiki_stock.before_loop
async def before_check():
    await bot.wait_until_ready()

bot.run(TOKEN)
