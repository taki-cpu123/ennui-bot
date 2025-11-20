import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import asyncio
from datetime import datetime
import io

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Enable all intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# Configuration - YOUR SPECIFIC IDs
AUTO_ROLE_ID = 1440909540546576415
TICKET_CATEGORY_ID = 1440921625427181600
LOG_CHANNEL_ID = 1440923132062863422

# Store active tickets and their data
active_tickets = {}
ticket_data = {}  # Store ticket creation info for transcripts

# ===== TICKET SYSTEM =====


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create Ticket", style=discord.ButtonStyle.primary, custom_id="persistent_view:create_ticket", emoji="🎫")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.create_ticket_channel(interaction)

    async def create_ticket_channel(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user

        # Check if user already has an active ticket
        if user.id in active_tickets:
            ticket_channel = guild.get_channel(active_tickets[user.id])
            if ticket_channel:
                await interaction.response.send_message(
                    f"You already have an active ticket: {ticket_channel.mention}",
                    ephemeral=True
                )
                return

        # Get ticket category
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if category is None:
            await interaction.response.send_message(
                "❌ Ticket category not found! Please contact an administrator.",
                ephemeral=True
            )
            return

        # Create ticket channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True)
        }

        # Clean username for channel name
        clean_name = "".join(
            c for c in user.display_name if c.isalnum() or c in ('-', '_')).lower()[:20]
        ticket_channel = await category.create_text_channel(
            name=f"ticket-{clean_name}",
            overwrites=overwrites
        )

        # Store ticket info
        active_tickets[user.id] = ticket_channel.id
        ticket_data[ticket_channel.id] = {
            'user_id': user.id,
            'user_name': user.display_name,
            'created_at': datetime.now(),
            'created_by': user.display_name,
            'messages': []
        }

        # Create ticket embed
        embed = discord.Embed(
            title="🎫 Buy-In Tickets",
            description=f"Hello {user.mention}! Taki Will Be With You Shortly",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Use !close to close this ticket")

        # Add close button to ticket
        view = TicketCloseView()

        await ticket_channel.send(
            content=f"{user.mention}",
            embed=embed,
            view=view
        )

        await interaction.response.send_message(
            f"🎫 Ticket created: {ticket_channel.mention}",
            ephemeral=True
        )

        # Log ticket creation
        await self.log_ticket_creation(guild, user, ticket_channel)

    async def log_ticket_creation(self, guild, user, ticket_channel):
        """Log ticket creation to log channel"""
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="🎫 Ticket Created",
                description=f"**User:** {user.mention} (`{user.display_name}`)\n**Channel:** {ticket_channel.mention}\n**Time:** <t:{int(datetime.now().timestamp())}:F>",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            await log_channel.send(embed=embed)


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="persistent_view:close_ticket", emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.close_ticket_channel(interaction)

    async def close_ticket_channel(self, interaction: discord.Interaction):
        channel = interaction.channel
        guild = interaction.guild

        # Create transcript before closing
        await self.create_transcript(channel, interaction.user)

        # Find user who owns this ticket
        ticket_owner = None
        for user_id, channel_id in active_tickets.items():
            if channel_id == channel.id:
                ticket_owner = user_id
                break

        if ticket_owner:
            del active_tickets[ticket_owner]

        # Send confirmation
        embed = discord.Embed(
            title="🔒 Ticket Closed",
            description="This ticket has been closed and will be deleted in 5 seconds.",
            color=discord.Color.red()
        )

        await interaction.response.send_message(embed=embed)

        # Delete channel after delay
        await asyncio.sleep(5)
        await channel.delete()

    async def create_transcript(self, channel, closed_by):
        """Create and send a transcript of the ticket"""
        if channel.id not in ticket_data:
            return

        ticket_info = ticket_data[channel.id]
        messages = []

        # Collect all messages from the ticket
        async for message in channel.history(limit=None, oldest_first=True):
            # Skip system messages and bot commands
            if message.author.bot and message.content.startswith('!'):
                continue

            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            attachments_info = ""

            # Handle attachments
            if message.attachments:
                attachment_names = []
                for attachment in message.attachments:
                    if attachment.content_type and attachment.content_type.startswith('image/'):
                        attachment_names.append(
                            f"[Image: {attachment.filename}]")
                    else:
                        attachment_names.append(
                            f"[File: {attachment.filename}]")
                attachments_info = " " + ", ".join(attachment_names)

            message_content = message.content if message.content else "[No text content]"
            messages.append(
                f"[{timestamp}] {message.author.display_name}: {message_content}{attachments_info}")

        # Create transcript text
        transcript_text = f"Ticket Transcript - {ticket_info['user_name']}\n"
        transcript_text += f"Created: {ticket_info['created_at'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        transcript_text += f"Closed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        transcript_text += f"Closed by: {closed_by.display_name}\n"
        transcript_text += "="*50 + "\n\n"
        transcript_text += "\n".join(messages)

        # Send to log channel
        log_channel = channel.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            # Create embed for quick info
            embed = discord.Embed(
                title="📄 Ticket Transcript",
                description=f"**User:** {ticket_info['user_name']}\n**Created:** <t:{int(ticket_info['created_at'].timestamp())}:F>\n**Closed:** <t:{int(datetime.now().timestamp())}:F>\n**Closed by:** {closed_by.display_name}",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            # Create file with full transcript
            transcript_file = discord.File(
                io.BytesIO(transcript_text.encode('utf-8')),
                filename=f"transcript-{ticket_info['user_name']}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
            )

            await log_channel.send(embed=embed, file=transcript_file)

        # Clean up ticket data
        if channel.id in ticket_data:
            del ticket_data[channel.id]

# ===== AUTO ROLE & WELCOME FEATURES =====


@bot.event
async def on_ready():
    print(f'{bot.user} is online and ready!')
    print(f'Auto-role ID set to: {AUTO_ROLE_ID}')
    print(f'Ticket Category ID: {TICKET_CATEGORY_ID}')
    print(f'Log Channel ID: {LOG_CHANNEL_ID}')

    # Add the persistent views
    bot.add_view(TicketView())
    bot.add_view(TicketCloseView())

    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Made By Taki"))


@bot.event
async def on_member_join(member):
    """Auto-role and welcome when members join"""
    role = member.guild.get_role(AUTO_ROLE_ID)

    if role is None:
        print(f"❌ Error: Role with ID {AUTO_ROLE_ID} not found!")
        return

    try:
        await member.add_roles(role)
        print(f"✅ Assigned {role.name} to {member.display_name}")

        welcome_channel = member.guild.system_channel
        if welcome_channel:
            await welcome_channel.send(f"You are now a part of Ennui {member.mention}")

    except discord.Forbidden:
        print("❌ Error: Bot doesn't have permission to assign roles!")
    except Exception as e:
        print(f"❌ Error assigning role: {e}")

# ===== TICKET COMMANDS =====


@bot.command()
@commands.has_permissions(administrator=True)
async def setup_tickets(ctx):
    """Setup the ticket system with a create ticket button"""
    embed = discord.Embed(
        title="🎫 Buy-In Tickets",
        description="Click the button below to purchase!",
        color=discord.Color.green()
    )
    embed.add_field(
        name="Price",
        value="• $10 for Monthly Roles\n• $15 for Perm Roles",
        inline=False
    )

    view = TicketView()
    await ctx.send(embed=embed, view=view)
    await ctx.message.delete()


@bot.command()
async def close(ctx):
    """Close the current ticket"""
    if isinstance(ctx.channel, discord.DMChannel):
        return

    # Check if this is a ticket channel
    if ctx.channel.id in active_tickets.values():
        # Create transcript before closing
        view = TicketCloseView()
        await view.create_transcript(ctx.channel, ctx.author)

        # Find and remove from active tickets
        for user_id, channel_id in list(active_tickets.items()):
            if channel_id == ctx.channel.id:
                del active_tickets[user_id]
                break

        embed = discord.Embed(
            title="🔒 Ticket Closed",
            description="This ticket has been closed and will be deleted in 5 seconds.",
            color=discord.Color.red()
        )

        await ctx.send(embed=embed)

        # Delete channel after delay
        await asyncio.sleep(5)
        await ctx.channel.delete()
    else:
        await ctx.send("❌ This command can only be used in ticket channels.")


@bot.command()
@commands.has_permissions(administrator=True)
async def force_close(ctx, channel: discord.TextChannel = None):
    """Force close a ticket (Admin only)"""
    target_channel = channel or ctx.channel

    if target_channel.id in active_tickets.values():
        # Create transcript before closing
        view = TicketCloseView()
        await view.create_transcript(target_channel, ctx.author)

        # Find and remove from active tickets
        for user_id, channel_id in list(active_tickets.items()):
            if channel_id == target_channel.id:
                del active_tickets[user_id]
                break

        await target_channel.delete()
        await ctx.send(f"✅ Force closed ticket: {target_channel.name}")
    else:
        await ctx.send("❌ This is not a valid ticket channel.")


@bot.command()
@commands.has_permissions(administrator=True)
async def ticket_stats(ctx):
    """Show ticket statistics"""
    embed = discord.Embed(
        title="📊 Ticket Statistics",
        color=discord.Color.blue()
    )
    embed.add_field(name="Active Tickets", value=len(
        active_tickets), inline=True)
    embed.add_field(name="Ticket Category",
                    value=f"<#{TICKET_CATEGORY_ID}>", inline=True)

    await ctx.send(embed=embed)

# ===== AUTO-ROLE COMMANDS =====


@bot.command()
@commands.has_permissions(administrator=True)
async def set_autorole(ctx, role_id: int):
    """Set the auto-role for new members using role ID"""
    global AUTO_ROLE_ID
    role = ctx.guild.get_role(role_id)
    if role is None:
        await ctx.send("❌ Role not found! Please check the role ID.")
        return
    AUTO_ROLE_ID = role_id
    await ctx.send(f"✅ Auto-role set to: **{role.name}**")


@bot.command()
@commands.has_permissions(administrator=True)
async def autorole(ctx, role: discord.Role):
    """Set the auto-role for new members by mentioning the role"""
    global AUTO_ROLE_ID
    AUTO_ROLE_ID = role.id
    await ctx.send(f"✅ Auto-role set to: **{role.name}**")


@bot.command()
async def check_autorole(ctx):
    """Check the current auto-role setting"""
    role = ctx.guild.get_role(AUTO_ROLE_ID)
    if role:
        await ctx.send(f"🔄 Current auto-role: **{role.name}** (ID: {AUTO_ROLE_ID})")
    else:
        await ctx.send(f"❌ Auto-role not set or role not found (ID: {AUTO_ROLE_ID})")


@bot.command()
async def test_autorole(ctx):
    """Test the auto-role on yourself"""
    role = ctx.guild.get_role(AUTO_ROLE_ID)
    if role is None:
        await ctx.send("❌ Auto-role not set or role not found!")
        return
    try:
        await ctx.author.add_roles(role)
        await ctx.send(f"✅ Test successful! Assigned **{role.name}** to you.")
    except discord.Forbidden:
        await ctx.send("❌ Bot doesn't have permission to assign roles!")
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

# ===== HELP COMMAND =====


@bot.command()
async def commands(ctx):
    """Show all available commands"""
    embed = discord.Embed(
        title="🤖 Bot Commands Menu",
        description="Here are all the available commands:",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="🎫 Ticket Commands",
        value="• `!setup_tickets` - Create ticket panel (Admin)\n• `!close` - Close current ticket\n• `!force_close` - Force close ticket (Admin)\n• `!ticket_stats` - Show ticket stats",
        inline=False
    )

    embed.add_field(
        name="👥 Auto-Role Commands",
        value="• `!autorole @role` - Set auto-role (Admin)\n• `!set_autorole ID` - Set auto-role by ID (Admin)\n• `!check_autorole` - Check current auto-role\n• `!test_autorole` - Test auto-role on yourself",
        inline=False
    )

    await ctx.send(embed=embed)

# Remove the default help command
bot.remove_command('help')

bot.run(TOKEN)

