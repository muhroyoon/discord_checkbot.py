import json
import os
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

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
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return data

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    data.setdefault("users", {})
    data.setdefault("today_order", {})
    return data


def refresh_data():
    global data, users
    data = load_data()
    users = data["users"]
    return data


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


data = load_data()
users = data["users"]


def get_ranking_periods(now):
    today = now.date()

    this_week_start = today - timedelta(days=today.weekday())
    this_week_end = this_week_start + timedelta(days=6)

    last_week_start = this_week_start - timedelta(days=7)
    last_week_end = this_week_start - timedelta(days=1)

    this_month_start = today.replace(day=1)
    next_month = (this_month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    this_month_end = next_month - timedelta(days=1)

    last_month_end = this_month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    return {
        "this_week": ("이번주", this_week_start, this_week_end),
        "last_week": ("지난주", last_week_start, last_week_end),
        "this_month": ("이번달", this_month_start, this_month_end),
        "last_month": ("지난달", last_month_start, last_month_end),
    }


def get_period_ranking(guild, period_key):
    refresh_data()
    period_name, start_date, end_date = get_ranking_periods(datetime.now(KST))[period_key]

    eligible_members = {
        str(member.id): member
        for member in guild.members
        if any(role.id in ROLE_IDS for role in member.roles)
    }

    counts = {uid: 0 for uid in eligible_members}
    position_scores = {uid: 0 for uid in eligible_members}

    for day_str, attendee_ids in data.get("today_order", {}).items():
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if start_date <= day <= end_date:
            for idx, uid in enumerate(attendee_ids, start=1):
                if uid in counts:
                    counts[uid] += 1
                    position_scores[uid] += idx

    ranking_list = sorted(
        counts.items(),
        key=lambda x: (-x[1], position_scores[x[0]], x[0])
    )
    return period_name, start_date, end_date, ranking_list



def count_user_attendance_in_range(user_id, start_date, end_date):
    refresh_data()
    count = 0

    for day_str, attendee_ids in data.get("today_order", {}).items():
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if start_date <= day <= end_date and user_id in attendee_ids:
            count += 1

    return count


# ===== 출석 버튼 =====
class DailyAttendanceView(discord.ui.View):
    def __init__(self, date):
        super().__init__(timeout=None)
        self.date = date

        refresh_data()
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
        refresh_data()

        user_id = str(interaction.user.id)
        now = datetime.now(KST)
        today = self.date
        month = now.strftime("%Y-%m")

        if today not in data["today_order"]:
            data["today_order"][today] = []

        today_list = data["today_order"][today]

        if user_id in today_list:
            rank = today_list.index(user_id) + 1
            user = users.get(user_id, {})
            monthly_count = user.get("monthly", {}).get(month, 0)
            total_count = user.get("total", 0)
            streak_count = user.get("streak", 0)

            await interaction.response.send_message(
                f"⚠ 이미 출석했습니다!\n\n"
                f"🏅 오늘 순위: {rank}등\n\n"
                f"📅 이번 달 출석: {monthly_count}일\n"
                f"📈 총 누적 출석: {total_count}일\n"
                f"🔥 현재 연속 출석: {streak_count}일",
                ephemeral=True
            )
            return

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

        today_list.append(user_id)
        save_data()

        rank = today_list.index(user_id) + 1

        await interaction.response.send_message(
            f"✅ 출석 완료!\n\n"
            f"🏅 오늘 순위: {rank}등\n\n"
            f"📅 이번 달 출석: {user['monthly'][month]}일\n"
            f"📈 총 누적 출석: {user['total']}일\n"
            f"🔥 현재 연속 출석: {user['streak']}일",
            ephemeral=True
        )

        guild = interaction.guild
        first_user = guild.get_member(int(today_list[0])) if today_list else None
        first_text = f"🥇 1등: {first_user.display_name}" if first_user else "🥇 1등: 없음"

        embed = discord.Embed(
            title=f"📅 {today} 출석하기",
            description=(
                f"{first_text}\n\n"
                f"현재 출석 인원: {len(today_list)}명"
            ),
            color=0x00FFCC
        )

        await interaction.message.edit(embed=embed, view=DailyAttendanceView(today))


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
class AttendanceRankingView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=180)
        self.guild = guild
        self.period_key = "this_week"
        self.page = 0
        self.per_page = 10

    def get_current_ranking(self):
        return get_period_ranking(self.guild, self.period_key)

    def get_embed(self):
        period_name, start_date, end_date, ranking_list = self.get_current_ranking()
        total_pages = max((len(ranking_list) - 1) // self.per_page + 1, 1)

        start = self.page * self.per_page
        end = start + self.per_page
        chunk = ranking_list[start:end]

        desc_lines = [
            f"기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
            ""
        ]

        for i, (uid, count) in enumerate(chunk, start=start + 1):
            member = self.guild.get_member(int(uid))
            name = member.display_name if member else f"ID:{uid}"
            desc_lines.append(f"{i}위 {name} - {count}일")

        if len(desc_lines) == 2:
            desc_lines.append("기록 없음")

        embed = discord.Embed(
            title="HICKS 출석랭킹!!",
            description=f"선택: [{period_name}]\n\n" + "\n".join(desc_lines),
            color=0xFFCC00
        )
        embed.set_footer(text=f"페이지 {self.page + 1}/{total_pages}")
        return embed

    async def update_period(self, interaction, period_key):
        self.period_key = period_key
        self.page = 0
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="이번주", style=discord.ButtonStyle.primary, row=0)
    async def this_week(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_period(interaction, "this_week")

    @discord.ui.button(label="지난주", style=discord.ButtonStyle.primary, row=0)
    async def last_week(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_period(interaction, "last_week")

    @discord.ui.button(label="이번달", style=discord.ButtonStyle.success, row=0)
    async def this_month(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_period(interaction, "this_month")

    @discord.ui.button(label="지난달", style=discord.ButtonStyle.success, row=0)
    async def last_month(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_period(interaction, "last_month")

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        _, _, _, ranking_list = self.get_current_ranking()
        if (self.page + 1) * self.per_page < len(ranking_list):
            self.page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="📍 내 순위", style=discord.ButtonStyle.secondary, row=1)
    async def myrank(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        period_name, _, _, ranking_list = self.get_current_ranking()

        for i, (uid, count) in enumerate(ranking_list, start=1):
            if uid == user_id:
                await interaction.response.send_message(
                    f"👉 {period_name} 내 순위: {i}위 ({count}일)",
                    ephemeral=True
                )
                return

        await interaction.response.send_message("❌ 기록 없음", ephemeral=True)


# ===== 명령어 =====
@tree.command(name="출석랭킹", description="출석 랭킹 보기")
async def ranking(interaction: discord.Interaction):
    view = AttendanceRankingView(interaction.guild)
    await interaction.response.send_message(embed=view.get_embed(), view=view)


@tree.command(name="출석점검", description="유저 출석 확인 (이번주/지난주/이번달/6개월)")
@app_commands.describe(member="출석 기록 확인할 유저")
async def check_attendance(interaction: discord.Interaction, member: discord.Member):
    refresh_data()

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
    periods = get_ranking_periods(now)

    this_week_count = count_user_attendance_in_range(user_id, periods["this_week"][1], periods["this_week"][2])
    last_week_count = count_user_attendance_in_range(user_id, periods["last_week"][1], periods["last_week"][2])
    this_month_count = user.get("monthly", {}).get(month, 0)

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
            f"1. 이번주: {this_week_count}일\n"
            f"2. 지난주: {last_week_count}일\n"
            f"3. 이번달: {this_month_count}일\n"
            f"4. 6개월:\n" + "\n".join(last_6_months)
        ),
        color=0x00FFCC
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


class TodayAttendanceView(discord.ui.View):
    def __init__(self, today_users, guild, per_page=10):
        super().__init__(timeout=180)
        self.today_users = today_users
        self.guild = guild
        self.per_page = per_page
        self.page = 0
        self.total_pages = max((len(today_users) - 1) // per_page + 1, 1)

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
            title=f"📅 오늘 출석 현황 ({self.page + 1}/{self.total_pages})",
            description=description,
            color=0x00FFCC
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
    refresh_data()

    today = datetime.now(KST).strftime("%Y-%m-%d")
    today_users = data.get("today_order", {}).get(today, [])

    if not today_users:
        await interaction.response.send_message("❌ 오늘 출석한 유저가 없습니다.", ephemeral=True)
        return

    view = TodayAttendanceView(today_users, interaction.guild)
    await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)


@tree.command(name="출석생성", description="오늘 출석 버튼 생성 (관리자용)")
async def create_attendance(interaction: discord.Interaction):
    refresh_data()

    today = datetime.now(KST).strftime("%Y-%m-%d")

    if today not in data["today_order"]:
        data["today_order"][today] = []
        save_data()

    embed = discord.Embed(
        title=f"📅 {today} 출석하기",
        description="🥇 1등: 없음\n\n현재 출석 인원: 0명",
        color=0x00FFCC
    )

    channel = bot.get_channel(ATTENDANCE_CHANNEL_ID)
    await channel.send(embed=embed, view=DailyAttendanceView(today))

    await interaction.response.send_message("✅ 출석 버튼 생성 완료", ephemeral=True)


# ===== 자정 =====
@tasks.loop(minutes=1)
async def daily():
    refresh_data()
    now = datetime.now(KST)

    if now.hour == 0 and now.minute == 0:
        today = now.strftime("%Y-%m-%d")

        if today not in data["today_order"]:
            data["today_order"][today] = []
            save_data()

        attendance_channel = bot.get_channel(ATTENDANCE_CHANNEL_ID)
        notice_channel = bot.get_channel(MIDNIGHT_CHANNEL_ID)

        embed = discord.Embed(
            title=f"📅 {today} 출석하기",
            description="🥇 1등: 없음\n\n현재 출석 인원: 0명",
            color=0x00FFCC
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
