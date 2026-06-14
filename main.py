import discord
from discord.ext import commands, tasks
import requests
import os
import asyncio

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1378839178674176020  # Your exact channel ID plugged in!
WIKI_API_URL = "https://growagarden2wiki.net/api/stock" # The data endpoint for the wiki's tracker

# To avoid sending duplicate notifications for the same shop cycle
LAST_SEEN_SEEDS = []

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"GAG2 Tracker Active: Logged in as {bot.user.name}")
    # Start the background loop that checks the wiki every 30 seconds
    check_wiki_stock.start()

@tasks.loop(seconds=30)
async def check_wiki_stock():
    global LAST_SEEN_SEEDS
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    try:
        # Request data from the Wiki's stock database
        response = requests.get(WIKI_API_URL, timeout=10)
        if response.status_code != 200:
            return
            
        data = response.json()
        
        # Pull the items from the wiki data payload
        current_seeds = data.get("seeds", [])
        current_gear = data.get("gear", data.get("gears", []))
        current_weather = data.get("weather", "Clear")
        
        # If the seeds haven't changed, the shop hasn't restocked yet. Skip it.
        if current_seeds == LAST_SEEN_SEEDS or not current_seeds:
            return
            
        LAST_SEEN_SEEDS = current_seeds # Update our history tracker
        
        # Create the Discord Alert Message
        embed = discord.Embed(
            title="🌳 Grow a Garden 2 Stock Alert! 🌳", 
            color=discord.Color.brand_green(),
            url="https://growagarden2wiki.net/stock/" # Links back to your source website
        )
        embed.add_field(name="⛅ Current Weather", value=current_weather, inline=False)
        embed.add_field(name="🌱 New Seeds", value=", ".join(current_seeds), inline=True)
        embed.add_field(name="🛠️ New Gear", value=", ".join(current_gear), inline=True)
        embed.set_footer(text="Data fetched from growagarden2wiki.net")
        
        # Custom logic: Edit these keywords based on what pings you want
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
