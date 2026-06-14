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
LAST_SEEN_WEATHER = None
SETTINGS_FILE = "bot_settings.json"

# Allowed tracking items based on your lists
VALID_SEEDS = [
    "bamboo", "corn", "cactus", "pineapple", "mushroom", "green bean", "banana", 
    "grape", "coconut", "mango", "dragon fruit", "acorn", "cherry", "sunflower", 
    "venus fly trap", "pomegranate", "poison apple", "moon blossom", "dragon's breath"
]

VALID_GEAR = [
    "common watering can", "common sprinkler", "uncommon sprinkler", "trowel", 
    "rare sprinkler", "jump mushroom", "speed mushroom", "shrink mushroom", 
    "supersize mushroom", "gnome", "flashbang", "basic pot", "legendary sprinkler", 
    "invisibility mushroom", "teleporter", "super watering can", "super sprinkler"
]

VALID_CRATES = [
    "ladder crate", "bench crate", "light crate", "sign crate", "arch crate", 
    "roleplay crate", "bridge crate", "spring crate", "seesaw crate", "conveyor crate", 
    "owner door crate", "bear trap crate", "fence crate", "teleporter pad crate"
]

VALID_WEATHER = ["rain", "blizzard", "lightning", "midas", "rainbow moon", "blood moon"]

# Load saved configurations
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {
        "channels": {
            "weather": None,
            "seeds": None,
            "gear": None,
            "crates": None
        },
        "roles": {}  # Stores item_name: role_id mapping
    }

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

bot_settings = load_settings()

# --- FAKE SERVER TO TRICK RENDER'S PORT SCANNER ---
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
    print(f"GAG2 Multi-Tracker Active: Logged in as {bot.user.name}")
    check_wiki_stock.start()

# --- IN-SERVER COMMAND TO SET INDIVIDUAL CHANNELS ---
@bot.command()
@commands.has_permissions(manage_channels=True)
async def setchannel(ctx, category: str, channel: discord.TextChannel):
    """Sets a specific channel for a category. Usage: !setchannel seeds #seed-alerts"""
    category = category.lower()
    if category in ["weather", "seeds", "gear", "crates"]:
        # Ensure the channels dictionary exists in settings
        if "channels" not in bot_settings:
            bot_settings["channels"] = {"weather": None, "seeds": None, "gear": None, "crates": None}
            
        bot_settings["channels"][category] = channel.id
        save_settings(bot_settings)
        await ctx.send(f"✅ **{category.capitalize()}** alerts will now be posted in {channel.mention}!")
    else:
        await ctx.send("❌ Invalid category! Use `weather`, `seeds`, `gear`, or `crates`.\nExample: `!setchannel seeds #seed-tracker`")

# --- IN-SERVER COMMAND TO SET SPECIFIC ITEM ROLES ---
@bot.command()
@commands.has_permissions(manage_roles=True)
async def setrole(ctx, *, input_str: str):
    """Assigns a role to a specific item. Usage: !setrole Bamboo @RoleName"""
    try:
        parts = input_str.rsplit(" ", 1)
        if len(parts) < 2:
            await ctx.send("❌ Format error! Use: `!setrole [Item Name] [@Role]`")
            return
            
        item_name = parts[0].strip().lower()
        role_mention = parts[1].strip()
        
        role = await commands.RoleConverter().convert(ctx, role_mention)
        
        all_valid_items = VALID_SEEDS + VALID_GEAR + VALID_CRATES + VALID_WEATHER
        if item_name not in all_valid_items:
            await ctx.send(f"❌ `{parts[0]}` is not recognized in your specific item tracking lists.")
            return
            
        bot_settings["roles"][item_name] = role.id
        save_settings(bot_settings)
        await ctx.send(f"✅ Pings for **{parts[0]}** will now ping {role.mention}!")
        
    except Exception as e:
        await ctx.send(f"❌ Error updating role: Verification failed or role doesn't exist.")

# --- BACKGROUND TRACKER ---
@tasks.loop(seconds=30)
async def check_wiki_stock():
    global LAST_SEEN_SEEDS, LAST_SEEN_WEATHER
    
    channels = bot_settings.get("channels", {"weather": None, "seeds": None, "gear": None, "crates": None})
    saved_roles = bot_settings.get("roles", {})

    try:
        response = requests.get(WIKI_API_URL, timeout=10)
        if response.status_code != 200:
            return
            
        data = response.json()
        current_seeds = data.get("seeds", [])
        current_shop_gear = data.get("gear", data.get("gears", []))
        current_weather = data.get("weather", "Clear")

        # 1. WEATHER TRACKING
        if current_weather != LAST_SEEN_WEATHER:
            LAST_SEEN_WEATHER = current_weather
            
            w_channel_id = channels.get("weather")
            if w_channel_id:
                w_channel = bot.get_channel(w_channel_id)
                if w_channel:
                    weather_lower = current_weather.lower()
                    w_ping = f"<@&{saved_roles[weather_lower]}>" if (weather_lower in VALID_WEATHER and weather_lower in saved_roles) else ""
                    
                    embed_w = discord.Embed(
                        title="⛅ Weather Shift Detected!", 
                        description=f"The environment has changed to: **{current_weather}**", 
                        color=discord.Color.blue()
                    )
                    await w_channel.send(content=w_ping, embed=embed_w)

        # 2. SEED & GEAR ROTATION TRACKING
        if current_seeds != LAST_SEEN_SEEDS and current_seeds:
            LAST_SEEN_SEEDS = current_seeds

            # SEEDS CHANNEL
            s_channel_id = channels.get("seeds")
            if s_channel_id:
                s_channel = bot.get_channel(s_channel_id)
                if s_channel:
                    seed_pings = []
                    seed_list_str = []
                    for seed in current_seeds:
                        seed_lower = seed.lower()
                        seed_list_str.append(f"• {seed}")
                        if seed_lower in VALID_SEEDS and seed_lower in saved_roles:
                            seed_pings.append(f"<@&{saved_roles[seed_lower]}>")
                    
                    embed_s = discord.Embed(title="🌱 Seed Shop Rotation", description="\n".join(seed_list_str), color=discord.Color.green())
                    s_ping_content = " ".join(set(seed_pings)) if seed_pings else ""
                    await s_channel.send(content=s_ping_content, embed=embed_s)

            # Separate Gear vs Crates arrays
            gear_pings = []
            crate_pings = []
            gear_list_str = []
            crate_list_str = []

            for item in current_shop_gear:
                item_lower = item.lower()
                if item_lower in VALID_CRATES:
                    crate_list_str.append(f"• {item}")
                    if item_lower in saved_roles:
                        crate_pings.append(f"<@&{saved_roles[item_lower]}>")
                else:
                    gear_list_str.append(f"• {item}")
                    if item_lower in VALID_GEAR and item_lower in saved_roles:
                        gear_pings.append(f"<@&{saved_roles[item_lower]}>")

            # GEAR CHANNEL
            g_channel_id = channels.get("gear")
            if g_channel_id and gear_list_str:
                g_channel = bot.get_channel(g_channel_id)
                if g_channel:
                    embed_g = discord.Embed(title="🛠️ Gear Shop Rotation", description="\n".join(gear_list_str), color=discord.Color.orange())
                    g_ping_content = " ".join(set(gear_pings)) if gear_pings else ""
                    await g_channel.send(content=g_ping_content, embed=embed_g)

            # CRATES CHANNEL
            c_channel_id = channels.get("crates")
            if c_channel_id and crate_list_str:
                c_channel = bot.get_channel(c_channel_id)
                if c_channel:
                    embed_c = discord.Embed(title="📦 Crate Drops Available", description="\n".join(crate_list_str), color=discord.Color.gold())
                    c_ping_content = " ".join(set(crate_pings)) if crate_pings else ""
                    await c_channel.send(content=c_ping_content, embed=embed_c)

    except Exception as e:
        print(f"Error executing stock update: {e}")

@check_wiki_stock.before_loop
async def before_check():
    await bot.wait_until_ready()

bot.run(TOKEN)
