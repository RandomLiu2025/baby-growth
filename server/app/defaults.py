"""默认显示设置（首次启动写入 settings 单例）。结构与前端一致。"""

DEFAULT_SETTINGS = {
    "theme": {
        "name": "甜心粉", "primary": "#ec8aa0", "primaryD": "#d75f7e",
        "secondary": "#7fc6d0", "accent": "#ffc178", "bg": "#fff6f3",
    },
    "deco": {"enabled": True, "opacity": 0.5, "emoji": ["🍼", "🌸", "⭐", "🧸", "🎈", "☁️", "💕"]},
    "modules": {"timeline": True, "gallery": True, "growth": True, "vaccine": True, "daily": True,
                "diary": True, "videos": True, "messages": True, "about": True},
    "home": {"hero": True, "countdown": True, "onthisday": True, "carousel": True,
             "milestones": True, "growth": True, "videos": True, "diary": True, "recap": True, "vaccine": True},
    "feeding": {"defaultAmount": 150, "dailyTarget": 900},
    "ai": {"enabled": False, "apiKey": "", "baseUrl": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "faviconUrl": "",
    "photoFrame": "polaroid",
}

# 国家免疫规划参考（简化核心）：(名称, 剂次, 建议月龄)
VACCINE_SCHEDULE = [
    ("乙肝疫苗", 1, 0), ("乙肝疫苗", 2, 1), ("乙肝疫苗", 3, 6),
    ("卡介苗", 1, 0),
    ("脊灰疫苗", 1, 2), ("脊灰疫苗", 2, 3), ("脊灰疫苗", 3, 4), ("脊灰疫苗", 4, 48),
    ("百白破疫苗", 1, 3), ("百白破疫苗", 2, 4), ("百白破疫苗", 3, 5), ("百白破疫苗", 4, 18),
    ("麻风疫苗", 1, 8),
    ("麻腮风疫苗", 1, 18),
    ("乙脑减毒疫苗", 1, 8), ("乙脑减毒疫苗", 2, 24),
    ("A群流脑疫苗", 1, 6), ("A群流脑疫苗", 2, 9),
    ("甲肝减毒疫苗", 1, 18),
]

DEFAULT_BABY = {
    "name": "宝贝", "gender": "girl", "birthday": "",
    "avatar": "", "bio": "记录宝贝一点一滴的成长。", "family": "",
}
