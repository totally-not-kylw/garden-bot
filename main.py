import discord
from discord.ext import commands, tasks
import os
import threading
import json
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
# The exact endpoint you discovered in DevTools!
API_URL = "https://api.growagarden2wiki.net/api/v1/games/grow-a-garden-2/stock"

SETTINGS_FILE = "bot_settings.json"

VALID_SEEDS = ["carrot", "strawberry", "blueberry", "tulip", "tomato", "apple", "bamboo", "grape", "corn", "cactus", "pineapple", "mushroom", "green bean", "banana", "coconut", "mango", "dragon fruit", "acorn", "cherry", "sunflower", "venus fly trap", "pomegranate", "poison apple", "moon blossom", "dragon's breath"]
VALID_GEAR = ["common watering can", "common sprinkler", "uncommon sprinkler", "trowel", "rare sprinkler", "jump mushroom", "speed mushroom", "shrink mushroom", "supersize mushroom", "gnome", "flashbang", "basic pot", "legendary sprinkler", "invisibility mushroom", "teleporter", "super watering can", "super sprinkler"]
VALID_CRATES = ["ladder crate", "bench crate", "light crate", "sign crate", "arch crate", "roleplay crate", "bridge crate", "spring crate", "seesaw crate", "conveyor crate", "owner door crate", "bear trap crate", "fence crate", "teleporter pad crate"]
VALID_WEATHER = ["rain", "blizzard", "lightning", "midas", "rainbow moon", "blood moon", "rainbow"]

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {"channels": {"weather": None, "seeds": None, "gear": None, "crates": None}, "roles": {}, "last_stock": None}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

bot_settings = load_settings()

# --- PORT SCANNER FIX (For Render/Railway cloud hosting) ---
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
    print(f"✅ Success! GAG2 Wiki-API Tracker Connected: Logged in as {bot.user.name}")
    # This turns on the automated background checking loop
    check_wiki_stock.start()

# --- THE WIKI API ENGINE ---
# --- THE WIKI API ENGINE ---
@tasks.loop(seconds=15)
async def check_wiki_stock():
    global bot_settings
    await bot.wait_until_ready()
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept': 'application/json'
        }
        response = requests.get(API_URL, headers=headers)
        if response.status_code != 200:
            return
            
        api_data = response.json()
        
        # Prevent spam: Only send a message if the web data actually changed
        if bot_settings.get("last_stock") == api_data:
            return
            
        channels = bot_settings.get("channels", {"weather": None, "seeds": None, "gear": None, "crates": None})
        saved_roles = bot_settings.get("roles", {})
        
        # Grab the inner stock data dictionary
        stock = api_data.get("stock", {})

        # ⛅ WEATHER DETECTION
        weather_data = stock.get("weather", {})
        weather_type = weather_data.get("type", "").lower()
        
        if weather_type in VALID_WEATHER:
            w_id = channels.get("weather")
            if w_id and (w_channel := bot.get_channel(w_id)):
                w_ping = f"<@&{saved_roles[weather_type]}>" if weather_type in saved_roles else ""
                await w_channel.send(content=w_ping, embed=discord.Embed(
                    title="⛅ Weather Shift Detected!", 
                    description=f"The environment has changed to: **{weather_type.capitalize()}**", 
                    color=discord.Color.blue()
                ))

        # 🌱 SEEDS DETECTION (UPDATED FOR QUANTITY)
        seed_pings, seed_list_str = [], []
        for seed_obj in stock.get("seeds", []):
            seed_name = seed_obj.get("name", "")
            seed_qty = seed_obj.get("quantity", 1)  # Grabs the amount
            seed_lower = seed_name.lower()
            if seed_lower in VALID_SEEDS:
                seed_list_str.append(f"• {seed_name} **(x{seed_qty})**")
                if seed_lower in saved_roles:
                    seed_pings.append(f"<@&{saved_roles[seed_lower]}>")
                    
        if seed_list_str and (s_id := channels.get("seeds")):
            if s_channel := bot.get_channel(s_id):
                await s_channel.send(content=" ".join(set(seed_pings)) if seed_pings else "", embed=discord.Embed(
                    title="🌱 Seed Shop Rotation", 
                    description="\n".join(seed_list_str), 
                    color=discord.Color.green()
                ))

        # 🛠️ GEAR DETECTION (UPDATED FOR QUANTITY)
        gear_pings, gear_list_str = [], []
        for gear_obj in stock.get("gear", []):
            gear_name = gear_obj.get("name", "")
            gear_qty = gear_obj.get("quantity", 1)  # Grabs the amount
            gear_lower = gear_name.lower()
            if gear_lower in VALID_GEAR:
                gear_list_str.append(f"• {gear_name} **(x{gear_qty})**")
                if gear_lower in saved_roles:
                    gear_pings.append(f"<@&{saved_roles[gear_lower]}>")
                    
        if gear_list_str and (g_id := channels.get("gear")):
            if g_channel := bot.get_channel(g_id):
                await g_channel.send(content=" ".join(set(gear_pings)) if gear_pings else "", embed=discord.Embed(
                    title="🛠️ Gear Shop Rotation", 
                    description="\n".join(gear_list_str), 
                    color=discord.Color.orange()
                ))

        # 📦 CRATES DETECTION (UPDATED FOR QUANTITY)
        crate_pings, crate_list_str = [], []
        for crate_obj in stock.get("crates", []):
            crate_name = crate_obj.get("name", "")
            crate_qty = crate_obj.get("quantity", 1)  # Grabs the amount
            crate_lower = crate_name.lower()
            if crate_lower in VALID_CRATES:
                crate_list_str.append(f"• {crate_name} **(x{crate_qty})**")
                if crate_lower in saved_roles:
                    crate_pings.append(f"<@&{crate_lower]}>")

        if crate_list_str and (c_id := channels.get("crates")):
            if c_channel := bot.get_channel(c_id):
                await c_channel.send(content=" ".join(set(crate_pings)) if crate_pings else "", embed=discord.Embed(
                    title="📦 Crate Drops Available", 
                    description="\n".join(crate_list_str), 
                    color=discord.Color.gold()
                ))

        # Update cache file state
        bot_settings["last_stock"] = api_data
        save_settings(bot_settings)

    except Exception as e:
        print(f"Error reading live wiki api: {e}")

# --- SETUP COMMANDS ---
@bot.command()
@commands.has_permissions(manage_channels=True)
async def setchannel(ctx, category: str, channel: discord.TextChannel):
    category = category.lower()
    if category in ["weather", "seeds", "gear", "crates"]:
        if "channels" not in bot_settings:
            bot_settings["channels"] = {"weather": None, "seeds": None, "gear": None, "crates": None}
        bot_settings["channels"][category] = channel.id
        save_settings(bot_settings)
        await ctx.send(f"✅ **{category.capitalize()}** alerts will now be posted in {channel.mention}!")
    else:
        await ctx.send("❌ Invalid category! Use `weather`, `seeds`, `gear`, or `crates`.")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def setrole(ctx, *, input_str: str):
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

@bot.command()
@commands.has_permissions(manage_channels=True)
async def test(ctx):
    await ctx.send("🔄 Sending test alerts...")
    channels = bot_settings.get("channels", {})
    for cat, name, item, col in [("weather", "⛅ Weather Shift Detected! (TEST)", "Blood Moon", discord.Color.blue()),
                                 ("seeds", "🌱 Seed Shop Rotation (TEST)", "• Bamboo\n• Apple", discord.Color.green()),
                                 ("gear", "🛠️ Gear Shop Rotation (TEST)", "• Trowel", discord.Color.orange()),
                                 ("crates", "📦 Crate Drops Available (TEST)", "• Ladder Crate", discord.Color.gold())]:
        if channels.get(cat):
            ch = bot.get_channel(channels[cat])
            if ch:
                await ch.send(embed=discord.Embed(title=name, description=f"The environment has changed to: **{item}**" if cat == "weather" else item, color=col))
    await ctx.send("🎯 Test completed!")

bot.run(TOKEN)
