import json
import os
from datetime import datetime, timedelta

DATA_FILE = "/data/attendance.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        raise FileNotFoundError(f"{DATA_FILE} 파일이 없습니다.")

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    data.setdefault("users", {})
    data.setdefault("today_order", {})
    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def calculate_streak(attendance_dates):
    if not attendance_dates:
        return 0, ""

    sorted_dates = sorted(attendance_dates)
    last_date = sorted_dates[-1]

    streak = 1
    current = last_date

    for i in range(len(sorted_dates) - 2, -1, -1):
        prev_date = sorted_dates[i]
        if current - prev_date == timedelta(days=1):
            streak += 1
            current = prev_date
        else:
            break

    return streak, last_date.strftime("%Y-%m-%d")


def main():
    data = load_data()
    today_order = data.get("today_order", {})
    users = {}

    cleaned_today_order = {}
    duplicate_removed_count = 0

    user_attendance_dates = {}

    for day_str in sorted(today_order.keys()):
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
        except ValueError:
            print(f"잘못된 날짜 형식 건너뜀: {day_str}")
            continue

        original_list = today_order.get(day_str, [])
        seen = set()
        cleaned_list = []

        for user_id in original_list:
            if user_id in seen:
                duplicate_removed_count += 1
                continue
            seen.add(user_id)
            cleaned_list.append(user_id)

            if user_id not in user_attendance_dates:
                user_attendance_dates[user_id] = []
            user_attendance_dates[user_id].append(day)

        cleaned_today_order[day_str] = cleaned_list

    for user_id, attendance_dates in user_attendance_dates.items():
        attendance_dates = sorted(attendance_dates)

        monthly = {}
        for day in attendance_dates:
            month_key = day.strftime("%Y-%m")
            monthly[month_key] = monthly.get(month_key, 0) + 1

        streak, last_attendance = calculate_streak(attendance_dates)

        users[user_id] = {
            "last_attendance": last_attendance,
            "streak": streak,
            "total": len(attendance_dates),
            "monthly": monthly
        }

    data["today_order"] = cleaned_today_order
    data["users"] = users

    save_data(data)

    print("정리 완료")
    print(f"중복 제거 수: {duplicate_removed_count}")
    print(f"유저 수: {len(users)}")
    print(f"출석 일자 수: {len(cleaned_today_order)}")


if __name__ == "__main__":
    main()
