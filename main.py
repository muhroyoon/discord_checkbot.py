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
class AttendanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✅ 출석하기",
        style=discord.ButtonStyle.success,
        custom_id="attendance_button"
    )
    async def attend(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        now = datetime.now(KST)
        today = now.strftime("%Y-%m-%d")
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

        # 오늘 순서
        if today not in data["today_order"]:
            data["today_order"][today] = []

        if user_id not in data["today_order"][today]:
            data["today_order"][today].append(user_id)

        today_rank = data["today_order"][today].index(user_id) + 1

        # 월간 랭킹 (역할 필터)
        guild = interaction.guild
        ranking_list = []

        for member in guild.members:
            if any(role.id in ROLE_IDS for role in member.roles):
                uid = str(member.id)
                count = users.get(uid, {}).get("monthly", {}).get(month, 0)
                ranking_list.append((uid, count))

        ranking_list.sort(key=lambda x: x[1], reverse=True)

        rank = next((i+1 for i, (uid, _) in enumerate(ranking_list) if uid == user_id), "-")

        save_data()

        embed = discord.Embed(
            title="📢 오늘의 출석",
            description=(
                f"```yaml\n"
                f"🔥 연속 출석: {user['streak']}일\n"
                f"📅 이번달 출석: {user['monthly'].get(month,0)}일\n"
                f"🏆 현재 랭킹: {rank}위\n"
                f"⚡ 오늘 출석 순서: {today_rank}등\n"
                f"```"
            ),
            color=0x00ffcc
        )

        await interaction.response.send_message("🎉 출석 완료!", embed=embed, ephemeral=True)

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

# ===== 랭킹 UI =====
class RankingView(discord.ui.View):
    def __init__(self, ranking_list, guild, month):
        super().__init__(timeout=180)
        self.ranking_list = ranking_list
        self.guild = guild
        self.page = 0
        self.per_page = 10
        self.month = month

    def get_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        chunk = self.ranking_list[start:end]

        desc = ""
        for i,(uid,count) in enumerate(chunk, start=start+1):
            member = self.guild.get_member(int(uid))
            if member:
                desc += f"{i}위 {member.display_name} - {count}일\n"

        return discord.Embed(
            title=f"🏆 {self.month} 랭킹 ({self.page+1}/{(len(self.ranking_list)-1)//self.per_page+1})",
            description=desc or "없음",
            color=0xffcc00
        )

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.page+1)*self.per_page < len(self.ranking_list):
            self.page += 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="📍 내 순위", style=discord.ButtonStyle.success)
    async def myrank(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        for i,(uid,count) in enumerate(self.ranking_list, start=1):
            if uid == user_id:
                await interaction.response.send_message(
                    f"👉 당신의 순위: {i}위 ({count}일)",
                    ephemeral=True
                )
                return
        await interaction.response.send_message("❌ 기록 없음", ephemeral=True)

# ===== 명령어 =====
@tree.command(name="출석패널")
async def panel(interaction: discord.Interaction):
    embed = discord.Embed(title="출석", description="버튼 클릭", color=0x00ffcc)
    await interaction.response.send_message(embed=embed, view=AttendanceView())

@tree.command(name="출석랭킹")
async def ranking(interaction: discord.Interaction):
    now = datetime.now(KST)
    month = now.strftime("%Y-%m")

    guild = interaction.guild
    ranking_list = []

    for member in guild.members:
        if any(role.id in ROLE_IDS for role in member.roles):
            uid = str(member.id)
            count = users.get(uid, {}).get("monthly", {}).get(month, 0)
            ranking_list.append((uid, count))

    ranking_list.sort(key=lambda x: x[1], reverse=True)

    view = RankingView(ranking_list, interaction.guild, month)
    await interaction.response.send_message(embed=view.get_embed(), view=view)

@tree.command(name="출석점검")
async def check(interaction: discord.Interaction, member: discord.Member):
    uid = str(member.id)
    if uid not in users:
        await interaction.response.send_message("기록 없음", ephemeral=True)
        return

    user = users[uid]
    now = datetime.now(KST)
    month = now.strftime("%Y-%m")

    embed = discord.Embed(
        title=f"{member.display_name}",
        description=f"이번달: {user['monthly'].get(month,0)}일\n총: {user['total']}일",
        color=0x00ffcc
    )
    await interaction.response.send_message(embed=embed)

# ===== 자정 =====
@tasks.loop(minutes=1)
async def daily():
    now = datetime.now(KST)
    if now.hour == 0 and now.minute == 0:
        data["today_order"] = {}
        save_data()

        await bot.get_channel(MIDNIGHT_CHANNEL_ID).send(
            "@here\n출석 초기화 완료!\n출석체크가 초기화 되었습니다!!\n지금 바로 출석체크하세요!!",
            view=MoveToAttendanceView(),
            allowed_mentions=discord.AllowedMentions(everyone=True)
        )

# ===== 실행 =====
@bot.event
async def on_ready():
    bot.add_view(AttendanceView())
    bot.add_view(MoveToAttendanceView())
    await tree.sync()
    daily.start()
    print("READY")

bot.run(TOKEN)
