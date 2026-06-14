import discord
from discord.ext import commands, tasks
import requests
import os
import threading
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
# Using an open proxy to slip past Cloudflare's data center block
REAL_URL = "https://api.growagarden2wiki.net/api/v1/games/grow-a-garden-2/stock"
WIKI_API_URL = f"https://api.allorigins.win/get?url={requests.utils.quote(REAL_URL)}"

LAST_SEEN_SEEDS = []
LAST_SEEN_WEATHER = None
SETTINGS_FILE = "bot_settings.json"

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

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {
        "channels": {"weather": None, "seeds": None, "gear": None, "crates": None},
        "roles": {}
    }

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

bot_settings = load_settings()

# --- PORT SCANNER FIX ---
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

# --- SETUP COMMANDS ---
@bot.command()
@commands.has_permissions(manage_channels=True)
async def setchannel(ctx, category: str, channel: discord.TextChannel):
    """Sets a specific channel for a category."""
    category = category.lower()
    if category in ["weather", "seeds", "gear", "crates"]:
        if "channels" not in bot_settings:
            bot_settings["channels"] = {"weather": None, "seeds": None, "gear": None, "crates": None}
        bot_settings["channels"][category] = channel.id
        save_settings(bot_settings)
        await ctx.send(f"✅ **{category.capitalize()}** alerts will now be posted in {channel.mention}!")
    else:
        await ctx.send("❌ Invalid category! Use `weather`, `seeds`, or `gear`, or `crates`.")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def setrole(ctx, *, input_str: str):
    """Assigns a role to a specific item."""
    try:
        parts = input_str.rsplit(" ", 1)
        if len(parts) < 2:
            await ctx.send("❌ Format error! Use: `!setrole [Item Name] [@Role]`")
            return
        item_name = parts[0].strip().lower()
        role_mention = parts[1].strip()
        role = await commands.RoleConverter().convert(ctx, role_mention)
        
        if item_name not in (VALID_SEEDS + VALID_GEAR + VALID_CRATES + VALID_WEATHER):
            await ctx.send(f"❌ `{parts[0]}` is not recognized in tracking lists.")
            return
        bot_settings["roles"][item_name] = role.id
        save_settings(bot_settings)
        await ctx.send(f"✅ Pings for **{parts[0]}** will now ping {role.mention}!")
    except Exception:
        await ctx.send(f"❌ Error updating role: Verification failed.")

# --- DEBUG API COMMAND ---
@bot.command()
@commands.has_permissions(manage_channels=True)
async def checkapi(ctx):
    """Fetches data through an open proxy wrapper."""
    await ctx.send("🔍 Requesting live data via AllOrigins proxy wrapper...")
    try:
        response = requests.get(WIKI_API_URL, timeout=15)
        if response.status_code != 200:
            await ctx.send(f"❌ Proxy returned an error status code: {response.status_code}")
            return
            
        wrapper_data = response.json()
        # The proxy nests the real website response inside a field called "contents"
        raw_contents = wrapper_data.get("contents", "{}")
        
        if len(raw_contents) > 1900:
            raw_contents = raw_contents[:1900] + "\n...[Truncated]"
            
        await ctx.send(f"📡 **Proxy-Delivered API Response:**\n```json\n{raw_contents}\n```")
    except Exception as e:
        await ctx.send(f"❌ Proxy wrapper failed to fetch data: {e}")

# --- TEST COMMAND ---
@bot.command()
@commands.has_permissions(manage_channels=True)
async def test(ctx):
    """Forces a test alert."""
    await ctx.send("🔄 Sending test alerts...")
    channels = bot_settings.get("channels", {})
    saved_roles = bot_settings.get("roles", {})

    for cat, name, item, col in [("weather", "⛅ Weather Shift Detected! (TEST)", "Blood Moon", discord.Color.blue()),
                                 ("seeds", "🌱 Seed Shop Rotation (TEST)", "• Bamboo\n• Apple", discord.Color.green()),
                                 ("gear", "🛠️ Gear Shop Rotation (TEST)", "• Trowel", discord.Color.orange()),
                                 ("crates", "📦 Crate Drops Available (TEST)", "• Ladder Crate", discord.Color.gold())]:
        if channels.get(cat):
            ch = bot.get_channel(channels[cat])
            if ch:
                await ch.send(embed=discord.Embed(title=name, description=f"The environment has changed to: **{item}**" if cat == "weather" else item, color=col))
    await ctx.send("🎯 Test completed!")

# --- BACKGROUND TRACKER ---
@tasks.loop(seconds=30)
async def check_wiki_stock():
    global LAST_SEEN_SEEDS, LAST_SEEN_WEATHER
    channels = bot_settings.get("channels", {"weather": None, "seeds": None, "gear": None, "crates": None})
    saved_roles = bot_settings.get("roles", {})

    try:
        response = requests.get(WIKI_API_URL, timeout=15)
        if response.status_code != 200:
            return
            
        wrapper_data = response.json()
        # Unpack the proxy content string back into actual JSON dictionary data
        data = json.loads(wrapper_data.get("contents", "{}"))
        
        current_seeds = data.get("seeds", [])
        current_shop_gear = data.get("gear", data.get("gears", []))
        current_weather = data.get("weather", "Clear")

        if current_weather != LAST_SEEN_WEATHER:
            LAST_SEEN_WEATHER = current_weather
            w_id = channels.get("weather")
            if w_id and (w_channel := bot.get_channel(w_id)):
                w_lower = current_weather.lower()
                w_ping = f"<@&{saved_roles[w_lower]}>" if (w_lower in VALID_WEATHER and w_lower in saved_roles) else ""
                await w_channel.send(content=w_ping, embed=discord.Embed(title="⛅ Weather Shift Detected!", description=f"The environment has changed to: **{current_weather}**", color=discord.Color.blue()))

        if current_seeds != LAST_SEEN_SEEDS and current_seeds:
            LAST_SEEN_SEEDS = current_seeds

            if s_id := channels.get("seeds"):
                if s_channel := bot.get_channel(s_id):
                    seed_pings, seed_list_str = [], []
                    for seed in current_seeds:
                        seed_list_str.append(f"• {seed}")
                        if seed.lower() in VALID_SEEDS and seed.lower() in saved_roles:
                            seed_pings.append(f"<@&{saved_roles[seed.lower()]}>")
                    await s_channel.send(content=" ".join(set(seed_pings)) if seed_pings else "", embed=discord.Embed(title="🌱 Seed Shop Rotation", description="\n".join(seed_list_str), color=discord.Color.green()))

            gear_pings, crate_pings, gear_list_str, crate_list_str = [], [], [], []
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

            if (g_id := channels.get("gear")) and gear_list_str:
                if g_channel := bot.get_channel(g_id):
                    await g_channel.send(content=" ".join(set(gear_pings)) if gear_pings else "", embed=discord.Embed(title="🛠️ Gear Shop Rotation", description="\n".join(gear_list_str), color=discord.Color.orange()))

            if (c_id := channels.get("crates")) and crate_list_str:
                if c_channel := bot.get_channel(c_id):
                    await c_channel.send(content=" ".join(set(crate_pings)) if crate_pings else "", embed=discord.Embed(title="📦 Crate Drops Available", description="\n".join(crate_list_str), color=discord.Color.gold()))

    except Exception as e:
        print(f"Error executing stock update: {e}")

@check_wiki_stock.before_loop
async def before_check():
    await bot.wait_until_ready()

bot.run(TOKEN)
