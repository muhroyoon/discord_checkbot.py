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
        today = self.date
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

        # ===== 🔥 추가: 순위 계산 =====
        today_list = data["today_order"][today]
        rank = today_list.index(user_id) + 1

        # ===== 🔥 수정: 개인 메시지 먼저 =====
        await interaction.response.send_message(
            f"✅ 출석 완료!\n\n"
            f"🏅 오늘 순위: {rank}등\n\n"
            f"📅 이번 달 출석: {user['monthly'][month]}일\n"
            f"📈 총 누적 출석: {user['total']}일\n"
            f"🔥 현재 연속 출석: {user['streak']}일",
            ephemeral=True
        )

        # ===== 기존 출석판 업데이트 =====
        guild = interaction.guild

        first_user = None
        if today_list:
            first_user = guild.get_member(int(today_list[0]))

        first_text = f"🥇 1등: {first_user.display_name}" if first_user else "🥇 1등: 없음"

        new_count = len(today_list)

        embed = discord.Embed(
            title=f"📅 {today} 출석하기",
            description=(
                f"{first_text}\n\n"
                f"현재 출석 인원: {new_count}명"
            ),
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
        for i, (uid, count) in enumerate(chunk, start=start + 1):
            member = self.guild.get_member(int(uid))
            if member:
                desc += f"{i}위 {member.display_name} - {count}일\n"

        return discord.Embed(
            title=f"🏆 {self.month} 랭킹 ({self.page + 1}/{(len(self.ranking_list)-1)//self.per_page+1})",
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
        if (self.page + 1) * self.per_page < len(self.ranking_list):
            self.page += 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="📍 내 순위", style=discord.ButtonStyle.success)
    async def myrank(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        for i, (uid, count) in enumerate(self.ranking_list, start=1):
            if uid == user_id:
                await interaction.response.send_message(
                    f"👉 당신의 순위: {i}위 ({count}일)",
                    ephemeral=True
                )
                return
        await interaction.response.send_message("❌ 기록 없음", ephemeral=True)


@tree.command(name="출석랭킹", description="이번 달 출석 랭킹")
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


# ===== 출석점검 =====
@tree.command(name="출석점검", description="유저 출석 확인 (이번 달/총/지난 6개월)")
@app_commands.describe(member="출석 기록 확인할 유저")
async def check_attendance(interaction: discord.Interaction, member: discord.Member):
    user_id = str(member.id)

    if user_id not in users:
        await interaction.response.send_message(
            f"❌ {member.display_name}님의 출석 기록이 없습니다.",
            ephemeral=True
        )
        return

    user = users[user_id]
    now = datetime.now(KST)
    month = now.strftime("%Y-%m")

    this_month_count = user.get("monthly", {}).get(month, 0)
    total_count = user.get("total", 0)

    last_6_months = []
    for i in range(5, -1, -1):
        year = now.year
        mon = now.month - i
        if mon <= 0:
            year -= 1
            mon += 12
        m_str = f"{year}-{mon:02d}"
        last_6_months.append(f"{m_str} : {user.get('monthly', {}).get(m_str, 0)}일")

    embed = discord.Embed(
        title=f"📊 {member.display_name} 출석 기록",
        description=(
            f"📅 이번 달 출석: {this_month_count}일\n"
            f"📈 총 누적 출석: {total_count}일\n\n"
            f"🗓 지난 6개월 출석:\n" + "\n".join(last_6_months)
        ),
        color=0x00ffcc
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


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


@tree.command(name="출석생성", description="오늘 출석 버튼 생성 (관리자용)")
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

    await channel.send(
        embed=embed,
        view=DailyAttendanceView(today)
    )

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

        embed = discord.Embed(
    title="🌙 출석 초기화 완료!",
    description=(
        "🔥 오늘의 1등은 누구??\n\n"
        "지금 바로 출석하세요!!"
    ),
    color=0x5865F2
)

await notice_channel.send(
    content="@here",
    embed=embed,
    view=MoveToAttendanceView(),
    allowed_mentions=discord.AllowedMentions(everyone=True)
)


# ===== 실행 =====
@bot.event
async def on_ready():
    bot.add_view(DailyAttendanceView("dummy"))
    bot.add_view(MoveToAttendanceView())

    guild = discord.Object(id=GUILD_ID)
    await tree.sync(guild=guild)

    if not daily.is_running():
        daily.start()

    print("READY")

bot.run(TOKEN)
