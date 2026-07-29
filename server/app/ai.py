"""AI 助手：内置指令解析（查询 + 管理员可执行写操作）+ 可选大模型（OpenAI 兼容）自然语言。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import select

from . import models


# ---------- 数据辅助 ----------
def _parse(dt: str):
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except Exception:
        return None


def age_text(birthday: str, ref: datetime | None = None) -> str:
    b = _parse(birthday)
    if not b:
        return "未知"
    ref = ref or datetime.now(timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    mo = (ref.year - b.year) * 12 + (ref.month - b.month)
    if ref.day < b.day:
        mo -= 1
    mo = max(mo, 0)
    y, m = divmod(mo, 12)
    return (f"{y}岁" if y else "") + (f"{m}个月" if m else ("" if y else "未满月"))


def days_old(birthday: str) -> int:
    b = _parse(birthday)
    if not b:
        return 0
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - b).days)


def since_text(ts: str) -> str:
    t = _parse(ts)
    if not t:
        return "—"
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    secs = max(0, (datetime.now(timezone.utc) - t).total_seconds())
    h, m = int(secs // 3600), int((secs % 3600) // 60)
    return f"{h}小时{m}分" if h else f"{m}分钟"


def get_settings(db):
    s = db.get(models.Setting, 1)
    return (s.data if s else {}) or {}


def latest_growth(db):
    rows = db.execute(select(models.Growth)).scalars().all()
    rows = [r for r in rows if r.date]
    rows.sort(key=lambda r: r.date)
    return rows[-1] if rows else None


def daily_stats(db):
    today = datetime.now(timezone.utc).date()
    lo, hi = today.isoformat(), (today + timedelta(days=1)).isoformat()
    # ISO 时间字符串按字典序即时间序，用 [今日, 明日) 区间把过滤下推到 SQL（time 列有索引）
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
                       time=datetime.now(timezone.utc).isoformat(), note=note or "")
    db.add(row); db.commit()
    s = daily_stats(db)
    return f"已记录一次喂奶 {amount}ml ✅ 今天累计 {s['total']}ml / {s['target']}ml。"


def act_add_diaper(db, diaperType="pee", note=""):
    row = models.Daily(type="diaper", diaperType=diaperType or "pee",
                       time=datetime.now(timezone.utc).isoformat(), note=note or "")
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
    base = (st.get("baseUrl") or "https://api.openai.com/v1").rstrip("/")
    key, model = st.get("apiKey"), st.get("model") or "gpt-4o-mini"
    sys = ("你是宝贝成长记录网站的智能助手，用简体中文亲切温暖地回答。以下为实时数据：\n"
           + snapshot(db)
           + "\n可调用工具记录喂奶/换尿布（仅在用户已登录后台时有效）。")
    msgs = [{"role": "system", "content": sys}] + [
        {"role": m["role"], "content": m.get("content", "")} for m in messages[-8:]
    ]
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=40) as cli:
        for _ in range(4):
            r = cli.post(f"{base}/chat/completions",
                         headers=headers,
                         json={"model": model, "messages": msgs, "tools": TOOLS, "temperature": 0.6})
            r.raise_for_status()
            m = r.json()["choices"][0]["message"]
            msgs.append(m)
            calls = m.get("tool_calls") or []
            if not calls:
                return m.get("content") or "（无内容）"
            for c in calls:
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except Exception:
                    args = {}
                out = _run_tool(c["function"]["name"], args, db, is_admin)
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": out})
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
        except Exception as e:
            reply, _ = local_answer(text, db, is_admin)
            return {"reply": (reply or f"大模型调用失败（{e}）。") + "（已回退内置助手）", "mode": "local_fallback"}
    reply, handled = local_answer(text, db, is_admin)
    if not handled:
        reply = f'我暂时不太确定怎么回答"{text}"。可以问我年龄、身高体重、喂奶统计或最近里程碑；或在后台"显示设置"填入大模型 API Key 开启自然语言对话。'
    return {"reply": reply, "mode": "local"}


# ---------- 成长小结 ----------
def _in_range(dstr, start, end):
    d = _parse(dstr)
    if not d:
        return False
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return start <= d <= end


def build_recap(db, period):
    days = 30 if period == "month" else 7
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    b = db.get(models.Baby, 1)
    name = b.name if b else "宝贝"
    label = "这一个月" if period == "month" else "这一周"
    ms = [m.title for m in db.query(models.Milestone).all() if _in_range(m.date, start, end)]
    diary = [x for x in db.query(models.Diary).all() if _in_range(x.date, start, end)]
    videos = [v for v in db.query(models.Video).all() if _in_range(v.date, start, end)]
    photos = 0
    for a in db.query(models.Album).all():
        photos += sum(1 for p in a.photos if _in_range(p.takenAt, start, end))
    feeds = [d for d in db.query(models.Daily).all() if d.type == "feeding" and _in_range(d.time, start, end)]
    total_ml = sum(int(d.amount or 0) for d in feeds)
    g = [r for r in db.query(models.Growth).all() if r.date and _in_range(r.date, start, end)]
    g.sort(key=lambda r: r.date)
    growth_txt = f"最新身高 {g[-1].height}cm、体重 {g[-1].weight}kg。" if g else ""
    feeding_txt = f"平均每天喝奶约 {round(total_ml / days)}ml。" if feeds else ""

    parts = [f"{label}，{name}又悄悄长大了一点。"]
    if ms:
        parts.append("新解锁的里程碑：" + "、".join(ms) + "。")
    counts = []
    if diary:
        counts.append(f"{len(diary)} 篇日记")
    if photos:
        counts.append(f"{photos} 张照片")
    if videos:
        counts.append(f"{len(videos)} 段视频")
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
               f"日记{len(diary)}篇、照片{photos}张、视频{len(videos)}段。{growth_txt}{feeding_txt}")
    return text, context, name, label


def _llm_recap(db, context, name, label):
    st = get_settings(db).get("ai") or {}
    base = (st.get("baseUrl") or "https://api.openai.com/v1").rstrip("/")
    key, model = st.get("apiKey"), st.get("model") or "gpt-4o-mini"
    sys = (f"你是宝贝成长记录网站的助手。请用简体中文、温暖亲切的口吻，为家长写一段{label}的成长小结"
           f"（120-180字，1-2段，不要用列表），可适当加入 emoji。以下是本期数据：\n{context}")
    with httpx.Client(timeout=40) as cli:
        r = cli.post(base + "/chat/completions",
                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                     json={"model": model, "temperature": 0.7,
                           "messages": [{"role": "system", "content": sys},
                                        {"role": "user", "content": f"请为{name}写这段成长小结。"}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


def generate_recap(db, period="week"):
    text, context, name, label = build_recap(db, period)
    st = get_settings(db).get("ai") or {}
    if st.get("enabled") and st.get("apiKey"):
        try:
            return _llm_recap(db, context, name, label)
        except Exception:
            return text
    return text
