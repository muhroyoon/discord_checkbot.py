import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import json
import os
import asyncio

TOKEN = "여기에_봇_토큰"
ATTENDANCE_CHANNEL_ID = 1483339751674089544  # 채널 ID

KST = timezone(timedelta(hours=9))
DATA_FILE = "attendance.json"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 데이터 로드/저장
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()

# 랭킹 계산
def get_ranking(month):
    ranking = sorted(
        [(uid, u["monthly"].get(month, 0)) for uid, u in data.items()],
        key=lambda x: x[1],
        reverse=True
    )
    return ranking

def get_rank(user_id, month):
    ranking = get_ranking(month)
    return next((i+1 for i, u in enumerate(ranking) if u[0] == user_id), "-")

# UI 생성
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

# 버튼
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

        # 로딩 연출
        await interaction.response.edit_message(content="⏳ 출석 처리 중...", embed=None, view=None)
        await asyncio.sleep(1)

        # 스트릭 계산
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

# 출석 패널
@bot.command()
async def 출석패널(ctx):
    if ctx.channel.id != ATTENDANCE_CHANNEL_ID:
        return

    embed = discord.Embed(
        title="📢 오늘의 출석",
        description="버튼을 눌러 출석하세요!",
        color=0x00ffcc
    )

    await ctx.send(embed=embed, view=AttendanceView())

# 랭킹
@bot.command()
async def 출석랭킹(ctx):
    now = datetime.now(KST)
    month = now.strftime("%Y-%m")

    ranking = get_ranking(month)[:10]

    desc = ""
    for i, (user_id, count) in enumerate(ranking):
        user = await bot.fetch_user(int(user_id))
        desc += f"{i+1}위 {user.name} - {count}일\n"

    embed = discord.Embed(title="🏆 출석 랭킹", description=desc, color=0xffcc00)
    await ctx.send(embed=embed)

# 통계
@bot.command()
async def 출석통계(ctx):
    today = datetime.now(KST).strftime("%Y-%m-%d")

    today_count = len([u for u in data.values() if u["last_attendance"] == today])
    total = sum(u["total"] for u in data.values())

    embed = discord.Embed(title="📊 출석 통계", color=0x3399ff)
    embed.add_field(name="오늘 출석자", value=f"{today_count}명")
    embed.add_field(name="총 출석 수", value=f"{total}")

    await ctx.send(embed=embed)

# 월간 랭킹 공지
async def announce_last_month():
    channel = bot.get_channel(ATTENDANCE_CHANNEL_ID)
    now = datetime.now(KST)
    last_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    ranking = get_ranking(last_month)[:10]

    desc = ""
    for i, (user_id, count) in enumerate(ranking):
        user = await bot.fetch_user(int(user_id))
        desc += f"{i+1}위 {user.name} - {count}일\n"

    embed = discord.Embed(
        title=f"🏆 {last_month} 출석 랭킹",
        description=desc,
        color=0xff6600
    )

    await channel.send(embed=embed)

# 자정 체크
@tasks.loop(minutes=1)
async def daily_check():
    now = datetime.now(KST)

    if now.hour == 0 and now.minute == 0:
        if now.day == 1:
            await announce_last_month()

@bot.event
async def on_ready():
    print(f"봇 로그인: {bot.user}")
    daily_check.start()

bot.run(TOKEN)
