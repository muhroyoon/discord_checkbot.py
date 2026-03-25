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

@tree.command(name="출석점검", description="유저 출석 확인 (이번 달/총/지난 6개월)")
@app_commands.describe(member="출석 기록 확인할 유저")
async def check_attendance(interaction: discord.Interaction, member: discord.Member):
    user_id = str(member.id)
    if user_id not in users:
        await interaction.response.send_message(f"❌ {member.display_name}님의 출석 기록이 없습니다.", ephemeral=True)
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

class TodayAttendanceView(discord.ui.View):
    def __init__(self, today_users, guild, per_page=10):
        super().__init__(timeout=180)
        self.today_users = today_users  # 오늘 출석자 ID 리스트
        self.guild = guild
        self.per_page = per_page
        self.page = 0
        self.total_pages = max((len(today_users) - 1) // per_page + 1, 1)  # 최소 1페이지

    def get_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        chunk = self.today_users[start:end]

        desc_lines = []
        for i, uid in enumerate(chunk, start=start + 1):
            # 캐시 없으면 ID로 표시
            member = self.guild.get_member(int(uid))
            name = member.display_name if member else f"ID:{uid}"
            desc_lines.append(f"{i}등. {name}")

        description = f"총 출석 인원: {len(self.today_users)}명\n\n" + "\n".join(desc_lines)
        embed = discord.Embed(
            title=f"📅 오늘 출석 현황 ({self.page + 1}/{self.total_pages}페이지)",
            description=description,
            color=0x00ffcc
        )
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()  # 첫 페이지일 때 아무 변화 없음

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page + 1 < self.total_pages:
            self.page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()  # 마지막 페이지일 때 아무 변화 없음


@tree.command(name="오늘출석", description="오늘 출석한 유저 전체 목록 확인 (출석 순서)")
async def today_attendance(interaction: discord.Interaction):
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")

    today_users = data.get("today_order", {}).get(today, [])
    if not today_users:
        await interaction.response.send_message("❌ 오늘 출석한 유저가 없습니다.", ephemeral=True)
        return

    guild = interaction.guild
    view = TodayAttendanceView(today_users, guild)
    await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)
    
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

# ===== 채널 갱신 =====
async def update_stats_channels():
    today_channel = bot.get_channel(TODAY_CHANNEL_ID)
    total_channel = bot.get_channel(TOTAL_CHANNEL_ID)

    if not today_channel or not total_channel:
        return

    today_count = sum(1 for u in users.values() if u["last_attendance"] == datetime.now(KST).strftime("%Y-%m-%d"))
    total_attendance = sum(u["total"] for u in users.values())

    try:
        await today_channel.edit(name=f"Today Check : {today_count}")
        await total_channel.edit(name=f"Total Check : {total_attendance}")
    except:
        pass

@tasks.loop(minutes=10)
async def refresh_stats_loop():
    await update_stats_channels()

# ===== 실행 =====
@bot.event
async def on_ready():
    bot.add_view(AttendanceView())
    bot.add_view(MoveToAttendanceView())
    await tree.sync()
    daily.start()
    print("READY")

bot.run(TOKEN)
