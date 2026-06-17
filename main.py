import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import threading
import json
import requests
import asyncio
import re
import time  # Imported for live timestamp generation
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
API_URL = os.getenv("API_KEY")

DISPLAY_ONLY_SEEDS = ["carrot", "strawberry", "blueberry", "tulip", "tomato"]
VALID_SEEDS = ["apple", "bamboo", "grape", "corn", "cactus", "pineapple", "mushroom", "green bean", "banana", "coconut", "mango", "dragon fruit", "acorn", "cherry", "sunflower", "venus fly trap", "pomegranate", "poison apple", "moon bloom", "dragon's breath"]
VALID_GEAR = ["common watering can", "common sprinkler", "uncommon sprinkler", "trowel", "rare sprinkler", "jump mushroom", "speed mushroom", "shrink mushroom", "supersize mushroom", "gnome", "flashbang", "basic pot", "legendary sprinkler", "invisibility mushroom", "teleporter", "super watering can", "super sprinkler"]
VALID_CRATES = ["ladder crate", "bench crate", "light crate", "sign crate", "arch crate", "roleplay crate", "bridge crate", "spring crate", "seesaw crate", "conveyor crate", "owner door crate", "bear trap crate", "fence crate", "teleporter pad crate"]
VALID_WEATHER = ["rain", "lightning", "snowfall", "rainbow", "starfall", "blood moon", "midas"]

ALL_TRACKED_SEEDS = VALID_SEEDS + DISPLAY_ONLY_SEEDS
ALL_ASSIGNABLE_ITEMS = VALID_SEEDS + VALID_GEAR + VALID_CRATES + VALID_WEATHER

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
ready_to_track = False  

pending_autorole_drafts = {}

# --- PORT SERVER ---
class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

# --- DISCORD BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- ACCURATE STRING SIMILARITY ENGINE ---
def clean_string(s: str) -> str:
    s = s.lower()
    s = re.sub(r'[^\w\s\']', '', s) 
    s = re.sub(r'\b(ping|role|alert|feed|tracker|bot|pings|roles|weather|status)\b', '', s) 
    return " ".join(s.split())

def calculate_match_score(item: str, role_name: str) -> float:
    cleaned_item = clean_string(item)
    cleaned_role = clean_string(role_name)
    
    if not cleaned_item or not cleaned_role:
        return 0.0
        
    if cleaned_item == cleaned_role:
        return 1.0
    if re.search(r'\b' + re.escape(cleaned_item) + r'\b', cleaned_role):
        return 0.90
        
    item_tokens = set(cleaned_item.split())
    role_tokens = set(cleaned_role.split())
    
    intersection = item_tokens.intersection(role_tokens)
    if not intersection:
        return 0.0
        
    return len(intersection) / max(len(item_tokens), len(role_tokens))

# --- MASTER ANTI-WIPE STORAGE ENGINE ---
async def load_settings_from_discord():
    global bot_settings, ready_to_track
    print("🔄 Initializing Master Database Recovery Engine...")
    await bot.wait_until_ready()
    await asyncio.sleep(6)  
    
    found_backup = False
    temp_channels = {}
    temp_roles = {}

    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.topic and "GAG2_DATA:" in channel.topic:
                try:
                    raw_json = channel.topic.split("GAG2_DATA:")[1].strip()
                    saved_data = json.loads(raw_json)
                    
                    if "channels" in saved_data:
                        for k, v in saved_data["channels"].items():
                            if v: temp_channels[k] = v
                    if "roles" in saved_data:
                        for k, v in saved_data["roles"].items():
                            if v: temp_roles[k.lower().strip()] = v
                    
                    found_backup = True
                    print(f"📖 Located save registry cluster on channel: #{channel.name}")
                except Exception as e:
                    print(f"⚠️ Error processing text stream on channel #{channel.name}: {e}")

    if found_backup:
        bot_settings["channels"].update(temp_channels)
        bot_settings["roles"].update(temp_roles)
        print(f"✅ Recovery complete. Restored {len(bot_settings['roles'])} data points.")
    else:
        print("⚠️ Recovery loop finished. No serialized configuration records found.")

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
        weather_type = str(weather_data.get("type", "")).lower().strip()
        
        if weather_type in VALID_WEATHER:
            if bot_settings.get("last_weather") != weather_type:
                bot_settings["last_weather"] = weather_type
                
                w_id = channels.get("weather")
                if w_id and (w_channel := bot.get_channel(w_id)):
                    w_ping = f"<@&{saved_roles[weather_type]}>" if weather_type in saved_roles else ""
                    w_emoji = ITEM_EMOJIS.get(weather_type, "⛅")
                    await w_channel.send(content=w_ping, embed=discord.Embed(
                        title="⛅ Weather Alert!", 
                        description=f"The environment has changed to: **{weather_type.title()}** {w_emoji}", 
                        color=discord.Color.blue()
                    ))

        current_items_only = json.dumps({k: stock.get(k) for k in ["seeds", "gear", "crates"]}, sort_keys=True)
        if bot_settings.get("last_stock_items") != current_items_only:
            bot_settings["last_stock_items"] = current_items_only
            
            # Generate the Unix Timestamp for right now
            nearest_5_min_timestamp = int(time.time() // 300) * 300
            timestamp_string = f"Stock At: <t:{nearest_5_min_timestamp}:t> (<t:{nearest_5_min_timestamp}:R>)\n\n"

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
                        title="🌱 Seed Stock!", 
                        description=timestamp_string + "\n".join(seed_list_str), 
                        color=discord.Color.green()
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
                        title="🛠️ Gear Stock!", 
                        description=timestamp_string + "\n".join(gear_list_str), 
                        color=discord.Color.orange()
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
                        title="📦 Crate Shop!", 
                        description=timestamp_string + "\n".join(crate_list_str), 
                        color=discord.Color.gold()
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
    global pending_backup, ready_to_track
    if not ready_to_track:
        return "❌ Storage engine is busy starting up. Please wait 5 seconds."
    item_lower = item_name.strip().lower()
    if item_lower in DISPLAY_ONLY_SEEDS:
        return f"❌ Role assignment disabled for `{item_name}`. This item is configured for display only."
    if item_lower not in ALL_ASSIGNABLE_ITEMS:
        return f"❌ `{item_name}` is not recognized in tracking lists."
    bot_settings["roles"][item_lower] = role.id
    pending_backup = True
    return f"✅ Pings for **{item_name}** bound to {role.mention}!"

def execute_unassigned():
    saved_roles = bot_settings.get("roles", {})
    unassigned_seeds = [s for s in VALID_SEEDS if s not in saved_roles]
    unassigned_gear = [g for g in VALID_GEAR if g not in saved_roles]
    unassigned_crates = [c for c in VALID_CRATES if c not in saved_roles]
    unassigned_weather = [w for w in VALID_WEATHER if w not in saved_roles]
    
    if (len(unassigned_seeds) + len(unassigned_gear) + len(unassigned_crates) + len(unassigned_weather)) == 0:
        return [discord.Embed(title="🎯 All Items Assigned!", description="Every tracking element has an associated ping role configured.", color=discord.Color.green())]

    embed = discord.Embed(title="⚠️ Unassigned Tracker Elements", description="Remaining items missing role mappings:", color=discord.Color.red())
    if unassigned_seeds: embed.add_field(name="🌱 Seeds", value="\n".join([f"• {s.title()} {ITEM_EMOJIS.get(s, '')}" for s in unassigned_seeds]), inline=False)
    if unassigned_gear: embed.add_field(name="🛠️ Gear", value="\n".join([f"• {g.title()} {ITEM_EMOJIS.get(g, '')}" for g in unassigned_gear]), inline=False)
    if unassigned_crates: embed.add_field(name="📦 Crates", value="\n".join([f"• {c.title()} {ITEM_EMOJIS.get(c, '')}" for c in unassigned_crates]), inline=False)
    if unassigned_weather: embed.add_field(name="⛅ Weather", value="\n".join([f"• {w.title()} {ITEM_EMOJIS.get(w, '')}" for w in unassigned_weather]), inline=False)
    return [embed]

# --- 🤖 HIGHLY ACCURATE AUTO-ROLE MATCHING CONTROLLERS ---
def generate_draft_embeds(draft_matches):
    """Combines categories into two larger embeds to safely prevent PC embed limits and mobile height cutoffs."""
    embeds_list = []
    
    # --- EMBED 1: SEEDS & GEAR ---
    lines_embed1 = []
    
    # Seeds Subsection
    lines_embed1.append("### 🌱 Seeds")
    has_seeds = False
    for item in VALID_SEEDS:
        if item in draft_matches:
            role_id = draft_matches[item]
            emoji = ITEM_EMOJIS.get(item, "🔹")
            lines_embed1.append(f"• **{item.title()}** {emoji} ➡️ <@&{role_id}>")
            has_seeds = True
    if not has_seeds:
        lines_embed1.append("*No seeds drafted.*")
        
    lines_embed1.append("\n" + "─" * 15 + "\n")
    
    # Gear Subsection
    lines_embed1.append("### 🛠️ Gear")
    has_gear = False
    for item in VALID_GEAR:
        if item in draft_matches:
            role_id = draft_matches[item]
            emoji = ITEM_EMOJIS.get(item, "🔹")
            lines_embed1.append(f"• **{item.title()}** {emoji} ➡️ <@&{role_id}>")
            has_gear = True
    if not has_gear:
        lines_embed1.append("*No gear drafted.*")

    embed1 = discord.Embed(description="\n".join(lines_embed1), color=discord.Color.green())
    embed1.set_author(name="🤖 Auto-Role Matcher Proposals", icon_url="https://i.imgur.com/vH3C1tC.png")
    embeds_list.append(embed1)

    # --- EMBED 2: CRATES & WEATHER ---
    lines_embed2 = []
    
    # Crates Subsection
    lines_embed2.append("### 📦 Crates")
    has_crates = False
    for item in VALID_CRATES:
        if item in draft_matches:
            role_id = draft_matches[item]
            emoji = ITEM_EMOJIS.get(item, "🔹")
            lines_embed2.append(f"• **{item.title()}** {emoji} ➡️ <@&{role_id}>")
            has_crates = True
    if not has_crates:
        lines_embed2.append("*No crates drafted.*")
        
    lines_embed2.append("\n" + "─" * 15 + "\n")
    
    # Weather Subsection
    lines_embed2.append("### ⛅ Weather")
    has_weather = False
    for item in VALID_WEATHER:
        if item in draft_matches:
            role_id = draft_matches[item]
            emoji = ITEM_EMOJIS.get(item, "🔹")
            lines_embed2.append(f"• **{item.title()}** {emoji} ➡️ <@&{role_id}>")
            has_weather = True
    if not has_weather:
        lines_embed2.append("*No weather drafted.*")

    embed2 = discord.Embed(description="\n".join(lines_embed2), color=discord.Color.gold())
    embed2.add_field(
        name="💡 Instructions", 
        value="* Need to change something? `!editdraft [Item Name] [@Role]`\n* Ready? Type `!approve` to save, or `!deny` to wipe.", 
        inline=False
    )
    embeds_list.append(embed2)
    
    return embeds_list

def execute_autoroles_discovery(guild: discord.Guild):
    global pending_autorole_drafts
    draft_matches = {}
    
    for item in ALL_ASSIGNABLE_ITEMS:
        best_role = None
        highest_score = 0.0
        
        for role in guild.roles:
            if role.is_default():
                continue
            score = calculate_match_score(item, role.name)
            if score > highest_score and score >= 0.40: 
                highest_score = score
                best_role = role
                
        if best_role:
            draft_matches[item] = best_role.id

    if not draft_matches:
        fallback_embed = discord.Embed(
            title="🔍 Auto-Role Finder Results",
            description="I scanned all roles using enhanced string similarity but couldn't find any robust matches on my lists.",
            color=discord.Color.orange()
        )
        return [fallback_embed], False

    pending_autorole_drafts[guild.id] = {"matches": draft_matches, "last_msg_id": None}
    return generate_draft_embeds(draft_matches), True

async def execute_edit_draft_flow(ctx_or_interaction, guild_id: int, item_name: str, role: discord.Role):
    global pending_autorole_drafts
    draft_data = pending_autorole_drafts.get(guild_id)
    if not draft_data:
        msg = "❌ There is no active auto-role draft to edit right now. Run `!autoroles` first!"
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg)
        else:
            await ctx_or_interaction.send(msg)
        return
        
    item_lower = item_name.strip().lower()
    if item_lower in DISPLAY_ONLY_SEEDS:
        msg = f"❌ Role assignment disabled for `{item_name}`. This item is display-only."
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg)
        else:
            await ctx_or_interaction.send(msg)
        return
    if item_lower not in ALL_ASSIGNABLE_ITEMS:
        msg = f"❌ `{item_name}` is not a recognized game tracking item."
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(msg)
        else:
            await ctx_or_interaction.send(msg)
        return
        
    draft_data["matches"][item_lower] = role.id
    new_embeds = generate_draft_embeds(draft_data["matches"])
    
    if draft_data["last_msg_id"]:
        try:
            channel = ctx_or_interaction.channel
            old_msg = await channel.fetch_message(draft_data["last_msg_id"])
            await old_msg.delete()
        except Exception:
            pass

    success_text = f"✏️ **Draft updated!** Set **{item_lower.title()}** to {role.mention}."
    
    if isinstance(ctx_or_interaction, discord.Interaction):
        await ctx_or_interaction.response.send_message(content=success_text)
        new_msg = await ctx_or_interaction.channel.send(embeds=new_embeds)
        draft_data["last_msg_id"] = new_msg.id
    else:
        await ctx_or_interaction.send(content=success_text)
        new_msg = await ctx_or_interaction.send(embeds=new_embeds)
        draft_data["last_msg_id"] = new_msg.id

def execute_approve_draft(guild_id: int):
    global bot_settings, pending_backup, pending_autorole_drafts
    draft_data = pending_autorole_drafts.get(guild_id)
    if not draft_data or not draft_data["matches"]:
        return "❌ There is no active auto-role draft pending approval. Run `!autoroles` first!"
        
    bot_settings["roles"].update(draft_data["matches"])
    del pending_autorole_drafts[guild_id]
    pending_backup = True
    return f"✅ **Success!** Automatically saved {len(draft_data['matches'])} tracking roles into the cloud database infrastructure!"

def execute_deny_draft(guild_id: int):
    global pending_autorole_drafts
    if guild_id in pending_autorole_drafts:
        del pending_autorole_drafts[guild_id]
        return "🗑️ Proposed auto-role configuration draft rejected and cleared successfully."
    return "❌ No active draft structure found to clear."


# --- DISCORD SLASH COMMAND INTERFACES ---
@bot.tree.command(name="setchannel")
async def slash_setchannel(interaction: discord.Interaction, category: str, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_channels: return
    await interaction.response.send_message(await execute_setchannel(category, channel))

@bot.tree.command(name="setrole")
async def slash_setrole(interaction: discord.Interaction, item_name: str, role: discord.Role):
    if not interaction.user.guild_permissions.manage_roles: return
    await interaction.response.send_message(await execute_setrole(item_name, role))

@bot.tree.command(name="unassigned")
async def slash_unassigned(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles: return
    embeds = execute_unassigned()
    await interaction.response.send_message(embeds=embeds)

@bot.tree.command(name="autoroles")
async def slash_autoroles(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles: return
    embeds, has_matches = execute_autoroles_discovery(interaction.guild)
    await interaction.response.send_message(embeds=embeds)
    if has_matches:
        msg = await interaction.original_response()
        pending_autorole_drafts[interaction.guild_id]["last_msg_id"] = msg.id

@bot.tree.command(name="editdraft")
@app_commands.describe(item_name="The item name to override", role="The new role to couple with it")
async def slash_editdraft(interaction: discord.Interaction, item_name: str, role: discord.Role):
    if not interaction.user.guild_permissions.manage_roles: return
    await execute_edit_draft_flow(interaction, interaction.guild_id, item_name, role)

@bot.tree.command(name="approve")
async def slash_approve(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles: return
    await interaction.response.send_message(execute_approve_draft(interaction.guild_id))

@bot.tree.command(name="deny")
async def slash_deny(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles: return
    await interaction.response.send_message(execute_deny_draft(interaction.guild_id))


# --- DISCORD PREFIX COMMAND INTERFACES ---
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
@commands.has_permissions(manage_roles=True)
async def unassigned(ctx):
    embeds = execute_unassigned()
    await ctx.send(embeds=embeds)

@bot.command(name="autoroles")
@commands.has_permissions(manage_roles=True)
async def cmd_autoroles(ctx):
    embeds, has_matches = execute_autoroles_discovery(ctx.guild)
    msg = await ctx.send(embeds=embeds)
    if has_matches:
        pending_autorole_drafts[ctx.guild.id]["last_msg_id"] = msg.id

@bot.command(name="editdraft")
@commands.has_permissions(manage_roles=True)
async def cmd_editdraft(ctx, *, input_str: str):
    try:
        parts = input_str.rsplit(" ", 1)
        if len(parts) < 2:
            await ctx.send("❌ Format error! Use: `!editdraft [Item Name] [@Role]`")
            return
        role = await commands.RoleConverter().convert(ctx, parts[1].strip())
        await execute_edit_draft_flow(ctx, ctx.guild.id, parts[0], role)
    except Exception as e:
        await ctx.send("❌ Error modifying draft element: Verification failed.")

@bot.command(name="approve")
@commands.has_permissions(manage_roles=True)
async def cmd_approve(ctx):
    await ctx.send(execute_approve_draft(ctx.guild.id))

@bot.command(name="deny")
@commands.has_permissions(manage_roles=True)
async def cmd_deny(ctx):
    await ctx.send(execute_deny_draft(ctx.guild.id))

@bot.command()
@commands.has_permissions(manage_channels=True)
async def test(ctx):
    channels = bot_settings.get("channels", {})
    for cat, name, item, col in [("weather", "⛅ Weather Alert! (TEST)", "Blood Moon 🔴", discord.Color.blue()),
                                 ("seeds", "🌱 Seed Stock! (TEST)", "• Bamboo 🎋 **(x2)**", discord.Color.green()),
                                 ("gear", "🛠️ Gear Stock! (TEST)", "• Trowel 🥄 **(x1)**", discord.Color.orange()),
                                 ("crates", "📦 Crate Shop! (TEST)", "• Ladder Crate 🪜 **(x3)**", discord.Color.gold())]:
        if channels.get(cat):
            ch = ctx.guild.get_channel(channels[cat])
            if ch: await ch.send(embed=discord.Embed(title=name, description=f"The environment has changed to: **{item}**" if cat == "weather" else item, color=col))

bot.run(TOKEN)
