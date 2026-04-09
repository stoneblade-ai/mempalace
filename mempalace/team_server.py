"""Team server: FastAPI app with auth, CRUD, search, versioning, wings/taxonomy endpoints."""

import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from .config import sanitize_content, sanitize_name
from .knowledge_graph import KnowledgeGraph
from .team_auth import check_wing_permission, resolve_user
from .version import __version__

COLLECTION_NAME = "mempalace_team_drawers"


def _drawer_id(content: str) -> str:
    return "team_" + hashlib.sha256(content.encode()).hexdigest()[:24]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_users(config_path: str) -> dict:
    try:
        return json.loads(Path(config_path).read_text()).get("users", {})
    except (json.JSONDecodeError, OSError):
        return {}


def create_app(config_path: str, data_dir: str) -> FastAPI:
    """Create and return the FastAPI team server app."""
    app = FastAPI(title="MemPalace Team Server", version=__version__)

    # Setup KnowledgeGraph
    data_path = Path(data_dir)
    team_kg = KnowledgeGraph(db_path=str(data_path / "knowledge_graph.sqlite3"))

    # Setup ChromaDB
    import chromadb

    palace_dir = Path(data_dir) / "palace"
    palace_dir.mkdir(parents=True, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=str(palace_dir))
    collection = chroma_client.get_or_create_collection(COLLECTION_NAME)

    # WAL setup
    wal_dir = Path(data_dir) / "wal"
    wal_dir.mkdir(parents=True, exist_ok=True)
    wal_path = wal_dir / "write_log.jsonl"

    # Version tracking: drawer_id -> int (loaded from metadata on startup)
    version_map: dict[str, int] = {}

    # Load existing versions from ChromaDB on startup
    try:
        existing = collection.get(include=["metadatas"])
        for i, doc_id in enumerate(existing["ids"]):
            meta = existing["metadatas"][i] if existing["metadatas"] else {}
            version_map[doc_id] = int(meta.get("version", 1))
    except Exception:
        pass

    def _wal_append(entry: dict):
        try:
            with open(wal_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def _auth(api_key: str):
        """Resolve user by api_key, reloading config on each call."""
        users = _load_users(config_path)
        return resolve_user(api_key, users)

    def _require_auth(x_api_key):
        if not x_api_key:
            return None, JSONResponse(status_code=401, content={"error": "Missing X-API-Key"})
        user = _auth(x_api_key)
        if user is None:
            return None, JSONResponse(status_code=401, content={"error": "Invalid API key"})
        return user, None

    # ── Health ────────────────────────────────────────────────────────────────

    @app.get("/api/v1/health")
    async def health():
        return {"ok": True}

    # ── Status ────────────────────────────────────────────────────────────────

    @app.get("/api/v1/status")
    async def status(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
        user, err = _require_auth(x_api_key)
        if err:
            return err
        count = collection.count()
        return {"version": __version__, "drawer_count": count, "user": user.get("user_id")}

    # ── Create Drawer ─────────────────────────────────────────────────────────

    @app.post("/api/v1/drawers")
    async def create_drawer(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        body = await request.json()
        wing = body.get("wing", "")
        room = body.get("room", "")
        content = body.get("content", "")
        source_type = body.get("source_type", "direct")
        origin = body.get("origin") or {}

        # Validate inputs
        try:
            wing = sanitize_name(wing, "wing")
            room = sanitize_name(room, "room")
            content = sanitize_content(content)
        except ValueError as e:
            return JSONResponse(status_code=422, content={"error": str(e)})

        # Permission check
        if not check_wing_permission(user, wing, "write"):
            return JSONResponse(status_code=403, content={"error": f"Write permission denied for wing '{wing}'"})

        drawer_id = _drawer_id(content)
        now = _now_iso()
        metadata = {
            "wing": wing,
            "room": room,
            "published_by": user.get("user_id", "unknown"),
            "published_at": now,
            "source_type": source_type,
            "version": 1,
        }
        if origin:
            if "local_id" in origin:
                metadata["origin_local_id"] = origin["local_id"]
            if "user_id" in origin:
                metadata["origin_user_id"] = origin["user_id"]

        collection.upsert(
            ids=[drawer_id],
            documents=[content],
            metadatas=[metadata],
        )
        version_map[drawer_id] = 1

        from_ip = request.client.host if request.client else "unknown"
        _wal_append({
            "op": "create",
            "drawer_id": drawer_id,
            "user_id": user.get("user_id"),
            "from_ip": from_ip,
            "at": now,
        })

        return JSONResponse(status_code=201, content={"drawer_id": drawer_id, "version": 1})

    # ── Update Drawer ─────────────────────────────────────────────────────────

    @app.patch("/api/v1/drawers/{drawer_id}")
    async def update_drawer(
        drawer_id: str,
        request: Request,
        if_match: Optional[str] = Header(default=None, alias="If-Match"),
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        if if_match is None:
            return JSONResponse(status_code=428, content={"error": "If-Match header required"})

        current_version = version_map.get(drawer_id)
        if current_version is None:
            # Try to load from ChromaDB
            try:
                result = collection.get(ids=[drawer_id], include=["metadatas"])
                if result["ids"]:
                    current_version = int(result["metadatas"][0].get("version", 1))
                    version_map[drawer_id] = current_version
            except Exception:
                pass

        if current_version is None:
            return JSONResponse(status_code=404, content={"error": "Drawer not found"})

        try:
            client_version = int(if_match)
        except (ValueError, TypeError):
            return JSONResponse(status_code=400, content={"error": "Invalid If-Match value"})

        if client_version != current_version:
            return JSONResponse(status_code=409, content={"error": "Version conflict", "current_version": current_version})

        body = await request.json()
        new_content = body.get("content", "")

        try:
            new_content = sanitize_content(new_content)
        except ValueError as e:
            return JSONResponse(status_code=422, content={"error": str(e)})

        # Get existing metadata to preserve wing/room etc.
        try:
            result = collection.get(ids=[drawer_id], include=["metadatas"])
            existing_meta = result["metadatas"][0] if result["metadatas"] else {}
        except Exception:
            existing_meta = {}

        # Check write permission on wing
        wing = existing_meta.get("wing", "")
        if wing and not check_wing_permission(user, wing, "write"):
            return JSONResponse(status_code=403, content={"error": f"Write permission denied for wing '{wing}'"})

        new_version = current_version + 1
        now = _now_iso()
        new_meta = {**existing_meta, "version": new_version, "updated_at": now}

        collection.update(
            ids=[drawer_id],
            documents=[new_content],
            metadatas=[new_meta],
        )
        version_map[drawer_id] = new_version

        from_ip = request.client.host if request.client else "unknown"
        _wal_append({
            "op": "update",
            "drawer_id": drawer_id,
            "user_id": user.get("user_id"),
            "from_ip": from_ip,
            "at": now,
            "version": new_version,
        })

        return {"drawer_id": drawer_id, "version": new_version}

    # ── Delete Drawer ─────────────────────────────────────────────────────────

    @app.delete("/api/v1/drawers/{drawer_id}")
    async def delete_drawer(
        drawer_id: str,
        request: Request,
        if_match: Optional[str] = Header(default=None, alias="If-Match"),
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        if if_match is None:
            return JSONResponse(status_code=428, content={"error": "If-Match header required"})

        current_version = version_map.get(drawer_id)
        if current_version is None:
            try:
                result = collection.get(ids=[drawer_id], include=["metadatas"])
                if result["ids"]:
                    current_version = int(result["metadatas"][0].get("version", 1))
                    version_map[drawer_id] = current_version
            except Exception:
                pass

        if current_version is None:
            return JSONResponse(status_code=404, content={"error": "Drawer not found"})

        try:
            client_version = int(if_match)
        except (ValueError, TypeError):
            return JSONResponse(status_code=400, content={"error": "Invalid If-Match value"})

        if client_version != current_version:
            return JSONResponse(status_code=409, content={"error": "Version conflict", "current_version": current_version})

        # Permission: admin can delete any, member only own
        if user.get("role") != "admin":
            try:
                result = collection.get(ids=[drawer_id], include=["metadatas"])
                meta = result["metadatas"][0] if result["metadatas"] else {}
                if meta.get("published_by") != user.get("user_id"):
                    return JSONResponse(status_code=403, content={"error": "Only admin can delete other users' drawers"})
            except Exception:
                pass

        collection.delete(ids=[drawer_id])
        version_map.pop(drawer_id, None)

        now = _now_iso()
        from_ip = request.client.host if request.client else "unknown"
        _wal_append({
            "op": "delete",
            "drawer_id": drawer_id,
            "user_id": user.get("user_id"),
            "from_ip": from_ip,
            "at": now,
        })

        return {"drawer_id": drawer_id, "deleted": True}

    # ── Search ────────────────────────────────────────────────────────────────

    @app.post("/api/v1/search")
    async def search_drawers(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        body = await request.json()
        query = body.get("query", "")
        n_results = int(body.get("n_results", 10))
        filter_wing = body.get("wing")
        filter_room = body.get("room")

        if not query:
            return JSONResponse(status_code=422, content={"error": "query is required"})

        # Build ChromaDB where filter
        where = {}
        if filter_wing and filter_room:
            where = {"$and": [{"wing": {"$eq": filter_wing}}, {"room": {"$eq": filter_room}}]}
        elif filter_wing:
            where = {"wing": {"$eq": filter_wing}}
        elif filter_room:
            where = {"room": {"$eq": filter_room}}

        try:
            count = collection.count()
            if count == 0:
                return {"results": []}

            actual_n = min(n_results, count)
            kwargs = {"query_texts": [query], "n_results": actual_n, "include": ["documents", "metadatas", "distances"]}
            if where:
                kwargs["where"] = where

            results = collection.query(**kwargs)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"Search failed: {str(e)}"})

        output = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            wing = meta.get("wing", "")
            if wing and not check_wing_permission(user, wing, "read"):
                continue
            output.append({
                "drawer_id": doc_id,
                "content": docs[i] if i < len(docs) else "",
                "wing": wing,
                "room": meta.get("room", ""),
                "published_by": meta.get("published_by", ""),
                "published_at": meta.get("published_at", ""),
                "version": meta.get("version", 1),
                "distance": distances[i] if i < len(distances) else None,
            })

        return {"results": output}

    # ── List Drawers ──────────────────────────────────────────────────────────

    @app.get("/api/v1/drawers")
    async def list_drawers(
        request: Request,
        wing: Optional[str] = Query(default=None),
        room: Optional[str] = Query(default=None),
        published_by: Optional[str] = Query(default=None),
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        try:
            result = collection.get(include=["documents", "metadatas"])
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

        drawers = []
        for i, doc_id in enumerate(result["ids"]):
            meta = result["metadatas"][i] if result["metadatas"] else {}
            doc = result["documents"][i] if result["documents"] else ""
            w = meta.get("wing", "")

            # Permission filter
            if w and not check_wing_permission(user, w, "read"):
                continue

            # Query filters
            if wing and w != wing:
                continue
            if room and meta.get("room", "") != room:
                continue
            if published_by and meta.get("published_by", "") != published_by:
                continue

            drawers.append({
                "drawer_id": doc_id,
                "content": doc,
                "wing": w,
                "room": meta.get("room", ""),
                "published_by": meta.get("published_by", ""),
                "published_at": meta.get("published_at", ""),
                "version": meta.get("version", 1),
            })

        return {"drawers": drawers}

    # ── Get Single Drawer ─────────────────────────────────────────────────────

    @app.get("/api/v1/drawers/{drawer_id}")
    async def get_drawer(
        drawer_id: str,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        try:
            result = collection.get(ids=[drawer_id], include=["documents", "metadatas"])
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

        if not result["ids"]:
            return JSONResponse(status_code=404, content={"error": "Drawer not found"})

        meta = result["metadatas"][0] if result["metadatas"] else {}
        doc = result["documents"][0] if result["documents"] else ""
        wing = meta.get("wing", "")

        if wing and not check_wing_permission(user, wing, "read"):
            return JSONResponse(status_code=403, content={"error": f"Read permission denied for wing '{wing}'"})

        return {
            "drawer_id": drawer_id,
            "content": doc,
            "wing": wing,
            "room": meta.get("room", ""),
            "published_by": meta.get("published_by", ""),
            "published_at": meta.get("published_at", ""),
            "version": meta.get("version", 1),
        }

    # ── Wings ─────────────────────────────────────────────────────────────────

    @app.get("/api/v1/wings")
    async def list_wings(
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        try:
            result = collection.get(include=["metadatas"])
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

        wing_counts: dict[str, int] = defaultdict(int)
        for meta in (result["metadatas"] or []):
            w = meta.get("wing", "")
            if w and check_wing_permission(user, w, "read"):
                wing_counts[w] += 1

        return {"wings": dict(wing_counts)}

    # ── Wing Rooms ────────────────────────────────────────────────────────────

    @app.get("/api/v1/wings/{wing}/rooms")
    async def list_wing_rooms(
        wing: str,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        if not check_wing_permission(user, wing, "read"):
            return JSONResponse(status_code=403, content={"error": f"Read permission denied for wing '{wing}'"})

        try:
            result = collection.get(where={"wing": {"$eq": wing}}, include=["metadatas"])
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

        room_counts: dict[str, int] = defaultdict(int)
        for meta in (result["metadatas"] or []):
            r = meta.get("room", "")
            if r:
                room_counts[r] += 1

        return {"wing": wing, "rooms": dict(room_counts)}

    # ── Taxonomy ──────────────────────────────────────────────────────────────

    @app.get("/api/v1/taxonomy")
    async def taxonomy(
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        try:
            result = collection.get(include=["metadatas"])
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

        tree: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for meta in (result["metadatas"] or []):
            w = meta.get("wing", "")
            r = meta.get("room", "")
            if w and check_wing_permission(user, w, "read"):
                tree[w][r] += 1

        # Convert to plain dicts
        return {"taxonomy": {w: dict(rooms) for w, rooms in tree.items()}}

    # ── Knowledge Graph ───────────────────────────────────────────────────────

    @app.post("/api/v1/kg/query")
    async def kg_query(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        body = await request.json()
        entity = body.get("entity", "")
        as_of = body.get("as_of")
        direction = body.get("direction", "both")

        if not entity:
            return JSONResponse(status_code=422, content={"error": "entity is required"})

        facts = team_kg.query_entity(entity, as_of=as_of, direction=direction)
        return {"entity": entity, "facts": facts, "count": len(facts)}

    @app.post("/api/v1/kg/add")
    async def kg_add(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        body = await request.json()
        subject = body.get("subject", "")
        predicate = body.get("predicate", "")
        obj = body.get("object", "")
        valid_from = body.get("valid_from")
        source_closet = body.get("source_closet")

        try:
            subject = sanitize_name(subject, "subject")
            predicate = sanitize_name(predicate, "predicate")
            obj = sanitize_name(obj, "object")
        except ValueError as e:
            return JSONResponse(status_code=422, content={"error": str(e)})

        now = _now_iso()
        _wal_append({
            "op": "kg_add",
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "user_id": user.get("user_id"),
            "at": now,
        })

        triple_id = team_kg.add_triple(subject, predicate, obj, valid_from=valid_from, source_closet=source_closet)
        return {"success": True, "triple_id": triple_id}

    @app.post("/api/v1/kg/invalidate")
    async def kg_invalidate(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        body = await request.json()
        subject = body.get("subject", "")
        predicate = body.get("predicate", "")
        obj = body.get("object", "")
        ended = body.get("ended")

        now = _now_iso()
        _wal_append({
            "op": "kg_invalidate",
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "user_id": user.get("user_id"),
            "at": now,
        })

        team_kg.invalidate(subject, predicate, obj, ended=ended)
        return {"success": True}

    @app.get("/api/v1/kg/timeline/{entity}")
    async def kg_timeline(
        entity: str,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        user, err = _require_auth(x_api_key)
        if err:
            return err

        timeline = team_kg.timeline(entity_name=entity)
        return {"entity": entity, "timeline": timeline, "count": len(timeline)}

    return app
