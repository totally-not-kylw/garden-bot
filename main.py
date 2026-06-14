import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import threading
import json
import requests
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
API_URL = "https://api.growagarden2wiki.net/api/v1/games/grow-a-garden-2/stock"

DISPLAY_ONLY_SEEDS = ["carrot", "strawberry", "blueberry", "tulip", "tomato", "apple"]
VALID_SEEDS = ["bamboo", "grape", "corn", "cactus", "pineapple", "mushroom", "green bean", "banana", "coconut", "mango", "dragon fruit", "acorn", "cherry", "sunflower", "venus fly trap", "pomegranate", "poison apple", "moon bloom", "dragon's breath"]
VALID_GEAR = ["common watering can", "common sprinkler", "uncommon sprinkler", "trowel", "rare sprinkler", "jump mushroom", "speed mushroom", "shrink mushroom", "supersize mushroom", "gnome", "flashbang", "basic pot", "legendary sprinkler", "invisibility mushroom", "teleporter", "super watering can", "super sprinkler"]
VALID_CRATES = ["ladder crate", "bench crate", "light crate", "sign crate", "arch crate", "roleplay crate", "bridge crate", "spring crate", "seesaw crate", "conveyor crate", "owner door crate", "bear trap crate", "fence crate", "teleporter pad crate"]
VALID_WEATHER = ["rain", "lightning", "snowfall", "rainbow", "starfall", "blood moon", "midas"]

ALL_TRACKED_SEEDS = VALID_SEEDS + DISPLAY_ONLY_SEEDS

# --- EMOJI MAPPING ---
ITEM_EMOJIS = {
    "carrot": "🥕", "strawberry": "🍓", "blueberry": "🫐", "tulip": "🌷", "tomato": "🍅",
    "apple": "🍎", "bamboo": "🎋", "grape": "🍇", "corn": "🌽", "cactus": "🌵",
    "pineapple": "🍍", "mushroom": "🍄", "green bean": "🫛", "banana": "🍌", 
    "coconut": "🥥", "mango": "🥭", "dragon fruit": "🐉", "acorn": "🌰", 
    "cherry": "🍒", "sunflower": "🌻", "venus fly trap": "🪴", "pomegranate": "🍎", 
    "poison apple": "🍏", "moon bloom": "🌸", "dragon's breath": "🐲",
    "common watering can": "💧", "common sprinkler": "💧", "uncommon sprinkler": "⚙️", 
    "trowel": "🥄", "rare sprinkler": "⚡", "jump mushroom": "🍄", "speed mushroom": "🍄", 
    "shrink mushroom": "🍄", "supersize mushroom": "🍄", "gnome": "🎅", "flashbang": "💥", 
    "basic pot": "🏺", "legendary sprinkler": "👑", "invisibility mushroom": "🍄", 
    "teleporter": "🌀", "super watering can": "🪣", "super sprinkler": "🌀",
    "ladder crate": "🪜", "bench crate": "📦", "light crate": "💡", "sign crate": "🪧", 
    "arch crate": "📦", "roleplay crate": "🎭", "bridge crate": "🌉", "spring crate": "📦", 
    "seesaw crate": "📦", "conveyor crate": "📦", "owner door crate": "🚪", 
    "bear trap crate": "🪤", "fence crate": "🚧", "teleporter pad crate": "🌀",
    "rain": "🌧️", "lightning": "🌩️", "snowfall": "❄️", "rainbow": "🌈", 
    "starfall": "⭐", "blood moon": "🔴", "midas": "🪙"
}

bot_settings = {"channels": {"weather": None, "seeds": None, "gear": None, "crates": None}, "roles": {}, "last_stock_items": None, "last_weather": None}
pending_backup = False 
ready_to_track = False  # Safety latch to protect data overwrites on startup

# --- PORT SERVER (Keep-Alive Endpoint) ---
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

# --- CENTRALIZED MEMORY ENGINE ---
async def load_settings_from_discord():
    global bot_settings, ready_to_track
    print("🔄 Syncing global configuration maps from channel topics...")
    await bot.wait_until_ready()
    
    # Give Discord connection a moment to fully cache channel properties
    await asyncio.sleep(5) 
    
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.topic and "GAG2_DATA:" in channel.topic:
                try:
                    raw_json = channel.topic.split("GAG2_DATA:")[1].strip()
                    saved_data = json.loads(raw_json)
                    
                    if "channels" in saved_data:
                        for k, v in saved_data["channels"].items():
                            if v: bot_settings["channels"][k] = v
                    if "roles" in saved_data:
                        for k, v in saved_data["roles"].items():
                            if v: bot_settings["roles"][k.lower().strip()] = v
                            
                    print(f"✅ Full recovery successful! Loaded memory data from #{channel.name}")
                    ready_to_track = True
                    return
                except Exception as e:
                    print(f"⚠️ Error reading backup on #{channel.name}: {e}")
    
    print("⚠️ No backup data found. Starting with a clean configuration profile.")
    ready_to_track = True

@tasks.loop(minutes=1)
async def dynamic_cloud_backup_loop():
    global bot_settings, pending_backup, ready_to_track
    if not pending_backup or not ready_to_track:
        return

    primary_channel_id = bot_settings["channels"].get("seeds") or bot_settings["channels"].get("weather")
    if not primary_channel_id:
        return

    channel = bot.get_channel(primary_channel_id)
    if channel:
        clean_topic = ""
        if channel.topic and "GAG2_DATA:" in channel.topic:
            clean_topic = channel.topic.split("GAG2_DATA:")[0].strip()
        elif channel.topic:
            clean_topic = channel.topic.strip()

        backup_package = {
            "channels": bot_settings["channels"],
            "roles": bot_settings["roles"]
        }
        serialized = json.dumps(backup_package)
        new_topic = f"{clean_topic} | GAG2_DATA:{serialized}".strip(" | ")
        
        try:
            await channel.edit(topic=new_topic)
            print("💾 Global database configuration safely secured to cloud channel topic.")
            pending_backup = False
        except discord.Forbidden:
            print("❌ Cannot sync backup: Missing permissions to edit channel topic.")
        except discord.HTTPException as e:
            if e.status == 429:
                print("⚠️ Sync postponed: Hitting Discord rate limits.")

@bot.event
async def on_ready():
    print(f"✅ GAG2 Wiki-API Tracker Connected: Logged in as {bot.user.name}")
    await load_settings_from_discord()
    
    try:
        synced = await bot.tree.sync()
        print(f"⚡ Global slash command tree synced! ({len(synced)} commands ready)")
    except Exception as e:
        print(f"⚠️ Application command sync failure: {e}")
        
    check_wiki_stock.start()
    dynamic_cloud_backup_loop.start()

# --- THE WIKI API ENGINE ---
@tasks.loop(seconds=10)
async def check_wiki_stock():
    global bot_settings, ready_to_track
    # Absolute safety stop: Do not scan or output stock until the cloud data has finished loading
    if not ready_to_track:
        return
        
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
        response = requests.get(API_URL, headers=headers)
        if response.status_code != 200:
            return
            
        api_data = response.json()
        stock = api_data.get("stock", {})
        
        channels = bot_settings.get("channels", {"weather": None, "seeds": None, "gear": None, "crates": None})
        saved_roles = bot_settings.get("roles", {})

        # ⛅ WEATHER DETECTION
        weather_data = stock.get("weather", {})
        weather_type = weather_data.get("type", "").lower().strip()
        
        if weather_type in VALID_WEATHER:
            if bot_settings.get("last_weather") != weather_type:
                bot_settings["last_weather"] = weather_type
                
                w_id = channels.get("weather")
                if w_id and (w_channel := bot.get_channel(w_id)):
                    w_ping = f"<@&{saved_roles[weather_type]}>" if weather_type in saved_roles else ""
                    w_emoji = ITEM_EMOJIS.get(weather_type, "⛅")
                    await w_channel.send(content=w_ping, embed=discord.Embed(
                        title="⛅ Weather Alert!", 
                        description=f"The environment has changed to: **{weather_type.capitalize()}** {w_emoji}", 
                        color=discord.Color.blue()
                    ))

        current_items_only = json.dumps({k: stock.get(k) for k in ["seeds", "gear", "crates"]}, sort_keys=True)
        if bot_settings.get("last_stock_items") != current_items_only:
            bot_settings["last_stock_items"] = current_items_only

            # 🌱 SEEDS DETECTION
            seed_pings, seed_list_str = [], []
            for seed_obj in stock.get("seeds", []):
                seed_name = seed_obj.get("name", "")
                seed_qty = seed_obj.get("quantity", 1)
                seed_lower = seed_name.lower().strip()
                if seed_lower in ALL_TRACKED_SEEDS:
                    emoji = ITEM_EMOJIS.get(seed_lower, "🌱")
                    seed_list_str.append(f"• {seed_name} {emoji} **(x{seed_qty})**")
                    if seed_lower in saved_roles:
                        seed_pings.append(f"<@&{saved_roles[seed_lower]}>")
                        
            if seed_list_str and (s_id := channels.get("seeds")):
                if s_channel := bot.get_channel(s_id):
                    await s_channel.send(content=" ".join(set(seed_pings)) if seed_pings else "", embed=discord.Embed(
                        title="🌱 Seed Stock!", description="\n".join(seed_list_str), color=discord.Color.green()
                    ))

            # 🛠️ GEAR DETECTION
            gear_pings, gear_list_str = [], []
            for gear_obj in stock.get("gear", []):
                gear_name = gear_obj.get("name", "")
                gear_qty = gear_obj.get("quantity", 1)
                gear_lower = gear_name.lower().strip()
                if gear_lower in VALID_GEAR:
                    emoji = ITEM_EMOJIS.get(gear_lower, "🛠️")
                    gear_list_str.append(f"• {gear_name} {emoji} **(x{gear_qty})**")
                    if gear_lower in saved_roles:
                        gear_pings.append(f"<@&{saved_roles[gear_lower]}>")
                        
            if gear_list_str and (g_id := channels.get("gear")):
                if g_channel := bot.get_channel(g_id):
                    await g_channel.send(content=" ".join(set(gear_pings)) if gear_pings else "", embed=discord.Embed(
                        title="🛠️ Gear Stock!", description="\n".join(gear_list_str), color=discord.Color.orange()
                    ))

            # 📦 CRATES DETECTION
            crate_pings, crate_list_str = [], []
            for crate_obj in stock.get("crates", []):
                crate_name = crate_obj.get("name", "")
                crate_qty = crate_obj.get("quantity", 1)
                crate_lower = crate_name.lower().strip()
                if crate_lower in VALID_CRATES:
                    emoji = ITEM_EMOJIS.get(crate_lower, "📦")
                    crate_list_str.append(f"• {crate_name} {emoji} **(x{crate_qty})**")
                    if crate_lower in saved_roles:
                        crate_pings.append(f"<@&{saved_roles[crate_lower]}>")

            if crate_list_str and (c_id := channels.get("crates")):
                if c_channel := bot.get_channel(c_id):
                    await c_channel.send(content=" ".join(set(crate_pings)) if crate_pings else "", embed=discord.Embed(
                        title="📦 Crate Shop!", description="\n".join(crate_list_str), color=discord.Color.gold()
                    ))
    except Exception as e:
        print(f"Error reading live wiki api: {e}")

# --- BACKEND REUSABLE CONTROLLERS ---
async def execute_setchannel(category: str, channel: discord.TextChannel):
    global pending_backup
    category = category.lower().strip()
    if category in ["weather", "seeds", "gear", "crates"]:
        bot_settings["channels"][category] = channel.id
        pending_backup = True
        return f"✅ **{category.capitalize()}** alerts mapped to {channel.mention}! Data will sync momentarily."
    return "❌ Invalid category! Use `weather`, `seeds`, `gear`, or `crates`."

async def execute_setrole(item_name: str, role: discord.Role):
    global pending_backup
    item_lower = item_name.strip().lower()
    if item_lower in DISPLAY_ONLY_SEEDS:
        return f"❌ Role assignment disabled for `{item_name}`. This item is configured for display only."
    if item_lower not in (VALID_SEEDS + VALID_GEAR + VALID_CRATES + VALID_WEATHER):
        return f"❌ `{item_name}` is not recognized in tracking lists."
    bot_settings["roles"][item_lower] = role.id
    pending_backup = True
    return f"✅ Pings for **{item_name}** bound to {role.mention}!"

async def execute_test(guild):
    channels = bot_settings.get("channels", {})
    for cat, name, item, col in [("weather", "⛅ Weather Alert! (TEST)", "Blood Moon 🔴", discord.Color.blue()),
                                 ("seeds", "🌱 Seed Stock! (TEST)", "• Bamboo 🎋 **(x2)**", discord.Color.green()),
                                 ("gear", "🛠️ Gear Stock! (TEST)", "• Trowel 🥄 **(x1)**", discord.Color.orange()),
                                 ("crates", "📦 Crate Shop! (TEST)", "• Ladder Crate 🪜 **(x3)**", discord.Color.gold())]:
        if channels.get(cat):
            ch = guild.get_channel(channels[cat])
            if ch:
                await ch.send(embed=discord.Embed(title=name, description=f"The environment has changed to: **{item}**" if cat == "weather" else item, color=col))

def execute_unassigned():
    saved_roles = bot_settings.get("roles", {})
    unassigned_seeds = [s for s in VALID_SEEDS if s not in saved_roles]
    unassigned_gear = [g for g in VALID_GEAR if g not in saved_roles]
    unassigned_crates = [c for c in VALID_CRATES if c not in saved_roles]
    unassigned_weather = [w for w in VALID_WEATHER if w not in saved_roles]
    
    if (len(unassigned_seeds) + len(unassigned_gear) + len(unassigned_crates) + len(unassigned_weather)) == 0:
        return discord.Embed(title="🎯 All Items Assigned!", description="Every tracking element has an associated ping role configured.", color=discord.Color.green())

    embed = discord.Embed(title="⚠️ Unassigned Tracker Elements", description="Remaining items missing role mappings:", color=discord.Color.red())
    if unassigned_seeds: embed.add_field(name="🌱 Seeds", value="\n".join([f"• {s.title()} {ITEM_EMOJIS.get(s, '')}" for s in unassigned_seeds]), inline=False)
    if unassigned_gear: embed.add_field(name="🛠️ Gear", value="\n".join([f"• {g.title()} {ITEM_EMOJIS.get(g, '')}" for g in unassigned_gear]), inline=False)
    if unassigned_crates: embed.add_field(name="📦 Crates", value="\n".join([f"• {c.title()} {ITEM_EMOJIS.get(c, '')}" for c in unassigned_crates]), inline=False)
    if unassigned_weather: embed.add_field(name="⛅ Weather", value="\n".join([f"• {w.title()} {ITEM_EMOJIS.get(w, '')}" for w in unassigned_weather]), inline=False)
    return embed

# --- DISCORD SLASH & PREFIX COMMANDS ---
@bot.tree.command(name="setchannel")
async def slash_setchannel(interaction: discord.Interaction, category: str, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_channels: return
    await interaction.response.send_message(await execute_setchannel(category, channel))

@bot.tree.command(name="setrole")
async def slash_setrole(interaction: discord.Interaction, item_name: str, role: discord.Role):
    if not interaction.user.guild_permissions.manage_roles: return
    await interaction.response.send_message(await execute_setrole(item_name, role))

@bot.tree.command(name="test")
async def slash_test(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels: return
    await interaction.response.send_message("🔄 Processing mock diagnostic alerts...")
    await execute_test(interaction.guild)

@bot.tree.command(name="unassigned")
async def slash_unassigned(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles: return
    await interaction.response.send_message(embed=execute_unassigned())

@bot.command()
@commands.has_permissions(manage_channels=True)
async def setchannel(ctx, category: str, channel: discord.TextChannel):
    await ctx.send(await execute_setchannel(category, channel))

@bot.command()
@commands.has_permissions(manage_roles=True)
async def setrole(ctx, *, input_str: str):
    try:
        parts = input_str.rsplit(" ", 1)
        role = await commands.RoleConverter().convert(ctx, parts[1].strip())
        await ctx.send(await execute_setrole(parts[0], role))
    except Exception:
        await ctx.send("❌ Error updating role: Verification failed.")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def test(ctx):
    await execute_test(ctx.guild)

@bot.command()
@commands.has_permissions(manage_roles=True)
async def unassigned(ctx):
    await ctx.send(embed=execute_unassigned())

bot.run(TOKEN)
