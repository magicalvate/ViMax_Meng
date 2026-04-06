import asyncio
import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from frontend.core import (
    wd, save_upload, get_pipeline, find_char_dir,
    load_portrait_versions, save_portrait_versions,
    add_portrait_version, new_task, new_vid,
    task_done, task_error, task_progress, load_style, _tasks,
)

logger = logging.getLogger("vimax.server")
router = APIRouter()


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
async def regenerate_portrait(project: str, char_idx: int, view: str):
    if view not in ("front", "side", "back"):
        raise HTTPException(400, "view must be front/side/back")
    p = wd(project)
    if not (p / "characters.json").exists():
        raise HTTPException(404, "characters.json not found")
    pipeline = get_pipeline(project)
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
