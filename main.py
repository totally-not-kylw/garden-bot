import discord
from discord import app_commands
from discord.ext import tasks
import os
import threading
import json
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
API_URL = "https://api.growagarden2wiki.net/api/v1/games/grow-a-garden-2/stock"

SETTINGS_FILE = "bot_settings.json"

VALID_SEEDS = ["carrot", "strawberry", "blueberry", "tulip", "tomato", "apple", "bamboo", "grape", "corn", "cactus", "pineapple", "mushroom", "green bean", "banana", "coconut", "mango", "dragon fruit", "acorn", "cherry", "sunflower", "venus fly trap", "pomegranate", "poison apple", "moon blossom", "dragon's breath"]
VALID_GEAR = ["common watering can", "common sprinkler", "uncommon sprinkler", "trowel", "rare sprinkler", "jump mushroom", "speed mushroom", "shrink mushroom", "supersize mushroom", "gnome", "flashbang", "basic pot", "legendary sprinkler", "invisibility mushroom", "teleporter", "super watering can", "super sprinkler"]
VALID_CRATES = ["ladder crate", "bench crate", "light crate", "sign crate", "arch crate", "roleplay crate", "bridge crate", "spring crate", "seesaw crate", "conveyor crate", "owner door crate", "bear trap crate", "fence crate", "teleporter pad crate"]
VALID_WEATHER = ["rain", "blizzard", "lightning", "midas", "rainbow moon", "blood moon", "rainbow"]

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"channels": {"weather": None, "seeds": None, "gear": None, "crates": None}, "roles": {}, "last_stock_items": None, "last_weather": None}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

bot_settings = load_settings()

# --- PORT SCANNER FIX (For Cloud Hosting) ---
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
class MasterBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        check_wiki_stock.start()

bot = MasterBot()

@bot.event
async def on_ready():
    print(f"✅ Success! GAG2 Tracker Connected as {bot.user.name}")
    try:
        # Syncs the slash commands globally across all servers your bot is in
        await bot.tree.sync()
        print("⚡ Slash commands synced globally!")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# --- THE WIKI API ENGINE ---
@tasks.loop(seconds=10)
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
        stock = api_data.get("stock", {})
        
        channels = bot_settings.get("channels", {"weather": None, "seeds": None, "gear": None, "crates": None})
        saved_roles = bot_settings.get("roles", {})
        has_updates = False

        # ⛅ WEATHER DETECTION (FIXED TO PREVENT GHOST SPAM)
        weather_data = stock.get("weather", {})
        weather_type = weather_data.get("type", "").lower()
        
        if weather_type in VALID_WEATHER:
            # Check if this weather is truly different from what we logged in settings
            if bot_settings.get("last_weather") != weather_type:
                bot_settings["last_weather"] = weather_type
                has_updates = True
                
                w_id = channels.get("weather")
                if w_id and (w_channel := bot.get_channel(w_id)):
                    w_ping = f"<@&{saved_roles[weather_type]}>" if weather_type in saved_roles else ""
                    await w_channel.send(content=w_ping, embed=discord.Embed(
                        title="⛅ Weather Shift Detected!", 
                        description=f"The environment has changed to: **{weather_type.capitalize()}**", 
                        color=discord.Color.blue()
                    ))

        # Smart Item Cache: Isolate item data strings
        current_items_only = json.dumps({k: stock.get(k) for k in ["seeds", "gear", "crates"]}, sort_keys=True)
        
        if bot_settings.get("last_stock_items") != current_items_only:
            bot_settings["last_stock_items"] = current_items_only
            has_updates = True

            # 🌱 SEEDS DETECTION
            seed_pings, seed_list_str = [], []
            for seed_obj in stock.get("seeds", []):
                seed_name = seed_obj.get("name", "")
                seed_qty = seed_obj.get("quantity", 1)
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

            # 🛠️ GEAR DETECTION
            gear_pings, gear_list_str = [], []
            for gear_obj in stock.get("gear", []):
                gear_name = gear_obj.get("name", "")
                gear_qty = gear_obj.get("quantity", 1)
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

            # 📦 CRATES DETECTION
            crate_pings, crate_list_str = [], []
            for crate_obj in stock.get("crates", []):
                crate_name = crate_obj.get("name", "")
                crate_qty = crate_obj.get("quantity", 1)
                crate_lower = crate_name.lower()
                if crate_lower in VALID_CRATES:
                    crate_list_str.append(f"• {crate_name} **(x{crate_qty})**")
                    if crate_lower in saved_roles:
                        crate_pings.append(f"<@&{saved_roles[crate_lower]}>")

            if crate_list_str and (c_id := channels.get("crates")):
                if c_channel := bot.get_channel(c_id):
                    await c_channel.send(content=" ".join(set(crate_pings)) if crate_pings else "", embed=discord.Embed(
                        title="📦 Crate Drops Available", 
                        description="\n".join(crate_list_str), 
                        color=discord.Color.gold()
                    ))

        if has_updates:
            save_settings(bot_settings)

    except Exception as e:
        print(f"Error reading live wiki api: {e}")

# --- SLASH COMMANDS SETUP ---
@bot.tree.command(name="setchannel", description="Set up where alerts are posted for a category.")
@app_commands.describe(category="Choose: weather, seeds, gear, crates", channel="Target channel")
async def setchannel(interaction: discord.Interaction, category: str, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ You lack permission to configure channels.", ephemeral=True)
        return
        
    category = category.lower().strip()
    if category in ["weather", "seeds", "gear", "crates"]:
        if "channels" not in bot_settings:
            bot_settings["channels"] = {"weather": None, "seeds": None, "gear": None, "crates": None}
        bot_settings["channels"][category] = channel.id
        save_settings(bot_settings)
        await interaction.response.send_message(f"✅ **{category.capitalize()}** alerts configured to {channel.mention}!")
    else:
        await interaction.response.send_message("❌ Invalid category. Choose `weather`, `seeds`, `gear`, or `crates`.", ephemeral=True)

@bot.tree.command(name="setrole", description="Assign a role ping to an in-game item or weather type.")
@app_commands.describe(item_name="Exact name of item/weather (e.g., Cactus, Blood Moon)", role="Role to notify")
async def setrole(interaction: discord.Interaction, item_name: str, role: discord.Role):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ You lack permission to configure roles.", ephemeral=True)
        return
        
    normalized_name = item_name.strip().lower()
    if normalized_name not in (VALID_SEEDS + VALID_GEAR + VALID_CRATES + VALID_WEATHER):
        await interaction.response.send_message(f"❌ `{item_name}` is not found in tracking indexes.", ephemeral=True)
        return
        
    bot_settings["roles"][normalized_name] = role.id
    save_settings(bot_settings)
    await interaction.response.send_message(f"✅ Pings for **{item_name}** mapped directly to {role.mention}!")

@bot.tree.command(name="test", description="Broadcast mock embeds across saved targets to verify setup.")
async def test(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Administrator clearance required.", ephemeral=True)
        return
        
    await interaction.response.send_message("🔄 Dispensing sample alerts...")
    channels = bot_settings.get("channels", {})
    for cat, name, item, col in [("weather", "⛅ Weather Shift Detected! (TEST)", "Blood Moon", discord.Color.blue()),
                                 ("seeds", "🌱 Seed Shop Rotation (TEST)", "• Bamboo **(x2)**\n• Apple **(x4)**", discord.Color.green()),
                                 ("gear", "🛠️ Gear Shop Rotation (TEST)", "• Trowel **(x1)**", discord.Color.orange()),
                                 ("crates", "📦 Crate Drops Available (TEST)", "• Ladder Crate **(x3)**", discord.Color.gold())]:
        if channels.get(cat):
            ch = bot.get_channel(channels[cat])
            if ch:
                await ch.send(embed=discord.Embed(title=name, description=f"The environment has changed to: **{item}**" if cat == "weather" else item, color=col))

bot.run(TOKEN)
