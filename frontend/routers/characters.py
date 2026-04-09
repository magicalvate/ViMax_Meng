import asyncio
import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile

from frontend.core import (
    wd, save_upload, get_pipeline, get_pipeline_for_task, find_char_dir, SCENE_REF_EXTS,
    load_portrait_versions, save_portrait_versions,
    add_portrait_version, new_task, new_vid,
    task_done, task_error, task_progress, load_style, _tasks,
    load_portrait_refs, load_portrait_ref_state, save_portrait_ref_state,
    load_portrait_bundle_versions, save_portrait_bundle_versions, add_portrait_bundle_version,
)

logger = logging.getLogger("vimax.server")
router = APIRouter()


# ⚠️ 必须在 `/{view}` 路由之前注册，否则 Starlette 会把 "regenerate_all" 当作 {view} 匹配 replace_portrait
@router.post("/api/projects/{project}/characters/{char_idx}/portraits/regenerate_all")
async def regenerate_portrait_all(project: str, char_idx: int, request: Request):
    p = wd(project)
    if not (p / "characters.json").exists():
        raise HTTPException(404, "characters.json not found")
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    model_override = body.get("model_override") or None
    pipeline = get_pipeline_for_task(project, model_override)
    tid = new_task()
    asyncio.create_task(_run_regenerate_portrait_all(tid, pipeline, p, char_idx))
    return {"task_id": tid}


@router.post("/api/projects/{project}/characters/{char_idx}/portraits/{view}")
async def replace_portrait(project: str, char_idx: int, view: str, file: UploadFile):
    if view not in ("front", "side", "back"):
        raise HTTPException(400, "view must be front/side/back")
    p = wd(project)
    portraits_dir = p / "character_portraits"
    target_dir = next((d for d in portraits_dir.iterdir() if d.is_dir() and d.name.startswith(f"{char_idx}_")), None)
    if not target_dir:
        raise HTTPException(404, "Character portrait directory not found")
    save_upload(file, target_dir / f"{view}.png")
    return {"ok": True}


@router.get("/api/projects/{project}/characters/{char_idx}/portraits/versions")
async def get_portrait_versions_all(project: str, char_idx: int):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    meta = load_portrait_versions(char_dir)
    result = {}
    for view, entries in meta.items():
        result[view] = [
            {**e, "url": f"/files/{project}/character_portraits/{char_dir.name}/versions/{view}_{e['id']}.png"}
            for e in entries
        ]
    return result


@router.post("/api/projects/{project}/characters/{char_idx}/portraits/{view}/versions/{vid}/select")
async def select_portrait_version(project: str, char_idx: int, view: str, vid: str):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    ver_file = char_dir / "versions" / f"{view}_{vid}.png"
    if not ver_file.exists():
        raise HTTPException(404, "Version file not found")
    shutil.copy2(str(ver_file), str(char_dir / f"{view}.png"))
    meta = load_portrait_versions(char_dir)
    for e in meta.get(view, []):
        e["selected"] = e["id"] == vid
    save_portrait_versions(char_dir, meta)
    return {"ok": True}


@router.delete("/api/projects/{project}/characters/{char_idx}/portraits/{view}/versions/{vid}")
async def delete_portrait_version(project: str, char_idx: int, view: str, vid: str):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    ver_file = char_dir / "versions" / f"{view}_{vid}.png"
    ver_file.unlink(missing_ok=True)

    meta = load_portrait_versions(char_dir)
    entries = meta.get(view, [])
    was_selected = any(e["id"] == vid and e["selected"] for e in entries)
    meta[view] = [e for e in entries if e["id"] != vid]

    if was_selected:
        if meta[view]:
            meta[view][-1]["selected"] = True
            last_id = meta[view][-1]["id"]
            shutil.copy2(
                str(char_dir / "versions" / f"{view}_{last_id}.png"),
                str(char_dir / f"{view}.png"),
            )
        else:
            (char_dir / f"{view}.png").unlink(missing_ok=True)

    save_portrait_versions(char_dir, meta)
    result = {}
    updated = load_portrait_versions(char_dir)
    for v, es in updated.items():
        result[v] = [
            {**e, "url": f"/files/{project}/character_portraits/{char_dir.name}/versions/{v}_{e['id']}.png"}
            for e in es
        ]
    return {"ok": True, "was_selected": was_selected, "versions": result}


@router.post("/api/projects/{project}/characters/{char_idx}/portraits/{view}/regenerate")
async def regenerate_portrait(project: str, char_idx: int, view: str, request: Request):
    if view not in ("front", "side", "back"):
        raise HTTPException(400, "view must be front/side/back")
    p = wd(project)
    if not (p / "characters.json").exists():
        raise HTTPException(404, "characters.json not found")
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    model_override = body.get("model_override") or None
    pipeline = get_pipeline_for_task(project, model_override)
    tid = new_task()
    asyncio.create_task(_run_regenerate_portrait(tid, pipeline, p, char_idx, view))
    return {"task_id": tid}


async def _run_regenerate_portrait(tid: str, pipeline, p: Path, char_idx: int, view: str):
    try:
        from interfaces import CharacterInScene
        from pipelines.script2video_pipeline import Script2VideoPipeline

        task_progress(tid, "加载角色信息…")
        characters = [
            CharacterInScene.model_validate(c)
            for c in json.loads((p / "characters.json").read_text(encoding="utf-8"))
        ]
        char = next((c for c in characters if c.idx == char_idx), None)
        if not char:
            raise ValueError(f"Character idx={char_idx} not found")

        char_dir = p / "character_portraits" / f"{char_idx}_{char.identifier_in_scene}"
        front_path = char_dir / "front.png"
        style = load_style(p)

        Script2VideoPipeline.character_portrait_events = {}
        ev = asyncio.Event()
        Script2VideoPipeline.character_portrait_events[char_idx] = ev

        portrait_path = char_dir / f"{view}.png"
        if portrait_path.exists():
            old_vid = new_vid()
            add_portrait_version(char_dir, view, old_vid)
            _tasks[tid]["preview_url"] = (
                f"/files/{p.name}/character_portraits/{char_dir.name}/versions/{view}_{old_vid}.png"
            )

        if view == "front":
            task_progress(tid, "图像生成 API 调用中（正面肖像）…")
            front_path.unlink(missing_ok=True)
            output = await pipeline.character_portraits_generator.generate_front_portrait(char, style)
            output.save(str(front_path))
        elif view == "side":
            if not front_path.exists():
                raise ValueError("front portrait must exist to regenerate side portrait")
            task_progress(tid, "图像生成 API 调用中（侧面肖像）…")
            side_path = char_dir / "side.png"
            side_path.unlink(missing_ok=True)
            output = await pipeline.character_portraits_generator.generate_side_portrait(char, str(front_path))
            output.save(str(side_path))
        elif view == "back":
            if not front_path.exists():
                raise ValueError("front portrait must exist to regenerate back portrait")
            task_progress(tid, "图像生成 API 调用中（背面肖像）…")
            back_path = char_dir / "back.png"
            back_path.unlink(missing_ok=True)
            output = await pipeline.character_portraits_generator.generate_back_portrait(char, str(front_path))
            output.save(str(back_path))

        ev.set()
        vid = new_vid()
        add_portrait_version(char_dir, view, vid)
        _tasks[tid]["new_vid"] = vid
        task_done(tid)
    except Exception as e:
        logger.exception(f"Task {tid} failed")
        task_error(tid, str(e))


async def _run_regenerate_portrait_all(tid: str, pipeline, p: Path, char_idx: int):
    try:
        from interfaces import CharacterInScene
        from pipelines.script2video_pipeline import Script2VideoPipeline

        task_progress(tid, "加载角色信息…")
        characters = [
            CharacterInScene.model_validate(c)
            for c in json.loads((p / "characters.json").read_text(encoding="utf-8"))
        ]
        char = next((c for c in characters if c.idx == char_idx), None)
        if not char:
            raise ValueError(f"Character idx={char_idx} not found")

        char_dir = p / "character_portraits" / f"{char_idx}_{char.identifier_in_scene}"
        char_dir.mkdir(parents=True, exist_ok=True)
        front_path = char_dir / "front.png"
        style = load_style(p)

        Script2VideoPipeline.character_portrait_events = {}
        ev = asyncio.Event()
        Script2VideoPipeline.character_portrait_events[char_idx] = ev

        # front
        task_progress(tid, f"[{char.identifier_in_scene}] 生成正面肖像…")
        if front_path.exists():
            add_portrait_version(char_dir, "front", new_vid())
        front_path.unlink(missing_ok=True)
        output = await pipeline.character_portraits_generator.generate_front_portrait(char, style)
        output.save(str(front_path))
        add_portrait_version(char_dir, "front", new_vid())

        # side
        task_progress(tid, f"[{char.identifier_in_scene}] 生成侧面肖像…")
        side_path = char_dir / "side.png"
        if side_path.exists():
            add_portrait_version(char_dir, "side", new_vid())
        side_path.unlink(missing_ok=True)
        output = await pipeline.character_portraits_generator.generate_side_portrait(char, str(front_path))
        output.save(str(side_path))
        add_portrait_version(char_dir, "side", new_vid())

        # back
        task_progress(tid, f"[{char.identifier_in_scene}] 生成背面肖像…")
        back_path = char_dir / "back.png"
        if back_path.exists():
            add_portrait_version(char_dir, "back", new_vid())
        back_path.unlink(missing_ok=True)
        output = await pipeline.character_portraits_generator.generate_back_portrait(char, str(front_path))
        output.save(str(back_path))
        add_portrait_version(char_dir, "back", new_vid())

        ev.set()
        task_done(tid)
    except Exception as e:
        logger.exception(f"Task {tid} failed")
        task_error(tid, str(e))


# ── 参考图 CRUD ───────────────────────────────────────────────────────────────

@router.get("/api/projects/{project}/characters/{char_idx}/portrait_refs")
async def get_portrait_refs(project: str, char_idx: int):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    return load_portrait_refs(char_dir, project)


@router.post("/api/projects/{project}/characters/{char_idx}/portrait_refs")
async def add_portrait_ref(project: str, char_idx: int, file: UploadFile):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    suffix = Path(file.filename or "ref.png").suffix.lower()
    if suffix not in SCENE_REF_EXTS:
        raise HTTPException(400, "Unsupported file type")
    refs_dir = char_dir / "portrait_refs"
    refs_dir.mkdir(exist_ok=True)
    stem = Path(file.filename or "ref").stem
    target = refs_dir / f"{stem}{suffix}"
    counter = 1
    while target.exists():
        target = refs_dir / f"{stem}_{counter}{suffix}"; counter += 1
    save_upload(file, target)
    url = f"/files/{project}/character_portraits/{char_dir.name}/portrait_refs/{target.name}"
    return {"filename": target.name, "url": url, "enabled": True}


@router.patch("/api/projects/{project}/characters/{char_idx}/portrait_refs/{filename}/enabled")
async def toggle_portrait_ref_enabled(project: str, char_idx: int, filename: str, request: Request):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    body = await request.json()
    enabled = bool(body.get("enabled", True))
    disabled = load_portrait_ref_state(char_dir)
    if enabled:
        disabled.discard(filename)
    else:
        disabled.add(filename)
    save_portrait_ref_state(char_dir, disabled)
    return {"ok": True, "filename": filename, "enabled": enabled}


@router.delete("/api/projects/{project}/characters/{char_idx}/portrait_refs/{filename}")
async def delete_portrait_ref(project: str, char_idx: int, filename: str):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    target = char_dir / "portrait_refs" / filename
    if not target.exists():
        raise HTTPException(404, "File not found")
    target.unlink()
    disabled = load_portrait_ref_state(char_dir)
    disabled.discard(filename)
    save_portrait_ref_state(char_dir, disabled)
    return {"ok": True}


# ── Bundle 版本 CRUD ──────────────────────────────────────────────────────────

def _bundle_entries_with_urls(project: str, char_dir: Path, entries: list) -> list:
    return [
        {**e, "preview_url": f"/files/{project}/character_portraits/{char_dir.name}/versions/bundle_{e['id']}_front.png"}
        for e in entries
    ]


@router.post("/api/projects/{project}/characters/{char_idx}/portrait_bundle_versions")
async def save_portrait_bundle(project: str, char_idx: int):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    vid = new_vid()
    if not add_portrait_bundle_version(char_dir, vid):
        raise HTTPException(400, "No portrait views available to save")
    return _bundle_entries_with_urls(project, char_dir, load_portrait_bundle_versions(char_dir))


@router.post("/api/projects/{project}/characters/{char_idx}/portrait_bundle_versions/{vid}/select")
async def select_portrait_bundle(project: str, char_idx: int, vid: str):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    ver_dir = char_dir / "versions"
    bundle_files = {view: ver_dir / f"bundle_{vid}_{view}.png" for view in ("front", "side", "back")}
    if not any(f.exists() for f in bundle_files.values()):
        raise HTTPException(404, "Bundle version files not found")
    for view, bf in bundle_files.items():
        if bf.exists():
            shutil.copy2(str(bf), str(char_dir / f"{view}.png"))
    entries = load_portrait_bundle_versions(char_dir)
    for e in entries:
        e["selected"] = (e["id"] == vid)
    save_portrait_bundle_versions(char_dir, entries)
    return _bundle_entries_with_urls(project, char_dir, entries)


@router.put("/api/projects/{project}/characters/{char_idx}/portrait_bundle_versions/{vid}")
async def update_portrait_bundle(project: str, char_idx: int, vid: str):
    """用当前 front/side/back 覆盖已有快照文件。"""
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    entries = load_portrait_bundle_versions(char_dir)
    if not any(e["id"] == vid for e in entries):
        raise HTTPException(404, "Bundle version not found")
    ver_dir = char_dir / "versions"
    ver_dir.mkdir(exist_ok=True)
    has_any = False
    for view in ("front", "side", "back"):
        active = char_dir / f"{view}.png"
        if active.exists():
            shutil.copy2(str(active), str(ver_dir / f"bundle_{vid}_{view}.png"))
            has_any = True
    if not has_any:
        raise HTTPException(400, "No portrait views available")
    return _bundle_entries_with_urls(project, char_dir, entries)


@router.delete("/api/projects/{project}/characters/{char_idx}/portrait_bundle_versions/{vid}")
async def delete_portrait_bundle(project: str, char_idx: int, vid: str):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    entries = load_portrait_bundle_versions(char_dir)
    entry = next((e for e in entries if e["id"] == vid), None)
    was_selected = entry.get("selected", False) if entry else False
    ver_dir = char_dir / "versions"
    for view in ("front", "side", "back"):
        (ver_dir / f"bundle_{vid}_{view}.png").unlink(missing_ok=True)
    entries = [e for e in entries if e["id"] != vid]
    if was_selected and entries:
        entries[-1]["selected"] = True
        last_vid = entries[-1]["id"]
        for view in ("front", "side", "back"):
            f = ver_dir / f"bundle_{last_vid}_{view}.png"
            if f.exists():
                shutil.copy2(str(f), str(char_dir / f"{view}.png"))
    save_portrait_bundle_versions(char_dir, entries)
    return {"ok": True, "was_selected": was_selected, "entries": _bundle_entries_with_urls(project, char_dir, entries)}
