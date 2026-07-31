"""示例数据：填充所有模块，用于演示 / 快速起步。图片用 picsum 占位图，用户上传后自行替换。"""
import copy
from datetime import datetime, timedelta, timezone

from . import clock, models
from .defaults import DEFAULT_SETTINGS

BIRTH = "2024-09-15"


def pic(seed, w=800, h=600):
    return f"https://picsum.photos/seed/{seed}/{w}/{h}"


def add_months(date_str, m):
    d = datetime.fromisoformat(date_str)
    year = d.year + (d.month - 1 + m) // 12
    month = (d.month - 1 + m) % 12 + 1
    day = min(d.day, 28)
    return f"{year:04d}-{month:02d}-{day:02d}"


def now_minus(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def seed_sample(db, reset=False):
    if reset:
        for a in db.query(models.Album).all():
            db.delete(a)              # cascade 删除照片
        for M in (models.Milestone, models.Growth, models.Daily, models.Diary, models.Video,
                  models.Message, models.Recap, models.Vaccine, models.Share):
            db.query(M).delete()
        db.commit()

    # 宝贝
    baby = db.get(models.Baby, 1) or models.Baby(id=1)
    baby.name = "小满"; baby.gender = "girl"; baby.birthday = BIRTH
    baby.avatar = pic("xiaoman-av", 400, 400)
    baby.bio = "2024年秋天来到我们身边的小天使，爱笑、爱吃、爱探索世界。这里记录她一点一滴的成长。"
    baby.family = "爸爸 · 妈妈 · 还有一只叫奶糖的猫"
    db.add(baby)

    # 设置
    st = db.get(models.Setting, 1) or models.Setting(id=1)
    st.data = copy.deepcopy(DEFAULT_SETTINGS)
    db.add(st)

    # 里程碑
    ms = [
        (1, "第一次微笑", "情感", "满月刚过，对着妈妈露出了人生第一个微笑，融化了全家。", "ms-smile"),
        (3, "学会翻身", "大动作", "趴着玩的时候突然一个用力翻了过来，自己都吓了一跳。", "ms-roll"),
        (6, "第一口辅食", "饮食", "开始添加米粉，小勺子送到嘴边，吃得满脸都是。", "ms-food"),
        (8, "会坐稳了", "大动作", "终于可以自己稳稳地坐着玩玩具，解放了妈妈的双手。", "ms-sit"),
        (11, "第一次叫妈妈", "语言", "含糊却清晰地喊出了“妈妈”，妈妈激动得哭了。", "ms-mama"),
        (13, "迈出第一步", "大动作", "扶着沙发慢慢松手，独立走出了摇摇晃晃的第一步！", "https://www.w3schools.com/html/mov_bbb.mp4"),
    ]
    for mo, title, cat, desc, seed in ms:
        img = seed if str(seed).startswith("http") else pic(seed, 800, 500)
        db.add(models.Milestone(date=add_months(BIRTH, mo), title=title, category=cat, desc=desc, image=img))

    # 相册 + 照片
    albums = [
        ("满月纪念", 1, "小满满月啦", "al1", 6),
        ("百天写真", 3, "100天的小可爱", "al2", 5),
        ("第一个夏天", 10, "海边的欢乐时光", "al3", 7),
        ("周岁生日", 12, "一周岁快乐", "al4", 4),
    ]
    for name, mo, desc, seed, n in albums:
        a = models.Album(name=name, date=add_months(BIRTH, mo), desc=desc, cover=pic(seed + "-c", 700, 700))
        for i in range(1, n + 1):
            a.photos.append(models.Photo(url=pic(f"{seed}-{i}", 900, 900),
                                         caption=f"{name} {i}", takenAt=add_months(BIRTH, mo), sort=i))
        if seed == "al3":
            a.photos.append(models.Photo(url="https://www.w3schools.com/html/mov_bbb.mp4", caption="海边的小视频🎬", takenAt=add_months(BIRTH, mo), sort=n + 1))
        a.cover = a.photos[0].url
        db.add(a)

    # 身高体重
    growth = [(0, 50, 3.3), (1, 54.5, 4.2), (2, 57.8, 5.1), (3, 60.2, 5.8), (4, 62.3, 6.4),
              (5, 64, 6.9), (6, 65.7, 7.3), (8, 68.5, 7.9), (10, 71, 8.5), (12, 74, 9.0),
              (15, 77.5, 9.7), (18, 80.5, 10.4), (21, 83, 11.0)]
    for mo, h, w in growth:
        db.add(models.Growth(date=add_months(BIRTH, mo), height=h, weight=w, head=round(34 + mo * 0.6, 1)))

    # 日常记录（相对当前时间）
    daily = [
        ("feeding", "formula", 150, None, 2.2, "喝得很香"),
        ("diaper", "", None, "poop", 3, "金黄色，正常"),
        ("feeding", "breast", 120, None, 5, ""),
        ("diaper", "", None, "pee", 6, ""),
        ("feeding", "formula", 160, None, 8, ""),
        ("diaper", "", None, "pee", 9.5, ""),
        ("feeding", "formula", 150, None, 11, "夜奶"),
    ]
    for typ, ft, amt, dt, hrs, note in daily:
        db.add(models.Daily(type=typ, feedType=ft or "", amount=amt, diaperType=dt or "",
                           time=now_minus(hrs), note=note))

    # 日记
    diary = [
        (2, "夜里的悄悄话", "今晚你又哭闹到半夜，我抱着你在客厅走了一圈又一圈。可当你在我怀里沉沉睡去，所有的疲惫都值得了。宝贝，慢慢长大呀。", ["d1"]),
        (5, "第一次去公园", "带你去看了大大的草坪和五颜六色的花。你伸着小手想去抓飞过的蝴蝶，眼睛里满是好奇。这个世界，我想慢慢讲给你听。", ["d2a", "d2b"]),
        (9, "牙牙学语", "你开始会发出各种奇怪的音节，像是在跟我们认真地讨论着什么大事。虽然听不懂，但我们都听得津津有味。", ["d3"]),
        (12, "一岁啦", "一年前的今天你来到我们身边，小小的一只。如今你会走、会笑、会撒娇。谢谢你选择我们做你的爸爸妈妈。生日快乐，我的小满。", ["d4"]),
    ]
    for mo, title, content, seeds in diary:
        db.add(models.Diary(date=add_months(BIRTH, mo), title=title, content=content,
                           images=[pic(s, 800, 500) for s in seeds]))

    # “那年今天”演示：一年前 / 两年前的今天（让首页该区块有内容可展示）
    for yrs, t2, c2, cs in [(1, "去年的今天", "翻开相册，去年这一天的你还那么小，时间过得真快呀。", "oty1"),
                            (2, "两年前的今天", "那年今天的小瞬间，被我们悄悄珍藏。", "oty2")]:
        d0 = clock.local_today() - timedelta(days=365 * yrs)
        db.add(models.Diary(date=d0.isoformat(), title=t2, content=c2, images=[pic(cs, 800, 500)]))

    # 成长视频
    videos = [
        (7, "翻身大成功", "珍贵的翻身瞬间，反复看都不腻。", "vc1", "https://www.w3schools.com/html/mov_bbb.mp4"),
        (13, "摇摇晃晃第一步", "人生第一步，全家欢呼那一刻。", "", "https://www.w3schools.com/html/mov_bbb.mp4"),
    ]
    for mo, title, desc, cseed, vurl in videos:
        db.add(models.Video(date=add_months(BIRTH, mo), title=title, desc=desc,
                           cover=(pic(cseed, 800, 500) if cseed else ""), url=vurl))

    # 留言
    msgs = [
        ("奶奶", "我的乖孙女越来越漂亮了，奶奶好想你，快点视频给奶奶看看！", "#ef8fa4", "approved", 30),
        ("小姨", "小满周岁快乐！小姨给你准备了大礼物哦～", "#7fc8d4", "approved", 72),
        ("王阿姨", "太可爱了吧！这个网站做得真用心，满满的爱。", "#ffca7a", "approved", 120),
        ("同事老张", "恭喜恭喜！健康成长～", "#9b8cff", "pending", 10),
    ]
    for name, content, color, status, hrs in msgs:
        db.add(models.Message(name=name, content=content, color=color, status=status, createdAt=now_minus(hrs)))

    # 疫苗：载入标准免疫程序，12 月龄及以前的标记为已接种（演示混合状态）
    from .defaults import VACCINE_SCHEDULE
    for vname, vdose, vmon in VACCINE_SCHEDULE:
        vdate = add_months(BIRTH, vmon) if vmon <= 12 else None
        db.add(models.Vaccine(name=vname, dose=vdose, plannedMonth=vmon, date=vdate))

    db.commit()
