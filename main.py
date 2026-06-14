import discord
from discord.ext import commands
import os
import threading
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")

# Put the ID of the public channel your bot is "watching" for stock updates here!
WATCH_CHANNEL_ID = 123456789012345678  

SETTINGS_FILE = "bot_settings.json"

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
    print(f"GAG2 Discord Mirror Active: Logged in as {bot.user.name}")

# --- THE SPY ENGINE ---
@bot.event
async def on_message(message):
    # Process regular bot commands first
    await bot.process_commands(message)
    
    # Check if the message is coming from the channel we are watching
    if message.channel.id != WATCH_CHANNEL_ID:
        return

    channels = bot_settings.get("channels", {"weather": None, "seeds": None, "gear": None, "crates": None})
    saved_roles = bot_settings.get("roles", {})
    
    # Read the text or embed details from the source bot
    content_text = message.content.lower()
    
    # If the source bot uses embeds, pull text from the embed instead
    if message.embeds:
        embed = message.embeds[0]
        content_text += f" {embed.title if embed.title else ''} {embed.description if embed.description else ''}"
        for field in embed.fields:
            content_text += f" {field.name} {field.value}"
            
    content_text = content_text.lower()

    # ⛅ WEATHER DETECTION
    for weather in VALID_WEATHER:
        if weather in content_text:
            w_id = channels.get("weather")
            if w_id and (w_channel := bot.get_channel(w_id)):
                w_ping = f"<@&{saved_roles[weather]}>" if weather in saved_roles else ""
                await w_channel.send(content=w_ping, embed=discord.Embed(title="⛅ Weather Shift Detected!", description=f"The environment has changed to: **{weather.capitalize()}**", color=discord.Color.blue()))
                break # Only process one weather event per message

    # 🌱 SEEDS DETECTION
    seed_pings, seed_list_str = [], []
    for seed in VALID_SEEDS:
        if seed in content_text:
            seed_list_str.append(f"• {seed.capitalize()}")
            if seed in saved_roles:
                seed_pings.append(f"<@&{saved_roles[seed]}>")
                
    if seed_list_str and (s_id := channels.get("seeds")):
        if s_channel := bot.get_channel(s_id):
            await s_channel.send(content=" ".join(set(seed_pings)) if seed_pings else "", embed=discord.Embed(title="🌱 Seed Shop Rotation", description="\n".join(seed_list_str), color=discord.Color.green()))

    # 🛠️ GEAR & 📦 CRATES DETECTION
    gear_pings, crate_pings, gear_list_str, crate_list_str = [], [], [], []
    
    for gear in VALID_GEAR:
        if gear in content_text:
            gear_list_str.append(f"• {gear.capitalize()}")
            if gear in saved_roles:
                gear_pings.append(f"<@&{saved_roles[gear]}>")
                
    for crate in VALID_CRATES:
        if crate in content_text:
            crate_list_str.append(f"• {crate.capitalize()}")
            if crate in saved_roles:
                crate_pings.append(f"<@&{saved_roles[crate]}>")

    if gear_list_str and (g_id := channels.get("gear")):
        if g_channel := bot.get_channel(g_id):
            await g_channel.send(content=" ".join(set(gear_pings)) if gear_pings else "", embed=discord.Embed(title="🛠️ Gear Shop Rotation", description="\n".join(gear_list_str), color=discord.Color.orange()))

    if crate_list_str and (c_id := channels.get("crates")):
        if c_channel := bot.get_channel(c_id):
            await c_channel.send(content=" ".join(set(crate_pings)) if crate_pings else "", embed=discord.Embed(title="📦 Crate Drops Available", description="\n".join(crate_list_str), color=discord.Color.gold()))

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
