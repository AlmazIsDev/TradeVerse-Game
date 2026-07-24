"""Универсальный редактор БД для админа: просмотр/правка/удаление любых коллекций.

ponytail: без allowlist коллекций — полностью универсальный редактор по
требованию (см. docs/superpowers/specs/2026-07-23-admin-db-editor-design.md).
Сырой JSON-редактор — плохая правка может незаметно сломать данные (например
строка вместо datetime ломает isinstance-проверки вроде _aware() в
market_data.py). Апгрейд-путь при необходимости — типизированный редактор
для конкретной "болящей" коллекции.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from bson import json_util, ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from auth import require_admin
from database import get_db

router = APIRouter(prefix="/api/admin/db", tags=["admin-db"])

LIST_LIMIT_CAP = 200

# Резолвер ID-ссылок -> человекочитаемое имя. Универсальный редактор не знает
# схему, поэтому маппинг полей задаём явно по соглашениям об именах.
# field -> (target_collection, display_field)
REF_MAP = {
    "userId": ("users", "username"),
    "ownerId": ("users", "username"),
    "orderedBy": ("users", "username"),
    "issuer": ("users", "username"),
    "sellerId": ("users", "username"),
    "buyerId": ("users", "username"),
    "companyId": ("companies", "name"),
    "businessId": ("cityroof_businesses", "name"),
    "studioAssetId": ("user_assets", "name"),
}
_COLL_DISPLAY = {coll: disp for coll, disp in REF_MAP.values()}


async def _resolve_refs(db: AsyncIOMotorDatabase, docs: list) -> dict:
    """id-строка -> отображаемое имя для известных ссылочных полей (батчами по коллекциям)."""
    ids_by_coll: dict[str, set] = {}
    for doc in docs:
        for field, (coll, _) in REF_MAP.items():
            v = doc.get(field)
            if isinstance(v, ObjectId):
                oid = v
            elif isinstance(v, str) and ObjectId.is_valid(v):
                oid = ObjectId(v)
            else:
                continue
            ids_by_coll.setdefault(coll, set()).add(oid)
    out: dict[str, str] = {}
    for coll, ids in ids_by_coll.items():
        disp = _COLL_DISPLAY[coll]
        async for d in db[coll].find({"_id": {"$in": list(ids)}}, {disp: 1}):
            name = d.get(disp)
            if name is not None:
                out[str(d["_id"])] = name
    return out


def _to_json(doc) -> dict:
    """BSON doc -> JSON-safe dict через Extended JSON (ObjectId -> {"$oid": ...}, datetime -> {"$date": ...}).

    Возвращаем строковую форму Extended JSON (json.loads, не json_util.loads):
    FastAPI сериализует результат напрямую, а bare ObjectId он сериализовать не умеет.
    Фронтенд уже читает _id как doc._id?.$oid || doc._id.
    """
    return json.loads(json_util.dumps(doc))


def _strip_id(payload: dict) -> dict:
    payload = dict(payload)
    payload.pop("_id", None)
    return payload


def _filter_for(doc_id: str) -> dict:
    return {"_id": ObjectId(doc_id) if ObjectId.is_valid(doc_id) else doc_id}


@router.get("/collections")
async def list_collections(
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    return sorted(await db.list_collection_names())


@router.get("/collections/{name}")
async def list_documents(
    name: str,
    q: str = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=LIST_LIMIT_CAP),
    sort: str = Query(None),
    order: int = Query(-1),
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    coll = db[name]
    query: dict = {}
    if q:
        sample = await coll.find_one({})
        escaped = re.escape(q)
        clauses = []
        for k, v in (sample or {}).items():
            if isinstance(v, str):
                clauses.append({k: {"$regex": escaped, "$options": "i"}})
            elif isinstance(v, datetime):
                # Даты хранятся как BSON datetime — строковый префикс ("2026-07-")
                # не матчит их regex'ом. Приводим к строке в агрегации и матчим.
                clauses.append({"$expr": {"$regexMatch": {
                    "input": {"$cond": [
                        {"$eq": [{"$type": f"${k}"}, "date"]},
                        {"$dateToString": {"date": f"${k}", "format": "%Y-%m-%d %H:%M:%S"}},
                        "",
                    ]},
                    "regex": escaped, "options": "i",
                }}})
        if clauses:
            query = {"$or": clauses}
    # Точный count_documents(query) на 900k делает полный скан (regex/$expr не
    # индексируются) — это главный источник тормозов. Считаем total только для
    # пустого фильтра (быстрая оценка); при поиске обходимся флагом has_more.
    total = None if query else await coll.estimated_document_count()
    cursor = coll.find(query)
    if sort:
        # sort без индекса на большой выборке упирается в лимит памяти (32МБ) и
        # падает — разрешаем досортировку на диске.
        cursor = cursor.sort(sort, 1 if order >= 0 else -1).allow_disk_use(True)
    # maxTimeMS: лучше быстрая ошибка, чем зависший на минуту запрос.
    cursor = cursor.max_time_ms(20000)
    # Берём на 1 больше лимита — так узнаём про следующую страницу без count.
    raw = [doc async for doc in cursor.skip(skip).limit(limit + 1)]
    has_more = len(raw) > limit
    raw = raw[:limit]
    refs = await _resolve_refs(db, raw)
    items = [_to_json(doc) for doc in raw]
    return {"items": items, "total": total, "has_more": has_more, "refs": refs}


@router.get("/collections/{name}/{doc_id}")
async def get_document(
    name: str,
    doc_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db[name].find_one(_filter_for(doc_id))
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    return _to_json(doc)


@router.post("/collections/{name}", status_code=status.HTTP_201_CREATED)
async def create_document(
    name: str,
    request: Request,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    body = json_util.loads(await request.body())
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Тело должно быть JSON-объектом")
    result = await db[name].insert_one(_strip_id(body))
    return await get_document(name, str(result.inserted_id), _admin=_admin, db=db)


@router.patch("/collections/{name}/{doc_id}")
async def update_document(
    name: str,
    doc_id: str,
    request: Request,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    body = json_util.loads(await request.body())
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Тело должно быть JSON-объектом")
    fields = _strip_id(body)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое тело запроса")
    result = await db[name].update_one(_filter_for(doc_id), {"$set": fields})
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    return await get_document(name, doc_id, _admin=_admin, db=db)


@router.delete("/collections/{name}/{doc_id}")
async def delete_document(
    name: str,
    doc_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    result = await db[name].delete_one(_filter_for(doc_id))
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    return {"deleted": True}


if __name__ == "__main__":
    from datetime import timezone

    # json_util round-trip сохраняет ObjectId и datetime как типы, не строки.
    doc = {"_id": ObjectId(), "created_at": datetime.now(timezone.utc), "name": "x"}
    restored = _to_json(doc)
    assert restored["_id"]["$oid"] == str(doc["_id"]), restored["_id"]
    assert "$date" in restored["created_at"], restored["created_at"]
    assert restored["name"] == "x"

    # _strip_id всегда убирает _id из тела PATCH/POST.
    stripped = _strip_id({"_id": "abc", "role": "admin"})
    assert "_id" not in stripped
    assert stripped["role"] == "admin"

    # REF_MAP и производный _COLL_DISPLAY согласованы.
    assert _COLL_DISPLAY["users"] == "username"
    assert REF_MAP["businessId"] == ("cityroof_businesses", "name")

    print("admin_db self-check OK")
