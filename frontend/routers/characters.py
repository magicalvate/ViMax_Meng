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
    task_done, task_error, task_progress, load_style,
    get_model_label, _tasks,
    SCENE_REF_EXTS, _read_json, _write_json, load_portrait_refs,
)

logger = logging.getLogger("vimax.server")
router = APIRouter()


@router.post("/api/projects/{project}/characters/{char_idx}/portraits/regenerate")
async def regenerate_all_portraits(project: str, char_idx: int):
    """重新生成某角色的全部肖像（front → side → back）"""
    p = wd(project)
    if not (p / "characters.json").exists():
        raise HTTPException(404, "characters.json not found")
    pipeline = get_pipeline(project)
    tid = new_task()
    asyncio.create_task(_run_regenerate_all_portraits(tid, pipeline, p, char_idx))
    return {"task_id": tid}


async def _run_regenerate_all_portraits(tid: str, pipeline, p: Path, char_idx: int):
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
        style = load_style(p)
        model_label = get_model_label(pipeline.image_generator)

        Script2VideoPipeline.character_portrait_events = {}
        ev = asyncio.Event()
        Script2VideoPipeline.character_portrait_events[char_idx] = ev

        for view in ("front", "side", "back"):
            portrait_path = char_dir / f"{view}.png"
            if portrait_path.exists():
                add_portrait_version(char_dir, view, new_vid())

        task_progress(tid, "图像生成 API 调用中（正面）…")
        front_path = char_dir / "front.png"
        front_path.unlink(missing_ok=True)
        refs = load_portrait_refs(char_dir, p.name)
        ref_paths = [r["path"] for r in refs if r.get("path") and Path(r["path"]).exists()]
        output = await pipeline.character_portraits_generator.generate_front_portrait(char, style, ref_paths)
        output.save(str(front_path))
        add_portrait_version(char_dir, "front", new_vid(), model=model_label)

        task_progress(tid, "图像生成 API 调用中（侧面）…")
        side_path = char_dir / "side.png"
        side_path.unlink(missing_ok=True)
        output = await pipeline.character_portraits_generator.generate_side_portrait(char, str(front_path))
        output.save(str(side_path))
        add_portrait_version(char_dir, "side", new_vid(), model=model_label)

        task_progress(tid, "图像生成 API 调用中（背面）…")
        back_path = char_dir / "back.png"
        back_path.unlink(missing_ok=True)
        output = await pipeline.character_portraits_generator.generate_back_portrait(char, str(front_path))
        output.save(str(back_path))
        add_portrait_version(char_dir, "back", new_vid(), model=model_label)

        ev.set()
        task_done(tid)
    except Exception as e:
        logger.exception(f"Task {tid} failed")
        task_error(tid, str(e))


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


def _find_char_dir_with_version(p: Path, char_idx: int, view: str, vid: str):
    """Find the char dir that actually contains the requested version file."""
    portraits_dir = p / "character_portraits"
    if not portraits_dir.exists():
        return None, None
    for d in portraits_dir.iterdir():
        if d.is_dir() and d.name.startswith(f"{char_idx}_"):
            vf = d / "versions" / f"{view}_{vid}.png"
            if vf.exists():
                return d, vf
    return None, None


@router.post("/api/projects/{project}/characters/{char_idx}/portraits/{view}/versions/{vid}/select")
async def select_portrait_version(project: str, char_idx: int, view: str, vid: str):
    p = wd(project)
    char_dir, ver_file = _find_char_dir_with_version(p, char_idx, view, vid)
    if not char_dir:
        raise HTTPException(404, "Version file not found")
    shutil.copy2(str(ver_file), str(char_dir / f"{view}.png"))
    meta = load_portrait_versions(char_dir)
    for e in meta.get(view, []):
        e["selected"] = e["id"] == vid
    save_portrait_versions(char_dir, meta)
    result = {
        v: [{**e, "url": f"/files/{p.name}/character_portraits/{char_dir.name}/versions/{v}_{e['id']}.png"} for e in es]
        for v, es in meta.items()
    }
    return {"ok": True, "versions": result}


@router.delete("/api/projects/{project}/characters/{char_idx}/portraits/{view}/versions/{vid}")
async def delete_portrait_version(project: str, char_idx: int, view: str, vid: str):
    p = wd(project)
    char_dir, ver_file = _find_char_dir_with_version(p, char_idx, view, vid)
    if not char_dir:
        char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        raise HTTPException(404, "Character portrait directory not found")
    if ver_file:
        ver_file.unlink(missing_ok=True)
    else:
        (char_dir / "versions" / f"{view}_{vid}.png").unlink(missing_ok=True)

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
        model_label = get_model_label(pipeline.image_generator)

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
            refs = load_portrait_refs(char_dir, p.name)
            ref_paths = [r["path"] for r in refs if r.get("path") and Path(r["path"]).exists()]
            output = await pipeline.character_portraits_generator.generate_front_portrait(char, style, ref_paths)
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
        add_portrait_version(char_dir, view, vid, model=model_label)
        _tasks[tid]["new_vid"] = vid
        task_done(tid)
    except Exception as e:
        logger.exception(f"Task {tid} failed")
        task_error(tid, str(e))


# ── 人物参考图管理 ────────────────────────────────────────────────────────────

@router.get("/api/projects/{project}/characters/{char_idx}/portrait_refs")
async def get_portrait_refs(project: str, char_idx: int):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        return []
    return load_portrait_refs(char_dir, project)


@router.post("/api/projects/{project}/characters/{char_idx}/portrait_refs")
async def add_portrait_ref(project: str, char_idx: int, file: UploadFile):
    p = wd(project)
    char_dir = find_char_dir(p, char_idx)
    if not char_dir:
        chars_path = p / "characters.json"
        if not chars_path.exists():
            raise HTTPException(404, "characters.json not found")
        from interfaces import CharacterInScene
        characters = [CharacterInScene.model_validate(c) for c in json.loads(chars_path.read_text(encoding="utf-8"))]
        char = next((c for c in characters if c.idx == char_idx), None)
        if not char:
            raise HTTPException(404, f"Character idx={char_idx} not found")
        char_dir = p / "character_portraits" / f"{char_idx}_{char.identifier_in_scene}"
        char_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "ref.png").suffix.lower()
    if suffix not in SCENE_REF_EXTS:
        raise HTTPException(400, "Unsupported file type")

    refs_dir = char_dir / "portrait_refs"
    refs_dir.mkdir(exist_ok=True)
    stem = Path(file.filename or "ref").stem
    target = refs_dir / f"{stem}{suffix}"
    counter = 1
    while target.exists():
        target = refs_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    save_upload(file, target)

    refs_path = char_dir / "portrait_refs.json"
    data = _read_json(refs_path, [])
    data.append({"path": str(target), "description": ""})
    _write_json(refs_path, data)

    return {"ok": True, "filename": target.name}


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

    refs_path = char_dir / "portrait_refs.json"
    data = _read_json(refs_path, [])
    data = [item for item in data if Path(item.get("path", "")).name != filename]
    _write_json(refs_path, data)

    return {"ok": True}
