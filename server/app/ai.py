"""AI 助手：内置指令解析（查询 + 管理员可执行写操作）+ 可选大模型（OpenAI 兼容）自然语言。"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from . import clock, models, outbound, secret_store
from .config import settings


logger = logging.getLogger(__name__)


# ---------- 数据辅助 ----------
def _parse(dt: str):
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def age_text(birthday: str, ref: datetime | None = None) -> str:
    b = _parse_date(birthday)
    if not b:
        return "未知"
    reference = clock.local_today(ref)
    mo = (reference.year - b.year) * 12 + (reference.month - b.month)
    if reference.day < b.day:
        mo -= 1
    mo = max(mo, 0)
    y, m = divmod(mo, 12)
    return (f"{y}岁" if y else "") + (f"{m}个月" if m else ("" if y else "未满月"))


def days_old(birthday: str, ref: datetime | None = None) -> int:
    b = _parse_date(birthday)
    if not b:
        return 0
    return max(0, (clock.local_today(ref) - b).days)


def since_text(ts: str, now: datetime | None = None) -> str:
    t = _parse(ts)
    if not t:
        return "—"
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    secs = max(0, (clock.as_utc(now) - t.astimezone(timezone.utc)).total_seconds())
    h, m = int(secs // 3600), int((secs % 3600) // 60)
    return f"{h}小时{m}分" if h else f"{m}分钟"


def get_settings(db):
    s = db.get(models.Setting, 1)
    return secret_store.reveal_settings_data((s.data if s else {}) or {})


def latest_growth(db):
    rows = db.execute(select(models.Growth)).scalars().all()
    rows = [r for r in rows if r.date]
    rows.sort(key=lambda r: r.date)
    return rows[-1] if rows else None


def daily_stats(db, now: datetime | None = None):
    start, end = clock.local_day_utc_bounds(now)
    lo, hi = start.isoformat(), end.isoformat()
    today_rows = db.execute(
        select(models.Daily).where(models.Daily.time >= lo, models.Daily.time < hi)
    ).scalars().all()
    feeds = [r for r in today_rows if r.type == "feeding"]
    total = sum(int(r.amount or 0) for r in feeds)
    pee = sum(1 for r in today_rows if r.type == "diaper" and r.diaperType == "pee")
    poop = sum(1 for r in today_rows if r.type == "diaper" and r.diaperType == "poop")
    last_feed = db.execute(
        select(models.Daily).where(models.Daily.type == "feeding")
        .order_by(models.Daily.time.desc()).limit(1)
    ).scalars().first()
    target = int((get_settings(db).get("feeding") or {}).get("dailyTarget") or 900)
    return dict(feeds=feeds, total=total, pee=pee, poop=poop, last_feed=last_feed,
                target=target, pct=min(100, round(total / target * 100)) if target else 0)


def snapshot(db) -> str:
    b = db.get(models.Baby, 1)
    name = b.name if b else "宝贝"
    gender = b.gender if b else "girl"
    birthday = b.birthday if b else ""
    g = latest_growth(db)
    s = daily_stats(db)
    n_ms = db.query(models.Milestone).count()
    n_diary = db.query(models.Diary).count()
    n_msg = db.query(models.Message).filter_by(status="approved").count()
    last = since_text(s["last_feed"].time) if s["last_feed"] else "—"
    return (
        f"宝贝：{name}，{'女宝' if gender=='girl' else '男宝'}，生日{birthday}，"
        f"现在{age_text(birthday)}（第{days_old(birthday)}天）。"
        f"最新身高{getattr(g,'height',None)}cm、体重{getattr(g,'weight',None)}kg。"
        f"今日喂奶{len(s['feeds'])}次共{s['total']}ml（目标{s['target']}ml），"
        f"尿布 尿{s['pee']}次/便{s['poop']}次，距上次喂奶{last}。"
        f"里程碑{n_ms}个、日记{n_diary}篇、已通过留言{n_msg}条。"
    )


# ---------- 写操作（管理员） ----------
def act_add_feeding(db, amount=None, feedType="formula", note=""):
    st = get_settings(db)
    amount = int(amount or (st.get("feeding") or {}).get("defaultAmount") or 150)
    row = models.Daily(type="feeding", feedType=feedType or "formula", amount=amount,
                       time=clock.utc_now().isoformat(), note=note or "")
    db.add(row); db.commit()
    s = daily_stats(db)
    return f"已记录一次喂奶 {amount}ml ✅ 今天累计 {s['total']}ml / {s['target']}ml。"


def act_add_diaper(db, diaperType="pee", note=""):
    row = models.Daily(type="diaper", diaperType=diaperType or "pee",
                       time=clock.utc_now().isoformat(), note=note or "")
    db.add(row); db.commit()
    return f"已记录一次换尿布（{'大便' if diaperType=='poop' else '小便'}）✅"


# ---------- 内置指令解析 ----------
def local_answer(text: str, db, is_admin: bool):
    q = (text or "").strip()
    has = lambda *ks: any(k in q for k in ks)
    b = db.get(models.Baby, 1)
    name = b.name if b else "宝贝"
    num = re.search(r"(\d{2,4})", q)

    if (has("记录", "记一笔", "添加", "记一次") and has("喂奶", "喝奶")) or re.search(r"喂奶.*\d+", q):
        if not is_admin:
            return "记录数据需要先登录后台哦～", True
        ft = "breast" if has("母乳", "亲喂") else "formula"
        return act_add_feeding(db, num.group(1) if num else None, ft), True
    if has("换尿布", "尿布", "拉了", "粑粑", "便便") and has("记录", "添加", "记一笔", "记一次"):
        if not is_admin:
            return "记录数据需要先登录后台哦～", True
        dt = "poop" if has("便", "粑", "拉") else "pee"
        return act_add_diaper(db, dt), True

    if has("几岁", "多大", "年龄", "几个月"):
        bday = b.birthday if b else ""
        return f"{name}现在 {age_text(bday)}，已经陪伴我们 {days_old(bday)} 天啦 🎉", True
    if has("多高", "身高"):
        g = latest_growth(db)
        return (f"{name}最新身高是 {g.height} cm（{g.date}）📏" if g else "还没有身高记录哦。"), True
    if has("多重", "体重", "几斤", "几公斤"):
        g = latest_growth(db)
        return (f"{name}最新体重是 {g.weight} kg ⚖️" if g else "还没有体重记录哦。"), True
    if has("上次喂", "多久没", "距离上次", "上顿"):
        s = daily_stats(db)
        return (f"距离上次喂奶已经 {since_text(s['last_feed'].time)} 了 🍼" if s["last_feed"] else "今天还没有喂奶记录。"), True
    if has("今天", "今日") and has("奶", "喂", "喝"):
        s = daily_stats(db)
        return f"今天已喂奶 {len(s['feeds'])} 次，共 {s['total']}ml，完成每日目标的 {s['pct']}%（目标 {s['target']}ml）。", True
    if has("尿布", "便便", "大便", "小便"):
        s = daily_stats(db)
        return f"今天换尿布：小便 {s['pee']} 次，大便 {s['poop']} 次 👶", True
    if has("里程碑", "最近", "大事"):
        m = db.execute(select(models.Milestone)).scalars().all()
        m = sorted([x for x in m if x.date], key=lambda x: x.date, reverse=True)
        return (f"最近的里程碑是「{m[0].title}」（{m[0].date}）：{m[0].desc}" if m else "还没有里程碑。"), True
    if has("你好", "您好", "hi", "hello", "在吗"):
        return f"你好呀！我是{name}的成长小助手 🍼 可以问我年龄、身高体重、喂奶统计、最近里程碑等。", True
    if has("帮助", "能做什么", "会什么", "怎么用"):
        return "我可以查询年龄/身高体重、今日喂奶与尿布统计、距上次喂奶时间、最近里程碑；登录后还能帮你记录喂奶/换尿布。", True
    return "", False


# ---------- 大模型（OpenAI 兼容） ----------
TOOLS = [
    {"type": "function", "function": {"name": "add_feeding", "description": "记录一次喂奶",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "integer", "description": "毫升"},
            "feedType": {"type": "string", "enum": ["formula", "breast"]}}}}},
    {"type": "function", "function": {"name": "add_diaper", "description": "记录一次换尿布",
        "parameters": {"type": "object", "properties": {
            "diaperType": {"type": "string", "enum": ["pee", "poop"]}}}}},
]


def _run_tool(name, args, db, is_admin):
    if not is_admin:
        return "需要登录后台才能记录数据。"
    if name == "add_feeding":
        return act_add_feeding(db, args.get("amount"), args.get("feedType", "formula"))
    if name == "add_diaper":
        return act_add_diaper(db, args.get("diaperType", "pee"))
    return "未知操作。"


def llm_answer(messages, db, is_admin):
    st = get_settings(db).get("ai") or {}
    endpoint = outbound.resolve_ai_endpoint(
        st.get("baseUrl") or "https://api.openai.com/v1",
        settings.AI_ALLOW_PRIVATE_BASE_URLS,
    )
    key, model = st.get("apiKey"), st.get("model") or "gpt-4o-mini"
    sys = ("你是宝贝成长记录网站的智能助手，用简体中文亲切温暖地回答。以下为实时数据：\n"
           + snapshot(db)
           + "\n可调用工具记录喂奶/换尿布（仅在用户已登录后台时有效）。")
    msgs = [{"role": "system", "content": sys}] + [
        {"role": m["role"], "content": m.get("content", "")} for m in messages[-8:]
    ]
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for _ in range(4):
        response = outbound.post_json(
            endpoint,
            "chat/completions",
            headers=headers,
            payload={"model": model, "messages": msgs, "tools": TOOLS, "temperature": 0.6},
            timeout=40,
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        msgs.append(message)
        calls = message.get("tool_calls") or []
        if not calls:
            return message.get("content") or "（无内容）"
        for call in calls:
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except Exception:
                args = {}
            out = _run_tool(call["function"]["name"], args, db, is_admin)
            msgs.append({"role": "tool", "tool_call_id": call["id"], "content": out})
    return "（对话轮次过多）"


def chat(messages, db, is_admin: bool):
    text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            text = m.get("content", "")
            break
    st = get_settings(db).get("ai") or {}
    use_llm = bool(st.get("enabled") and st.get("apiKey"))
    if use_llm:
        try:
            return {"reply": llm_answer(messages, db, is_admin), "mode": "llm"}
        except Exception:
            logger.exception("大模型对话调用失败，已回退内置助手")
            reply, _ = local_answer(text, db, is_admin)
            return {"reply": (reply or "大模型暂时不可用。") + "（已回退内置助手）", "mode": "local_fallback"}
    reply, handled = local_answer(text, db, is_admin)
    if not handled:
        reply = f'我暂时不太确定怎么回答"{text}"。可以问我年龄、身高体重、喂奶统计或最近里程碑；或在管理端“显示设置”填入大模型 API Key 开启自然语言对话。'
    return {"reply": reply, "mode": "local"}


# ---------- 成长小结 ----------
def build_recap(db, period, now: datetime | None = None):
    days = 30 if period == "month" else 7
    start_date, end_date, start_utc, end_utc = clock.local_period(now, days)
    date_start = start_date.isoformat()
    date_end = (end_date + timedelta(days=1)).isoformat()
    b = db.get(models.Baby, 1)
    name = b.name if b else "宝贝"
    label = "这一个月" if period == "month" else "这一周"
    ms = db.execute(
        select(models.Milestone.title)
        .where(models.Milestone.date >= date_start, models.Milestone.date < date_end)
        .order_by(models.Milestone.id.asc())
    ).scalars().all()
    diary_count = db.scalar(
        select(func.count(models.Diary.id)).where(
            models.Diary.date >= date_start,
            models.Diary.date < date_end,
        )
    ) or 0
    video_count = db.scalar(
        select(func.count(models.Video.id)).where(
            models.Video.date >= date_start,
            models.Video.date < date_end,
        )
    ) or 0
    photo_count = db.scalar(
        select(func.count(models.Photo.id))
        .join(models.Album, models.Album.id == models.Photo.albumId)
        .where(models.Photo.takenAt >= date_start, models.Photo.takenAt < date_end)
    ) or 0
    feed_count, total_ml = db.execute(
        select(
            func.count(models.Daily.id),
            func.coalesce(func.sum(models.Daily.amount), 0),
        ).where(
            models.Daily.type == "feeding",
            models.Daily.time >= start_utc.isoformat(),
            models.Daily.time < end_utc.isoformat(),
        )
    ).one()
    latest_growth = db.execute(
        select(models.Growth.height, models.Growth.weight)
        .where(models.Growth.date >= date_start, models.Growth.date < date_end)
        .order_by(models.Growth.date.desc(), models.Growth.id.desc())
        .limit(1)
    ).one_or_none()
    growth_txt = (
        f"最新身高 {latest_growth.height}cm、体重 {latest_growth.weight}kg。"
        if latest_growth else ""
    )
    feeding_txt = f"平均每天喝奶约 {round(total_ml / days)}ml。" if feed_count else ""

    parts = [f"{label}，{name}又悄悄长大了一点。"]
    if ms:
        parts.append("新解锁的里程碑：" + "、".join(ms) + "。")
    counts = []
    if diary_count:
        counts.append(f"{diary_count} 篇日记")
    if photo_count:
        counts.append(f"{photo_count} 张照片")
    if video_count:
        counts.append(f"{video_count} 段视频")
    if counts:
        parts.append("我们一起记录了 " + "、".join(counts) + "。")
    if growth_txt:
        parts.append(growth_txt)
    if feeding_txt:
        parts.append(feeding_txt)
    if len(parts) == 1:
        parts.append("虽然没有留下太多新记录，但每一天的陪伴都很珍贵。")
    parts.append(f"期待下一段旅程里，{name}带来更多小惊喜 💕")
    text = "".join(parts)
    context = (f"周期：{label}（近{days}天）。里程碑：{('、'.join(ms)) or '无'}。"
               f"日记{diary_count}篇、照片{photo_count}张、视频{video_count}段。{growth_txt}{feeding_txt}")
    return text, context, name, label


def _llm_recap(context, name, label, st):
    endpoint = outbound.resolve_ai_endpoint(
        st.get("baseUrl") or "https://api.openai.com/v1",
        settings.AI_ALLOW_PRIVATE_BASE_URLS,
    )
    key, model = st.get("apiKey"), st.get("model") or "gpt-4o-mini"
    sys = (f"你是宝贝成长记录网站的助手。请用简体中文、温暖亲切的口吻，为家长写一段{label}的成长小结"
           f"（120-180字，1-2段，不要用列表），可适当加入 emoji。以下是本期数据：\n{context}")
    response = outbound.post_json(
        endpoint,
        "chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        payload={"model": model, "temperature": 0.7,
                 "messages": [{"role": "system", "content": sys},
                              {"role": "user", "content": f"请为{name}写这段成长小结。"}]},
        timeout=40,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def generate_recap(db, period="week"):
    text, context, name, label = build_recap(db, period)
    st = get_settings(db).get("ai") or {}
    if st.get("enabled") and st.get("apiKey"):
        try:
            return _llm_recap(context, name, label, st)
        except Exception:
            logger.exception("大模型成长小结调用失败，已回退内置模板")
            return text
    return text
