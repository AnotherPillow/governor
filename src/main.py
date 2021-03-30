# Governor
# Written by aquova, 2020-2021
# https://github.com/aquova/governor

import discord
import db, commands, events, games, utils, xp
import traceback
from config import DEBUG_BOT, CMD_PREFIX, DISCORD_KEY, GAME_ANNOUNCEMENT_CHANNEL, XP_OFF, GATE_EMOJI, GATE_MES, GATE_ROLE
from debug import Debug
from slowmode import Thermometer
from tracker import Tracker

intents = discord.Intents.default()
intents.members = True

client = discord.Client(intents=intents)

db.initialize()
tr = Tracker()
cc = commands.CustomCommands()
dbg = Debug()
game_timer = games.GameTimer()
thermo = Thermometer()

# Dictionary of function pointers
# Maps commands to functions that are called by them
FUNC_DICT = {
    "addgame": games.add_game,
    "addxp": tr.add_xp,
    "bonusxp": tr.set_bonus_xp,
    "cleargames": games.clear_games,
    "custom": commands.print_help,
    "define": cc.define_cmd,
    "edit": commands.edit,
    "getgames": games.get_games,
    "help": commands.print_help,
    "info": commands.info,
    "lb": commands.show_lb,
    "level": xp.render_lvl_image,
    "list": cc.list_cmds,
    "lvl": xp.render_lvl_image,
    "nobonusxp": tr.reset_bonus_xp,
    "ranks": commands.list_ranks,
    "remove": cc.remove_cmd,
    "say": commands.say,
    "userinfo": xp.userinfo,
    "xp": xp.get_xp,
}

# The keys in the function dict cannot be used as custom commands
cc.set_protected_keywords(list(FUNC_DICT.keys()))

"""
Update User Count

Updates the bot's 'activity' to reflect the number of users
"""
async def update_user_count(guild):
    activity_mes = f"{guild.member_count} members!"
    activity_object = discord.Activity(name=activity_mes, type=discord.ActivityType.watching)
    await client.change_presence(activity=activity_object)

"""
On Ready

Runs when Discord bot is first brought online
"""
@client.event
async def on_ready():
    print("Logged in as:")
    print(client.user.name)
    print(client.user.id)

"""
On Guild Available

Runs when a guild (server) that the bot is connected to becomes ready
"""
@client.event
async def on_guild_available(guild):
    await tr.refresh_db(guild)

    # This is 100% going to cause issues if we ever want to host on more than one server
    # TODO: If we want to fix this, make announcement channels a list in config.json, and add a server ID column to DB
    game_channel = discord.utils.get(guild.text_channels, id=GAME_ANNOUNCEMENT_CHANNEL)

    if game_channel is not None:
        print(f"Announcing games in server '{guild.name}' channel '{game_channel.name}'")
    else:
        await client.close()
        raise Exception(f"Game announcement error: couldn't find channel {GAME_ANNOUNCEMENT_CHANNEL}")

    game_timer.start(game_channel)
    thermo.start(guild)

    # Set Bouncer's status
    await update_user_count(guild)

"""
On Member Join

Runs when a user joins the server
"""
@client.event
async def on_member_join(user):
    await update_user_count(user.guild)

"""
On Member Remove

Runs when a member leaves the server
"""
@client.event
async def on_member_remove(user):
    tr.remove_from_cache(user.id)
    await update_user_count(user.guild)

"""
On Raw Reaction Add

Runs when a member reacts to a message with an emoji
"""
@client.event
async def on_raw_reaction_add(payload):
    if DEBUG_BOT:
        return

    await events.award_event_prize(payload, tr, client)

    if payload.message_id == GATE_MES and payload.emoji.name == GATE_EMOJI:
        # Raw payload just returns IDs, so need to iterate through connected servers to get server object
        # Since each bouncer instance will only be in one server, it should be quick.
        # If bouncer becomes general purpose (god forbid), may need to rethink this
        try:
            server = [x for x in client.guilds if x.id == payload.guild_id][0]
            new_role = discord.utils.get(server.roles, id=GATE_ROLE)
            target_user = discord.utils.get(server.members, id=payload.user_id)
            await target_user.add_roles(new_role)
        except IndexError as e:
            print("Error: The client could not find any servers: {e}")
        except AttributeError as e:
            print("Couldn't find member to add role to: {e}")

"""
On Message

Runs when a user posts a message
"""
@client.event
async def on_message(message):
    # Ignore bots completely (including ourself)
    if message.author.bot:
        return

    # For now, completely ignore DMs
    if type(message.channel) is discord.channel.DMChannel:
        return

    # Check first if we're toggling debug mode
    # Need to do this before we discard a message
    if dbg.check_toggle(message):
        await dbg.toggle_debug(message)
        return
    elif dbg.should_ignore_message(message):
        return

    try:
        # Keep track of the user's message for dynamic slowmode
        await thermo.user_spoke(message)
        # Check if we need to congratulate a user on getting a new role
        # Don't award XP if posting in specified disabled channels
        if message.channel.id not in XP_OFF:
            lvl_up_message = await tr.give_xp(message.author)
            if lvl_up_message != None:
                await message.channel.send(lvl_up_message)

        # Check if someone is trying to use a bot command
        if message.content != "" and message.content[0] == CMD_PREFIX:
            prefix_removed = utils.strip_prefix(message.content)
            if prefix_removed == "":
                return
            command = utils.get_command(prefix_removed)

            try:
                if command in FUNC_DICT:
                    # First, check if they're using a built-in command
                    output_message = await FUNC_DICT[command](message)
                    if output_message != None:
                        await message.channel.send(output_message)
                elif cc.command_available(command):
                    # Check if they're using a user-defined command
                    cmd_output = cc.parse_response(message)
                    await message.channel.send(cmd_output)
            except discord.errors.Forbidden as e:
                if e.code == 50013:
                    print(f"I can see messages, but cannot send in #{message.channel.name}")
        else:
            # Else, check if they are posting in an event channel
            await events.event_check(message)

    except discord.errors.HTTPException as e:
        print(traceback.format_exc())
        pass

client.run(DISCORD_KEY)
