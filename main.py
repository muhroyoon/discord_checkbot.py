import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone
import json
import os

TOKEN = os.getenv("TOKEN")

ATTENDANCE_CHANNEL_ID = 1483339751674089544
MIDNIGHT_CHANNEL_ID = 1377672440783704219
GUILD_ID = 1377672440276058214

ROLE_IDS = [1482028706850537676, 1409209830152863845, 1409208539548876801]

KST = timezone(timedelta(hours=9))
DATA_FILE = "/data/attendance.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ===== 데이터 =====
def load_data():
    if not os.path.exists(DATA_FILE):
        data = {"users": {}, "today_order": {}}
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
        return data

    with open(DATA_FILE, "r") as f:
        data = json.load(f)

    data.setdefault("users", {})
    data.setdefault("today_order", {})
    return data

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()
users = data["users"]

# ===== 출석 버튼 =====
class DailyAttendanceView(discord.ui.View):
    def __init__(self, date):
        super().__init__(timeout=None)
        self.date = date
        count = len(data["today_order"].get(date, []))
        self.add_item(AttendanceButton(date, count))


class AttendanceButton(discord.ui.Button):
    def __init__(self, date, count):
        super().__init__(
            label=f"✅ 출석하기 ({count})",
            style=discord.ButtonStyle.success,
            custom_id=f"attendance_{date}"
        )
        self.date = date

        today = datetime.now(KST).strftime("%Y-%m-%d")
        if self.date != today:
            self.disabled = True

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        now = datetime.now(KST)
        today = datetime.now(KST).strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")

        if user_id not in users:
            users[user_id] = {
                "last_attendance": "",
                "streak": 0,
                "total": 0,
                "monthly": {}
            }

        user = users[user_id]

        if user["last_attendance"] == today:
            await interaction.response.send_message("⚠ 이미 출석했습니다!", ephemeral=True)
            return

        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        user["streak"] = user["streak"] + 1 if user["last_attendance"] == yesterday else 1

        user["last_attendance"] = today
        user["total"] += 1
        user["monthly"][month] = user["monthly"].get(month, 0) + 1

        if today not in data["today_order"]:
            data["today_order"][today] = []

        data["today_order"][today].append(user_id)

        save_data()

        # ===== 순위 =====
        today_list = data["today_order"][today]
        rank = today_list.index(user_id) + 1

        first_bonus = ""
        if rank == 1:
            first_bonus = "🎉 **오늘 1등입니다! 축하합니다!!** 🎉\n\n"

        # ===== 개인 메시지 (🔥 안정 방식) =====
        await interaction.response.send_message(
            f"✅ 출석 완료!\n\n"
            f"{first_bonus}"
            f"🏅 오늘 순위: {rank}등\n\n"
            f"📅 이번 달 출석: {user['monthly'][month]}일\n"
            f"📈 총 누적 출석: {user['total']}일\n"
            f"🔥 현재 연속 출석: {user['streak']}일",
            ephemeral=True
        )

        # ===== 출석판 업데이트 =====
        guild = interaction.guild
        first_user = guild.get_member(int(today_list[0])) if today_list else None

        first_text = f"🥇 1등: {first_user.display_name}" if first_user else "🥇 1등: 없음"

        embed = discord.Embed(
            title=f"📅 {today} 출석하기",
            description=f"{first_text}\n\n현재 출석 인원: {len(today_list)}명",
            color=0x00ffcc
        )

        view = DailyAttendanceView(today)

        await interaction.message.edit(embed=embed, view=view)


# ===== 이동 버튼 =====
class MoveToAttendanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="📍 출석하러 가기",
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/channels/{GUILD_ID}/{ATTENDANCE_CHANNEL_ID}"
            )
        )


# ===== 오늘출석 =====
class TodayAttendanceView(discord.ui.View):
    def __init__(self, today_users, guild, per_page=10):
        super().__init__(timeout=180)
        self.today_users = today_users
        self.guild = guild
        self.per_page = per_page
        self.page = 0
        self.total_pages = max((len(today_users) - 1)//per_page + 1, 1)

    def get_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        chunk = self.today_users[start:end]

        desc_lines = []
        for i, uid in enumerate(chunk, start=start + 1):
            member = self.guild.get_member(int(uid))
            name = member.display_name if member else f"ID:{uid}"
            desc_lines.append(f"{i}등. {name}")

        description = f"총 출석 인원: {len(self.today_users)}명\n\n" + "\n".join(desc_lines)

        return discord.Embed(
            title=f"📅 오늘 출석 현황 ({self.page+1}/{self.total_pages})",
            description=description,
            color=0x00ffcc
        )

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page + 1 < self.total_pages:
            self.page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()


@tree.command(name="오늘출석")
async def today_attendance(interaction: discord.Interaction):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    today_users = data.get("today_order", {}).get(today, [])

    if not today_users:
        await interaction.response.send_message("❌ 오늘 출석한 유저가 없습니다.", ephemeral=True)
        return

    view = TodayAttendanceView(today_users, interaction.guild)

    await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)


# ===== 출석생성 =====
@tree.command(name="출석생성")
async def create_attendance(interaction: discord.Interaction):
    today = datetime.now(KST).strftime("%Y-%m-%d")

    if today not in data["today_order"]:
        data["today_order"][today] = []
        save_data()

    embed = discord.Embed(
        title=f"📅 {today} 출석하기",
        description="🥇 1등: 없음\n\n현재 출석 인원: 0명",
        color=0x00ffcc
    )

    channel = bot.get_channel(ATTENDANCE_CHANNEL_ID)

    await channel.send(embed=embed, view=DailyAttendanceView(today))
    await interaction.response.send_message("✅ 출석 버튼 생성 완료", ephemeral=True)


# ===== 자정 =====
@tasks.loop(minutes=1)
async def daily():
    now = datetime.now(KST)

    if now.hour == 0 and now.minute == 0:
        today = now.strftime("%Y-%m-%d")

        data["today_order"][today] = []
        save_data()

        attendance_channel = bot.get_channel(ATTENDANCE_CHANNEL_ID)
        notice_channel = bot.get_channel(MIDNIGHT_CHANNEL_ID)

        embed = discord.Embed(
            title=f"📅 {today} 출석하기",
            description="🥇 1등: 없음\n\n현재 출석 인원: 0명",
            color=0x00ffcc
        )

        await attendance_channel.send(
            content="@here",
            embed=embed,
            view=DailyAttendanceView(today),
            allowed_mentions=discord.AllowedMentions(everyone=True)
        )

        await notice_channel.send(
            content="@here\n🌙 출석이 초기화되었습니다!\n\n🔥 오늘의 1등은 누구??\n\n지금 바로 출석하세요!!",
            view=MoveToAttendanceView(),
            allowed_mentions=discord.AllowedMentions(everyone=True)
        )


@bot.event
async def on_ready():
    bot.add_view(DailyAttendanceView("dummy"))
    bot.add_view(MoveToAttendanceView())

    guild = discord.Object(id=GUILD_ID)
    await tree.sync(guild=guild)  # ← 이걸로 복구

    if not daily.is_running():
        daily.start()

    print("READY")
