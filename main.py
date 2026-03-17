import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone
import json
import os
import asyncio

# ===== 환경 변수 =====
TOKEN = os.getenv("TOKEN")

# 채널 ID
ATTENDANCE_CHANNEL_ID = 1483339751674089544  # 출석 버튼 / 통계용
TODAY_CHANNEL_ID = 1483352015747944541      # 오늘 출석 표시 채널
TOTAL_CHANNEL_ID = 1483352131452010516      # 총 누적 출석 표시 채널
MONTHLY_RANK_CHANNEL_ID = 1397125455454273578  # 월간 랭킹 공지 채널

# 서버 ID (월간 랭킹용)
GUILD_ID = 123456789012345678  # 본인 서버 ID로 교체 필요

# 랭킹 대상 역할
ROLE_IDS = [
    1482028706850537676,
    1409209830152863845,
    1409208539548876801
]

KST = timezone(timedelta(hours=9))
DATA_FILE = "attendance.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # 멤버 조회 필수

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ===== 데이터 =====
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()

# ===== 랭킹 =====
def get_ranking(month):
    return sorted(
        [(uid, u["monthly"].get(month, 0)) for uid, u in data.items()],
        key=lambda x: x[1],
        reverse=True
    )

def get_rank(user_id, month):
    ranking = get_ranking(month)
    return next((i+1 for i, u in enumerate(ranking) if u[0] == user_id), "-")

# ===== UI =====
def create_embed(user, rank, month):
    return discord.Embed(
        title="📢 오늘의 출석",
        description=(
            "```yaml\n"
            f"🔥 연속 출석: {user['streak']}일\n"
            f"📅 이번달 출석: {user['monthly'].get(month, 0)}일\n"
            f"🏆 현재 랭킹: {rank}위\n"
            "```"
        ),
        color=0x00ffcc
    )

# ===== 버튼 =====
class AttendanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ 출석하기", style=discord.ButtonStyle.success)
    async def attend(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        now = datetime.now(KST)
        today = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")

        if user_id not in data:
            data[user_id] = {
                "last_attendance": "",
                "streak": 0,
                "total": 0,
                "monthly": {}
            }

        user = data[user_id]

        # 중복 체크
        if user["last_attendance"] == today:
            await interaction.response.send_message("⚠ 이미 출석했습니다!", ephemeral=True)
            return

        # 로딩
        await interaction.response.edit_message(content="⏳ 출석 처리 중...", embed=None, view=None)
        await asyncio.sleep(1)

        # 스트릭
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        if user["last_attendance"] == yesterday:
            user["streak"] += 1
        else:
            user["streak"] = 1

        user["last_attendance"] = today
        user["total"] += 1

        if month not in user["monthly"]:
            user["monthly"][month] = 0
        user["monthly"][month] += 1

        save_data(data)

        rank = get_rank(user_id, month)
        embed = create_embed(user, rank, month)

        # 버튼 상태 변경
        button.label = "✅ 출석 완료"
        button.disabled = True
        button.style = discord.ButtonStyle.gray

        await interaction.edit_original_response(content="🎉 출석 완료!", embed=embed, view=self)

# ===== 슬래시 명령어 =====
@tree.command(name="출석패널", description="출석 버튼 생성")
async def attendance_panel(interaction: discord.Interaction):
    if interaction.channel.id != ATTENDANCE_CHANNEL_ID:
        await interaction.response.send_message("❌ 출석 채널에서만 사용 가능", ephemeral=True)
        return

    embed = discord.Embed(
        title="📢 오늘의 출석",
        description="버튼을 눌러 출석하세요!",
        color=0x00ffcc
    )

    await interaction.response.send_message(embed=embed, view=AttendanceView())

@tree.command(name="출석랭킹", description="출석 랭킹 보기")
async def ranking(interaction: discord.Interaction):
    now = datetime.now(KST)
    month = now.strftime("%Y-%m")

    ranking_list = get_ranking(month)[:10]

    desc = ""
    for i, (user_id, count) in enumerate(ranking_list):
        user = await bot.fetch_user(int(user_id))
        desc += f"{i+1}위 {user.name} - {count}일\n"

    embed = discord.Embed(title="🏆 출석 랭킹", description=desc, color=0xffcc00)
    await interaction.response.send_message(embed=embed)

@tree.command(name="출석통계", description="출석 통계 보기")
async def stats(interaction: discord.Interaction):
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")

    total_users = len(data)
    today_count = len([u for u in data.values() if u["last_attendance"] == today])
    total_attendance = sum(u["total"] for u in data.values())
    monthly_total = sum(u["monthly"].get(month, 0) for u in data.values())
    max_streak = max([u["streak"] for u in data.values()], default=0)

    embed = discord.Embed(
        title="📊 출석 통계",
        description=(
            f"👥 전체 유저: {total_users}명\n"
            f"✅ 오늘 출석: {today_count}명\n"
            f"📅 이번달 출석: {monthly_total}회\n"
            f"🔥 최고 연속 출석: {max_streak}일\n"
            f"📈 총 누적 출석: {total_attendance}회"
        ),
        color=0x2b2d31
    )

    await interaction.response.send_message(embed=embed)

# ===== 월간 랭킹 공지 (특정 역할) =====
async def announce_last_month():
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return

    channel = bot.get_channel(MONTHLY_RANK_CHANNEL_ID)
    if channel is None:
        return

    now = datetime.now(KST)
    last_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    # 특정 역할 가진 멤버 필터링
    eligible_members = [
        m for m in guild.members
        if any(role.id in ROLE_IDS for role in m.roles)
    ]

    # 랭킹 계산
    ranking_list = []
    for member in eligible_members:
        user_data = data.get(str(member.id))
        if user_data:
            count = user_data.get("monthly", {}).get(last_month, 0)
            ranking_list.append((member, count))

    # 출석 많음 순으로 정렬
    ranking_list.sort(key=lambda x: x[1], reverse=True)

    # 랭킹 embed 생성
    desc = ""
    for i, (member, count) in enumerate(ranking_list):
        desc += f"{i+1}위 {member.display_name} - {count}일\n"

    embed = discord.Embed(
        title=f"🏆 {last_month} 출석 랭킹",
        description=desc if desc else "출석 데이터가 없습니다.",
        color=0xff6600
    )

    await channel.send(embed=embed)

# ===== 자정 체크 =====
@tasks.loop(minutes=1)
async def daily_check():
    now = datetime.now(KST)
    if now.hour == 0 and now.minute == 0:
        if now.day == 1:
            await announce_last_month()

# ===== 채널 이름 갱신 (오늘 출석 / 총 누적 출석) =====
async def update_stats_channels(bot):
    today_channel = bot.get_channel(TODAY_CHANNEL_ID)
    total_channel = bot.get_channel(TOTAL_CHANNEL_ID)
    if today_channel is None or total_channel is None:
        return

    today = datetime.now(KST).strftime("%Y-%m-%d")
    today_count = len([u for u in data.values() if u["last_attendance"] == today])
    total_attendance = sum(u["total"] for u in data.values())

    # 오늘 출석 채널
    new_today_name = f"✅ 오늘 출석: {today_count}"
    if today_channel.name != new_today_name:
        await today_channel.edit(name=new_today_name)

    # 총 누적 출석 채널
    new_total_name = f"📈 총 누적 출석: {total_attendance}"
    if total_channel.name != new_total_name:
        await total_channel.edit(name=new_total_name)

@tasks.loop(minutes=1)
async def refresh_stats_loop():
    await update_stats_channels(bot)

# ===== 핵심 (슬래시 등록 및 루프 시작) =====
@bot.event
async def on_ready():
    try:
        synced = await tree.sync()
        print(f"슬래시 명령어 {len(synced)}개 동기화 완료")
    except Exception as e:
        print("sync 에러:", e)

    print(f"봇 로그인 완료: {bot.user}")
    daily_check.start()
    refresh_stats_loop.start()

# ===== 실행 =====
bot.run(TOKEN)
