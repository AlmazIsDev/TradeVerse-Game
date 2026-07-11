"""Небольшая диагностическая утилита: печатает коллекции MongoDB, их размер
и пример полей документа. Запуск: ``python check_schema.py``.

(Ранее здесь был мёртвый SQLAlchemy-код от старой SQL-версии — заменён на
рабочую проверку под текущую Motor/MongoDB-схему.)
"""
import asyncio

from database import get_db


async def check():
    db = get_db()
    names = await db.list_collection_names()
    if not names:
        print("В базе пока нет коллекций.")
        return
    print(f"Коллекции ({len(names)}):")
    for name in sorted(names):
        count = await db[name].count_documents({})
        sample = await db[name].find_one({})
        fields = ", ".join(sorted(sample.keys())) if sample else "—"
        print(f"  • {name}: {count} документ(ов)")
        print(f"      поля: {fields}")


if __name__ == "__main__":
    asyncio.run(check())
