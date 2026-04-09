import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel

from frontend.core import (
    wd, save_upload, get_pipeline, get_pipeline_for_task, SCENE_REF_EXTS,
    load_frame_refs, load_ref_overrides, save_ref_overrides,
    is_frame_enabled, set_frame_enabled, frame_state_path,
    load_shot_versions, save_shot_versions, shot_version_urls,
    asset_ext, active_filename, add_shot_version,
    new_task, new_vid, task_done, task_error, task_progress,
    setup_frame_events, preset_all_frame_events, get_first_shot_ff_pair,
    get_model_label, _tasks,
)

logger = logging.getLogger("vimax.server")
router = APIRouter()


class DescriptionBody(BaseModel):
    ff_desc: Optional[str] = None
    lf_desc: Optional[str] = None
    motion_desc: Optional[str] = None
    audio_desc: Optional[str] = None
    visual_desc: Optional[str] = None
    ff_vis_char_idxs: Optional[list] = None
    lf_vis_char_idxs: Optional[list] = None


class EnabledBody(BaseModel):
    enabled: bool = True


class ToggleRefBody(BaseModel):
    path: str
    enabled: bool = True


# ── 替换帧（手动上传） ────────────────────────────────────────────────────────

@router.post("/api/projects/{project}/shots/{shot_idx}/frames/{frame_type}")
async def replace_frame(project: str, shot_idx: int, frame_type: str, file: UploadFile):
    if frame_type not in ("first", "last"):
        raise HTTPException(400, "frame_type must be first/last")
    p = wd(project)
    shot_dir = p / "shots" / str(shot_idx)
    if not shot_dir.exists():
        raise HTTPException(404, "Shot directory not found")
    save_upload(file, shot_dir / f"{frame_type}_frame.png")
    return {"ok": True}


# ── 参考场景 ─────────────────────────────────────────────────────────────────

@router.post("/api/projects/{project}/shots/{shot_idx}/scene_refs")
async def add_scene_ref(project: str, shot_idx: int, file: UploadFile):
    p = wd(project)
    shot_dir = p / "shots" / str(shot_idx)
    if not shot_dir.exists():
        raise HTTPException(404, "Shot directory not found")
    suffix = Path(file.filename or "upload.png").suffix.lower()
    if suffix not in SCENE_REF_EXTS:
        raise HTTPException(400, "Unsupported file type")
    refs_dir = shot_dir / "scene_refs"
    refs_dir.mkdir(exist_ok=True)
    stem = Path(file.filename or "scene").stem
    target = refs_dir / f"{stem}{suffix}"
    counter = 1
    while target.exists():
        target = refs_dir / f"{stem}_{counter}{suffix}"; counter += 1
    save_upload(file, target)
    return {"ok": True, "filename": target.name, "path": f"shots/{shot_idx}/scene_refs/{target.name}"}


@router.delete("/api/projects/{project}/shots/{shot_idx}/scene_refs/{filename}")
async def delete_scene_ref(project: str, shot_idx: int, filename: str):
    if filename.startswith("new_camera_"):
        raise HTTPException(403, "Auto-generated new_camera files cannot be deleted")
    p = wd(project)
    target = p / "shots" / str(shot_idx) / "scene_refs" / filename
    if not target.exists():
        raise HTTPException(404, "File not found")
    target.unlink()
    return {"ok": True}


# ── 描述编辑 ─────────────────────────────────────────────────────────────────

@router.patch("/api/projects/{project}/shots/{shot_idx}/description")
async def update_shot_description(project: str, shot_idx: int, body: DescriptionBody):
    p = wd(project)
    desc_path = p / "shots" / str(shot_idx) / "shot_description.json"
    if not desc_path.exists():
        raise HTTPException(404, "shot_description.json not found")
    desc = json.loads(desc_path.read_text(encoding="utf-8"))
    for key, value in body.model_dump(exclude_none=True).items():
        desc[key] = value
    desc_path.write_text(json.dumps(desc, ensure_ascii=False, indent=2), encoding="utf-8")
    return desc


# ── 帧启用/禁用 ───────────────────────────────────────────────────────────────

@router.patch("/api/projects/{project}/shots/{shot_idx}/frames/{frame_type}/enabled")
async def set_frame_enabled_ep(project: str, shot_idx: int, frame_type: str, body: EnabledBody):
    if frame_type not in ("first", "last"):
        raise HTTPException(400, "frame_type must be first/last")
    p = wd(project)
    shot_dir = p / "shots" / str(shot_idx)
    ft_key = f"{frame_type}_frame"
    if not (shot_dir / f"{ft_key}.png").exists():
        raise HTTPException(404, f"{ft_key}.png not found")
    set_frame_enabled(shot_dir, ft_key, body.enabled)
    return {"ok": True, "enabled": body.enabled}


@router.get("/api/projects/{project}/shots/{shot_idx}/frames/{frame_type}/refs")
async def get_frame_refs(project: str, shot_idx: int, frame_type: str):
    if frame_type not in ("first", "last"):
        raise HTTPException(400, "frame_type must be first/last")
    p = wd(project)
    shot_dir = p / "shots" / str(shot_idx)
    ft_key = f"{frame_type}_frame"
    return load_frame_refs(p, project, shot_dir, ft_key)


@router.patch("/api/projects/{project}/shots/{shot_idx}/frames/{frame_type}/refs")
async def toggle_frame_ref(project: str, shot_idx: int, frame_type: str, body: ToggleRefBody):
    if frame_type not in ("first", "last"):
        raise HTTPException(400, "frame_type must be first/last")
    p = wd(project)
    shot_dir = p / "shots" / str(shot_idx)
    ft_key = f"{frame_type}_frame"
    disabled = load_ref_overrides(shot_dir, ft_key)
    if body.enabled:
        disabled.discard(body.path)
    else:
        disabled.add(body.path)
    save_ref_overrides(shot_dir, ft_key, disabled)
    return {"ok": True, "path": body.path, "enabled": body.enabled}


@router.delete("/api/projects/{project}/shots/{shot_idx}/frames/{frame_type}")
async def delete_frame(project: str, shot_idx: int, frame_type: str):
    if frame_type not in ("first", "last"):
        raise HTTPException(400, "frame_type must be first/last")
    p = wd(project)
    shot_dir = p / "shots" / str(shot_idx)
    ft_key = f"{frame_type}_frame"

    (shot_dir / f"{ft_key}.png").unlink(missing_ok=True)

    ver_dir = shot_dir / "versions"
    if ver_dir.exists():
        for f in ver_dir.glob(f"{ft_key}_*.png"):
            f.unlink()

    meta = load_shot_versions(shot_dir)
    meta[ft_key] = []
    save_shot_versions(shot_dir, meta)
    state = {}
    fp = frame_state_path(shot_dir)
    if fp.exists():
        import json as _json
        state = _json.loads(fp.read_text(encoding="utf-8"))
    state.pop(ft_key, None)
    fp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


# ── 版本管理 ─────────────────────────────────────────────────────────────────

@router.get("/api/projects/{project}/shots/{shot_idx}/versions")
async def get_shot_versions(project: str, shot_idx: int):
    p = wd(project)
    shot_dir = p / "shots" / str(shot_idx)
    return shot_version_urls(project, shot_idx, shot_dir)


@router.post("/api/projects/{project}/shots/{shot_idx}/versions/{asset}/{vid}/select")
async def select_shot_version(project: str, shot_idx: int, asset: str, vid: str):
    p = wd(project)
    shot_dir = p / "shots" / str(shot_idx)
    ext = asset_ext(asset)
    ver_file = shot_dir / "versions" / f"{asset}_{vid}.{ext}"
    if not ver_file.exists():
        raise HTTPException(404, "Version file not found")
    shutil.copy2(str(ver_file), str(shot_dir / active_filename(asset)))
    meta = load_shot_versions(shot_dir)
    for e in meta.get(asset, []):
        e["selected"] = e["id"] == vid
    save_shot_versions(shot_dir, meta)
    return {"ok": True, "versions": shot_version_urls(project, shot_idx, shot_dir)}


@router.delete("/api/projects/{project}/shots/{shot_idx}/versions/{asset}/{vid}")
async def delete_shot_version(project: str, shot_idx: int, asset: str, vid: str):
    p = wd(project)
    shot_dir = p / "shots" / str(shot_idx)
    ext = asset_ext(asset)
    ver_file = shot_dir / "versions" / f"{asset}_{vid}.{ext}"
    ver_file.unlink(missing_ok=True)

    meta = load_shot_versions(shot_dir)
    entries = meta.get(asset, [])
    was_selected = any(e["id"] == vid and e["selected"] for e in entries)
    meta[asset] = [e for e in entries if e["id"] != vid]

    if was_selected:
        if meta[asset]:
            meta[asset][-1]["selected"] = True
            last_id = meta[asset][-1]["id"]
            shutil.copy2(
                str(shot_dir / "versions" / f"{asset}_{last_id}.{ext}"),
                str(shot_dir / active_filename(asset)),
            )
        else:
            (shot_dir / active_filename(asset)).unlink(missing_ok=True)

    save_shot_versions(shot_dir, meta)
    return {"ok": True, "was_selected": was_selected, "versions": shot_version_urls(project, shot_idx, shot_dir)}


# ── AI 重新生成：帧 ──────────────────────────────────────────────────────────

@router.post("/api/projects/{project}/shots/{shot_idx}/regenerate/frame/{frame_type}")
async def regenerate_frame(project: str, shot_idx: int, frame_type: str, request: Request):
    if frame_type not in ("first", "last"):
        raise HTTPException(400, "frame_type must be first/last")
    p = wd(project)
    if not (p / "shots" / str(shot_idx) / "shot_description.json").exists():
        raise HTTPException(404, "shot_description.json not found")
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    pipeline = get_pipeline_for_task(project, body.get("model_override") or None)
    tid = new_task()
    asyncio.create_task(_run_regenerate_frame(tid, pipeline, p, shot_idx, frame_type))
    return {"task_id": tid}


async def _run_regenerate_frame(tid: str, pipeline, p: Path, shot_idx: int, frame_type: str):
    try:
        from interfaces import CharacterInScene, ShotDescription

        ft_key = f"{frame_type}_frame"
        task_progress(tid, "归档旧版本…")
        shot_dir = p / "shots" / str(shot_idx)
        frame_path = shot_dir / f"{ft_key}.png"
        selector_path = shot_dir / f"{ft_key}_selector_output.json"

        old_vid = None
        if frame_path.exists():
            old_vid = new_vid()
            add_shot_version(shot_dir, ft_key, old_vid)
            _tasks[tid]["preview_url"] = (
                f"/files/{p.name}/shots/{shot_idx}/versions/{ft_key}_{old_vid}.png"
            )

        frame_path.unlink(missing_ok=True)
        selector_path.unlink(missing_ok=True)
        task_progress(tid, "加载上下文…")

        desc = ShotDescription.model_validate(
            json.loads((p / "shots" / str(shot_idx) / "shot_description.json").read_text(encoding="utf-8"))
        )
        characters = [
            CharacterInScene.model_validate(c)
            for c in json.loads((p / "characters.json").read_text(encoding="utf-8"))
        ]
        registry = json.loads((p / "character_portraits_registry.json").read_text(encoding="utf-8"))

        vis_idxs = desc.ff_vis_char_idxs if frame_type == "first" else desc.lf_vis_char_idxs
        visible_chars = [c for c in characters if c.idx in vis_idxs]
        frame_desc = desc.ff_desc if frame_type == "first" else desc.lf_desc
        first_shot_ff_pair = get_first_shot_ff_pair(p, shot_idx)

        ff_ref_path, ff_ref_text = first_shot_ff_pair
        if not Path(ff_ref_path).exists():
            archived = shot_dir / "versions" / f"{ft_key}_{old_vid}.png" if old_vid is not None else None
            if archived is not None and archived.exists():
                first_shot_ff_pair = (str(archived), ff_ref_text)
            else:
                first_shot_ff_pair = None

        task_progress(tid, "AI 筛选参考图 + 生成 Prompt…")
        setup_frame_events(pipeline, p, shot_idx, ft_key)

        task_progress(tid, "图像生成 API 调用中…")
        variation_hint = (
            "IMPORTANT: Generate a noticeably different visual composition compared to any previous version. "
            "Explore a different camera framing, lighting direction, character pose, or spatial arrangement "
            "while keeping the scene description accurate and character appearances consistent with the reference images."
        )
        excluded_ref_paths = list(load_ref_overrides(shot_dir, ft_key))
        await pipeline.generate_frame_for_single_shot(
            shot_idx=shot_idx,
            frame_type=ft_key,
            first_shot_ff_path_and_text_pair=first_shot_ff_pair,
            frame_desc=frame_desc,
            visible_characters=visible_chars,
            character_portraits_registry=registry,
            prompt_suffix=variation_hint,
            excluded_ref_paths=excluded_ref_paths,
        )
        task_progress(tid, "归档版本…")
        vid = new_vid()
        add_shot_version(p / "shots" / str(shot_idx), ft_key, vid,
                         model=get_model_label(pipeline.image_generator))
        set_frame_enabled(p / "shots" / str(shot_idx), ft_key, True)
        _tasks[tid]["new_vid"] = vid
        _tasks[tid]["enabled"] = True
        task_done(tid)
    except Exception as e:
        logger.exception(f"Task {tid} failed")
        task_error(tid, str(e))


# ── AI 重新生成：视频 ────────────────────────────────────────────────────────

@router.post("/api/projects/{project}/shots/{shot_idx}/regenerate/video")
async def regenerate_video(project: str, shot_idx: int, request: Request):
    p = wd(project)
    if not (p / "shots" / str(shot_idx) / "shot_description.json").exists():
        raise HTTPException(404, "shot_description.json not found")
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    pipeline = get_pipeline_for_task(project, body.get("model_override") or None)
    tid = new_task()
    asyncio.create_task(_run_regenerate_video(tid, pipeline, p, shot_idx))
    return {"task_id": tid}


async def _run_regenerate_video(tid: str, pipeline, p: Path, shot_idx: int):
    try:
        from interfaces import ShotDescription
        from tools.protocols import VideoRAIFilteredError

        task_progress(tid, "归档旧版本…")
        shot_dir = p / "shots" / str(shot_idx)
        video_path = shot_dir / "video.mp4"

        if video_path.exists():
            old_vid = new_vid()
            add_shot_version(shot_dir, "video", old_vid)
            _tasks[tid]["preview_url"] = (
                f"/files/{p.name}/shots/{shot_idx}/versions/video_{old_vid}.mp4"
            )

        video_path.unlink(missing_ok=True)
        task_progress(tid, "加载镜头描述…")

        desc = ShotDescription.model_validate(
            json.loads((p / "shots" / str(shot_idx) / "shot_description.json").read_text(encoding="utf-8"))
        )

        frame_paths = []
        ff = shot_dir / "first_frame.png"
        lf = shot_dir / "last_frame.png"
        if ff.exists() and is_frame_enabled(shot_dir, "first_frame"):
            frame_paths.append(str(ff))
        if lf.exists() and is_frame_enabled(shot_dir, "last_frame") and desc.variation_type in ("medium", "large"):
            frame_paths.append(str(lf))

        mode = {0: "文生视频", 1: "首帧→视频", 2: "首尾帧→视频"}[len(frame_paths)]
        task_progress(tid, f"视频生成 API 调用中（{mode}）…")

        try:
            video_output = await pipeline.video_generator.generate_single_video(
                prompt=desc.motion_desc + "\n" + desc.audio_desc,
                reference_image_paths=frame_paths,
            )
        except VideoRAIFilteredError:
            task_progress(tid, "RAI 过滤，仅用运动描述重试…")
            video_output = await pipeline.video_generator.generate_single_video(
                prompt=desc.motion_desc,
                reference_image_paths=frame_paths,
            )

        video_output.save(str(video_path))
        vid = new_vid()
        add_shot_version(p / "shots" / str(shot_idx), "video", vid,
                         model=get_model_label(pipeline.video_generator))
        _tasks[tid]["new_vid"] = vid
        task_done(tid)
    except Exception as e:
        logger.exception(f"Task {tid} failed")
        task_error(tid, str(e))
