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
ATTENDANCE_CHANNEL_ID = 1483339751674089544
TODAY_CHANNEL_ID = 1483357576996323349
TOTAL_CHANNEL_ID = 1483357602304757872
MONTHLY_RANK_CHANNEL_ID = 1397125455454273578

# 서버 ID
GUILD_ID = 1377672440276058214

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
intents.members = True

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

# ===== 버튼 (Persistent View) =====
class AttendanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent View

    @discord.ui.button(label="✅ 출석하기", style=discord.ButtonStyle.success, custom_id="attendance_button")
    async def attend(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        now = datetime.now(KST)
        today = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")

        if user_id not in data:
            data[user_id] = {"last_attendance":"","streak":0,"total":0,"monthly":{}}

        user = data[user_id]

        if user["last_attendance"] == today:
            await interaction.response.send_message("⚠ 이미 출석했습니다!", ephemeral=True)
            return

        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        user["streak"] = user["streak"] + 1 if user["last_attendance"] == yesterday else 1
        user["last_attendance"] = today
        user["total"] += 1
        user["monthly"][month] = user.get("monthly", {}).get(month, 0) + 1

        save_data(data)

        rank = get_rank(user_id, month)
        embed = create_embed(user, rank, month)

        await interaction.response.send_message("🎉 출석 완료!", embed=embed, ephemeral=True)

# ===== 슬래시 명령어 =====
@tree.command(name="출석패널", description="출석 버튼 생성")
async def attendance_panel(interaction: discord.Interaction):
    if interaction.channel.id != ATTENDANCE_CHANNEL_ID:
        await interaction.response.send_message("❌ 출석 채널에서만 사용 가능", ephemeral=True)
        return

    embed = discord.Embed(title="📢 오늘의 출석", description="버튼을 눌러 출석하세요!", color=0x00ffcc)
    await interaction.response.send_message(embed=embed, view=AttendanceView())

@tree.command(name="출석통계", description="출석 통계 보기")
async def stats(interaction: discord.Interaction):
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")

    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        await interaction.response.send_message("❌ 서버를 찾을 수 없습니다.", ephemeral=True)
        return

    eligible_members = [m for m in guild.members if any(role.id in ROLE_IDS for role in m.roles)]
    total_users = len(eligible_members)

    today_count = len([u for uid, u in data.items() if u["last_attendance"]==today and int(uid) in [m.id for m in eligible_members]])
    total_attendance = sum([u["total"] for uid, u in data.items() if int(uid) in [m.id for m in eligible_members]])
    monthly_total = sum([u["monthly"].get(month,0) for uid,u in data.items() if int(uid) in [m.id for m in eligible_members]])
    max_streak = max([u["streak"] for uid,u in data.items() if int(uid) in [m.id for m in eligible_members]], default=0)

    embed = discord.Embed(
        title="📊 출석 통계",
        description=(f"👥 전체 유저: {total_users}명\n"
                     f"✅ 오늘 출석: {today_count}명\n"
                     f"📅 이번달 출석: {monthly_total}회\n"
                     f"🔥 최고 연속 출석: {max_streak}일\n"
                     f"📈 총 누적 출석: {total_attendance}회"),
        color=0x2b2d31
    )
    await interaction.response.send_message(embed=embed)

@tree.command(name="출석점검", description="특정 유저 출석 기록 확인")
@app_commands.describe(member="출석 기록 확인할 유저")
async def check_attendance(interaction: discord.Interaction, member: discord.Member):
    user_id = str(member.id)
    if user_id not in data:
        await interaction.response.send_message(f"❌ {member.display_name}님의 출석 기록이 없습니다.", ephemeral=True)
        return

    user = data[user_id]
    now = datetime.now(KST)
    month = now.strftime("%Y-%m")
    this_month_count = user.get("monthly", {}).get(month,0)
    total_count = user.get("total",0)

    last_6_months = []
    for i in range(5,-1,-1):
        year = now.year
        mon = now.month - i
        if mon<=0:
            year-=1
            mon+=12
        m_str = f"{year}-{mon:02d}"
        count = user.get("monthly", {}).get(m_str,0)
        last_6_months.append(f"{m_str} : {count}일")

    embed = discord.Embed(
        title=f"📊 {member.display_name} 출석 기록",
        description=(f"📅 이번 달 출석: {this_month_count}일\n"
                     f"📈 총 누적 출석: {total_count}일\n\n"
                     f"🗓 지난 6개월 출석:\n" + "\n".join(last_6_months)),
        color=0x00ffcc
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ===== 월간 랭킹 공지 =====
async def announce_last_month():
    guild = bot.get_guild(GUILD_ID)
    if guild is None: return
    channel = bot.get_channel(MONTHLY_RANK_CHANNEL_ID)
    if channel is None: return

    now = datetime.now(KST)
    last_month = (now.replace(day=1)-timedelta(days=1)).strftime("%Y-%m")
    eligible_members = [m for m in guild.members if any(role.id in ROLE_IDS for role in m.roles)]

    ranking_list=[]
    for m in eligible_members:
        user_data = data.get(str(m.id))
        if user_data:
            ranking_list.append((m, user_data.get("monthly",{}).get(last_month,0)))
    ranking_list.sort(key=lambda x:x[1], reverse=True)

    desc=""
    for i,(m,count) in enumerate(ranking_list):
        desc+=f"{i+1}위 {m.display_name} - {count}일\n"

    embed=discord.Embed(title=f"🏆 {last_month} 출석 랭킹",
                        description=desc if desc else "출석 데이터가 없습니다.",
                        color=0xff6600)
    await channel.send(embed=embed)

# ===== 자정 체크 =====
@tasks.loop(minutes=1)
async def daily_check():
    now = datetime.now(KST)
    if now.hour==0 and now.minute==0:
        if now.day==1:
            await announce_last_month()

# ===== 채널 갱신 (5분 주기) =====
async def update_stats_channels(bot):
    today_channel = bot.get_channel(TODAY_CHANNEL_ID)
    total_channel = bot.get_channel(TOTAL_CHANNEL_ID)
    if today_channel is None or total_channel is None:
        print("❌ 갱신 실패: 채널을 찾을 수 없음")
        return

    today_count = len([u for u in data.values() if u["last_attendance"]==datetime.now(KST).strftime("%Y-%m-%d")])
    total_attendance = sum(u["total"] for u in data.values())

    new_today_name=f"Today Check : {today_count}"
    new_total_name=f"Total Check : {total_attendance}"

    try:
        if today_channel.name!=new_today_name:
            await today_channel.edit(name=new_today_name)
            print(f"✅ 채널 이름 변경 성공: {today_channel.id} → {new_today_name}")
    except discord.Forbidden:
        print(f"❌ 권한 부족: 오늘 출석 채널({today_channel.id}) 이름 변경 실패")
    except Exception as e:
        print(f"❌ 오늘 출석 채널 변경 에러: {e}")

    try:
        if total_channel.name!=new_total_name:
            await total_channel.edit(name=new_total_name)
            print(f"✅ 채널 이름 변경 성공: {total_channel.id} → {new_total_name}")
    except discord.Forbidden:
        print(f"❌ 권한 부족: 총 누적 출석 채널({total_channel.id}) 이름 변경 실패")
    except Exception as e:
        print(f"❌ 총 누적 출석 채널 변경 에러: {e}")

@tasks.loop(minutes=5)
async def refresh_stats_loop():
    await update_stats_channels(bot)

# ===== 핵심 =====
@bot.event
async def on_ready():
    # Persistent View 등록
    bot.add_view(AttendanceView())

    try:
        synced = await tree.sync()
        print(f"슬래시 명령어 {len(synced)}개 동기화 완료")
    except Exception as e:
        print("sync 에러:", e)

    print(f"봇 로그인 완료: {bot.user}")
    daily_check.start()
    refresh_stats_loop.start()

bot.run(TOKEN)
