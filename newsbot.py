import discord
import time
import aiohttp
import psycopg2
from newsbot_config import token, ss_key, password, categories
from discord.ext import tasks, commands
from io import BytesIO


class MyBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix='?', description="Delivers personalized newsfeeds.", intents=intents)
        self.categories = categories
        self.channel_name = "NEWSBOT"

    # EVENTS
    async def on_ready(self):
        print(f'Logged on as {self.user}')
        print(f'Running discord.py version {discord.__version__}')

    # BACKGROUND TASK
    async def setup_hook(self) -> None:
        self.my_background_task.start()

    @tasks.loop(seconds=86400)
    async def my_background_task(self):
        # scaleserp API vars
        connector = aiohttp.TCPConnector(ssl=False)
        params = {
            'api_key': ss_key,
            'search_type': 'news',
            'hl': 'en'
        }

        # message storage
        articles_dict = {}
        for category in self.categories:
            articles_dict[category] = ""

        # start session
        async with aiohttp.ClientSession(connector=connector) as session:
            # loop through categories
            for category in self.categories:
                params['q'] = category
                # get articles for each category
                async with session.get('https://api.scaleserp.com/search', params=params) as resp:
                    results = await resp.json()
                    # add results to dictionary
                    for result in results['news_results']:
                        articles_dict[category] += f"{result['title']} | {result['link']}\n\n"

        # connect to the database
        conn = psycopg2.connect("dbname = 'news' user = 'postgres' host= 'localhost' password = '{}'".format(password))
        cur = conn.cursor()

        for server in self.guilds:
            # select the relevant keywords for each server
            cur.execute("""SELECT keyword FROM serverkw WHERE sid = '{}';""".format(server.id))
            server_keywords = cur.fetchall()

            # server is not subscribed to any keywords
            if server_keywords is None:
                break

            # auxiliary
            news = ""
            exists = False

            # add relevant articles to server news
            for category in server_keywords:
                news += articles_dict[category[0]]

            # add news to text file
            buffer = BytesIO(news.encode('utf-8'))
            file = discord.File(buffer, filename='news.txt')

            # check if a dedicated bot channel exists
            for channel in server.text_channels:
                # if it exists, send the news there
                if channel.name.upper() == self.channel_name:
                    await channel.send(file=file)
                    exists = True
                    break

            # if it doesn't exist, create it and send the news there
            if not exists:
                try:
                    channel = await server.create_text_channel(name="newsybot")
                    await channel.send(file=file)
                except discord.Forbidden:
                    print("Insufficient permissions.")

    @my_background_task.before_loop
    async def before_my_task(self):
        await self.wait_until_ready()


# create bot instance
bot = MyBot()


async def bot_ok(ctx):
    await ctx.message.add_reaction("\N{WHITE HEAVY CHECK MARK}")


# COMMANDS
@bot.command(name="echo")
async def echo(ctx, *, content):
    await ctx.send(content)


@bot.command(name="ping")
async def ping(ctx):
    start = time.monotonic()
    message = await ctx.send("Pinging...")
    end = time.monotonic()

    interval_s = 1000 * (end - start)
    total = round(interval_s, 2)

    await message.edit(content=f"Pong! `{total}ms`")


@bot.command(name="addcategory", aliases=["addcat"])
async def add_cat(ctx, *, cat):
    cat = cat.upper()

    # if the category is invalid, return
    if cat not in bot.categories:
        await ctx.send(f"Invalid category. Valid categories: `{', '.join(bot.categories)}`.")
        return

    # connect to the database
    conn = psycopg2.connect("dbname = 'news' user = 'postgres' host= 'localhost' password = '{}'".format(password))
    cur = conn.cursor()
    query = "INSERT INTO serverkw(sid, keyword) VALUES(%s, %s);"

    # insert category into database
    try:
        cur.execute(query, (str(ctx.guild.id), cat))
        await bot_ok(ctx)
    # unless it's already there
    except psycopg2.IntegrityError:
        conn.rollback()
        await ctx.send(f"You are already subscribed to this category.")
        return
    else:
        # save the changes
        conn.commit()


@bot.command(name="removecategory", aliases=["removecat"])
async def remove_cat(ctx, *, cat):
    cat = cat.upper()

    # connect to the database
    conn = psycopg2.connect("dbname = 'news' user = 'postgres' host= 'localhost' password = '{}'".format(password))
    cur = conn.cursor()
    query = "DELETE FROM serverkw WHERE sid=%s AND keyword=%s;"

    # remove category from database
    cur.execute(query, (str(ctx.guild.id), cat))
    count = cur.rowcount
    conn.commit()

    # if deletion occurred
    if count == 1:
        await bot_ok(ctx)
    else:
        await ctx.send("You were not subscribed to this category.")


bot.run(token)
