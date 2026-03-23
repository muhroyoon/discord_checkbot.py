import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone
import json
import os

TOKEN = os.getenv("TOKEN")

ATTENDANCE_CHANNEL_ID = 1483339751674089544
MIDNIGHT_CHANNEL_ID = 1377672440783704219  # 🔥 자정 알림 채널
TODAY_CHANNEL_ID = 1483357576996323349
TOTAL_CHANNEL_ID = 1483357602304757872
MONTHLY_RANK_CHANNEL_ID = 1397125455454273578
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

    if "users" not in data:
        data = {"users": data, "today_order": {}}

    if "today_order" not in data:
        data["today_order"] = {}

    return data

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()
users = data["users"]
today_order = data["today_order"]

# ===== 랭킹 =====
def get_ranking(month):
    return sorted(
        [(uid, u["monthly"].get(month, 0)) for uid, u in users.items()],
        key=lambda x: x[1],
        reverse=True
    )

def get_rank(user_id, month):
    ranking = get_ranking(month)
    return next((i+1 for i, u in enumerate(ranking) if u[0] == user_id), "-")

# ===== UI =====
def create_embed(user, rank, month, today_rank):
    return discord.Embed(
        title="📢 오늘의 출석",
        description=(
            f"```yaml\n🔥 연속 출석: {user['streak']}일\n"
            f"📅 이번달 출석: {user['monthly'].get(month,0)}일\n"
            f"🏆 현재 랭킹: {rank}위\n"
            f"⚡ 오늘 출석 순서: {today_rank}등\n```"
        ),
        color=0x00ffcc
    )

# ===== 출석 버튼 =====
class AttendanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ 출석하기", style=discord.ButtonStyle.success, custom_id="attendance_button")
    async def attend(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        now = datetime.now(KST)
        today = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")

        if user_id not in users:
            users[user_id] = {"last_attendance":"","streak":0,"total":0,"monthly":{}}

        user = users[user_id]

        if user["last_attendance"] == today:
            await interaction.response.send_message("⚠ 이미 출석했습니다!", ephemeral=True)
            return

        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        user["streak"] = user["streak"]+1 if user["last_attendance"]==yesterday else 1
        user["last_attendance"] = today
        user["total"] += 1
        user["monthly"][month] = user.get("monthly",{}).get(month,0)+1

        if today not in today_order:
            today_order[today] = []

        if user_id not in today_order[today]:
            today_order[today].append(user_id)

        today_rank = today_order[today].index(user_id) + 1

        save_data(data)

        rank = get_rank(user_id, month)
        embed = create_embed(user, rank, month, today_rank)

        await interaction.response.send_message("🎉 출석 완료!", embed=embed, ephemeral=True)
        await update_stats_channels()

# ===== 🔥 채널 이동 버튼 =====
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

# ===== 🔥 자정 메시지 =====
async def send_midnight_message():
    channel = bot.get_channel(MIDNIGHT_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(
        title="🌙 출석 초기화 완료!",
        description="```yaml\n출석체크가 초기화 되었습니다!!\n지금 바로 출석체크하세요!! 🚀```",
        color=0x00ffcc
    )

    await channel.send(
        content="@here",  # 🔥 멘션 추가
        embed=embed,
        view=MoveToAttendanceView(),
        allowed_mentions=discord.AllowedMentions(everyone=True)
    )

# ===== 명령어 =====
@tree.command(name="출석패널", description="출석 버튼 생성")
async def attendance_panel(interaction: discord.Interaction):
    if interaction.channel.id != ATTENDANCE_CHANNEL_ID:
        await interaction.response.send_message("❌ 출석 채널에서만 사용 가능", ephemeral=True)
        return

    embed = discord.Embed(title="📢 오늘의 출석", description="버튼을 눌러 출석하세요!", color=0x00ffcc)
    await interaction.response.send_message(embed=embed, view=AttendanceView())

# ===== 자정 체크 =====
@tasks.loop(minutes=1)
async def daily_check():
    now = datetime.now(KST)

    if now.hour == 0 and now.minute == 0:
        today = now.strftime("%Y-%m-%d")
        data["today_order"] = {today: []}
        save_data(data)

        await send_midnight_message()

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

# ===== on_ready =====
@bot.event
async def on_ready():
    bot.add_view(AttendanceView())
    bot.add_view(MoveToAttendanceView())
    synced = await tree.sync()
    print(f"봇 로그인 완료: {bot.user}")
    print(f"슬래시 명령어 {len(synced)}개 동기화 완료 ✅")
    print("봇준비완료 🚀")
    daily_check.start()
    refresh_stats_loop.start()

bot.run(TOKEN)
