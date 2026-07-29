"""初始化数据库并填充示例数据。用法：在 server/ 目录下执行  python seed.py"""
from app.db import Base, engine, SessionLocal
from app.main import ensure_init, ensure_schema
from app.sampledata import seed_sample


def main():
    Base.metadata.create_all(engine)
    ensure_schema()
    db = SessionLocal()
    try:
        ensure_init(db)                 # 确保管理员/宝贝/设置存在
        seed_sample(db, reset=True)     # 清空内容并写入示例数据
        print("✅ 已填充示例数据。")
        print("   管理员账号见 .env（默认 admin / admin123）。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
