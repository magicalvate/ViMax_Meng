import asyncio
import json
import logging
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="ViMax Preview")
logger = logging.getLogger("vimax.server")

BASE_DIR = Path(__file__).parent.parent
WORKING_DIR = BASE_DIR / ".working_dir"
STATIC_DIR = Path(__file__).parent / "static"
CONFIGS_DIR = BASE_DIR / "configs"

SCENE_REF_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Config 发现 ──────────────────────────────────────────────────────────────

_config_cache: Dict[str, str] = {}  # project_name -> config_path


def find_config(project: str) -> Optional[str]:
    if project in _config_cache:
        return _config_cache[project]
    for yaml_file in CONFIGS_DIR.glob("*.yaml"):
        try:
            cfg = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            if Path(cfg.get("working_dir", "")).name == project:
                _config_cache[project] = str(yaml_file)
                return str(yaml_file)
        except Exception:
            pass
    return None


# ── Pipeline 缓存 ────────────────────────────────────────────────────────────

_pipeline_cache: Dict[str, Any] = {}  # project_name -> pipeline instance


def get_pipeline(project: str):
    if project not in _pipeline_cache:
        config_path = find_config(project)
        if not config_path:
            raise HTTPException(404, f"No config file found for project '{project}'")
        from pipelines.script2video_pipeline import Script2VideoPipeline
        _pipeline_cache[project] = Script2VideoPipeline.init_from_config(config_path)
        logger.info(f"Pipeline loaded for project '{project}' using config '{config_path}'")
    return _pipeline_cache[project]


# ── Task 系统 ────────────────────────────────────────────────────────────────

_tasks: Dict[str, Dict] = {}  # task_id -> {status, error_msg}


def _new_task() -> str:
    tid = str(uuid.uuid4())
    _tasks[tid] = {"status": "running", "error_msg": None}
    return tid


def _task_done(tid: str):
    _tasks[tid]["status"] = "done"


def _task_error(tid: str, msg: str):
    _tasks[tid]["status"] = "error"
    _tasks[tid]["error_msg"] = msg


# ── Frame events 工具 ────────────────────────────────────────────────────────

def _setup_frame_events(pipeline, wd: Path, target_shot_idx: int, target_frame_type: str):
    """为 generate_frame_for_single_shot 预初始化所有 frame_events。
    目标帧的 event 保持 unset；其他已存在的帧 event 置为 set。"""
    from pipelines.script2video_pipeline import Script2VideoPipeline
    Script2VideoPipeline.frame_events = {}  # 清空类级别状态
    shots_dir = wd / "shots"
    for d in sorted(shots_dir.iterdir()):
        if not d.is_dir():
            continue
        idx = int(d.name)
        events = {}
        for ft in ("first_frame", "last_frame"):
            ev = asyncio.Event()
            # 目标帧保持 unset（让方法正常写入后 set）
            if not (idx == target_shot_idx and ft == target_frame_type):
                if (d / f"{ft}.png").exists():
                    ev.set()
            events[ft] = ev
        Script2VideoPipeline.frame_events[idx] = events


def _preset_all_frame_events(pipeline, wd: Path):
    """为 generate_video_for_single_shot 预初始化：所有已有帧的 event 都置为 set。"""
    from pipelines.script2video_pipeline import Script2VideoPipeline
    Script2VideoPipeline.frame_events = {}
    shots_dir = wd / "shots"
    for d in sorted(shots_dir.iterdir()):
        if not d.is_dir():
            continue
        idx = int(d.name)
        events = {}
        for ft in ("first_frame", "last_frame"):
            ev = asyncio.Event()
            if (d / f"{ft}.png").exists():
                ev.set()
            events[ft] = ev
        Script2VideoPipeline.frame_events[idx] = events


def _get_first_shot_ff_pair(wd: Path, shot_idx: int):
    """找到该 shot 所属 camera 的第一个 shot 的首帧路径和描述，用作 reference pair。"""
    camera_tree_path = wd / "camera_tree.json"
    if camera_tree_path.exists():
        cameras = json.loads(camera_tree_path.read_text(encoding="utf-8"))
        for cam in cameras:
            if shot_idx in cam.get("active_shot_idxs", []):
                first_idx = cam["active_shot_idxs"][0]
                ff_path = str(wd / "shots" / str(first_idx) / "first_frame.png")
                desc_path = wd / "shots" / str(first_idx) / "shot_description.json"
                ff_desc = ""
                if desc_path.exists():
                    ff_desc = json.loads(desc_path.read_text(encoding="utf-8")).get("ff_desc", "")
                return (ff_path, ff_desc)
    # fallback：使用自身
    ff_path = str(wd / "shots" / str(shot_idx) / "first_frame.png")
    desc_path = wd / "shots" / str(shot_idx) / "shot_description.json"
    ff_desc = json.loads(desc_path.read_text(encoding="utf-8")).get("ff_desc", "") if desc_path.exists() else ""
    return (ff_path, ff_desc)


def _load_style(wd: Path) -> str:
    meta_path = wd / "metadata.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8")).get("style", "")
    return ""


# ── 静态页面 ─────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ── 项目列表 ─────────────────────────────────────────────────────────────────

@app.get("/api/projects")
async def list_projects():
    if not WORKING_DIR.exists():
        return []
    return sorted(d.name for d in WORKING_DIR.iterdir() if d.is_dir() and not d.name.startswith("."))


# ── 项目数据 ─────────────────────────────────────────────────────────────────

@app.get("/api/projects/{project}/data")
async def get_project_data(project: str):
    wd = _wd(project)

    def load(p: Path):
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    characters = load(wd / "characters.json") or []
    portraits_registry = load(wd / "character_portraits_registry.json") or {}
    storyboard = load(wd / "storyboard.json") or []
    camera_tree = load(wd / "camera_tree.json") or []
    metadata = load(wd / "metadata.json") or {}

    shots = []
    shots_dir = wd / "shots"
    if shots_dir.exists():
        for shot_dir in sorted(shots_dir.iterdir(), key=lambda d: int(d.name)):
            if not shot_dir.is_dir():
                continue
            idx = int(shot_dir.name)
            desc = load(shot_dir / "shot_description.json")
            scene_refs = []
            refs_dir = shot_dir / "scene_refs"
            if refs_dir.exists():
                for f in sorted(refs_dir.iterdir()):
                    if f.suffix.lower() in SCENE_REF_EXTS:
                        scene_refs.append({"filename": f.name, "path": f"shots/{idx}/scene_refs/{f.name}", "readonly": False})
            for f in sorted(shot_dir.glob("new_camera_*.png")):
                scene_refs.append({"filename": f.name, "path": f"shots/{idx}/{f.name}", "readonly": True})
            shots.append({
                "idx": idx,
                "description": desc,
                "has_first_frame": (shot_dir / "first_frame.png").exists(),
                "has_last_frame": (shot_dir / "last_frame.png").exists(),
                "has_video": (shot_dir / "video.mp4").exists(),
                "scene_refs": scene_refs,
            })

    return {
        "characters": characters,
        "portraits_registry": portraits_registry,
        "storyboard": storyboard,
        "camera_tree": camera_tree,
        "shots": shots,
        "has_final_video": (wd / "final_video.mp4").exists(),
        "metadata": metadata,
    }


# ── 文件代理 ─────────────────────────────────────────────────────────────────

@app.get("/files/{project}/{path:path}")
async def serve_file(project: str, path: str):
    wd = _wd(project)
    file_path = wd / path
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    media_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(str(file_path), media_type=media_type or "application/octet-stream")


# ── 替换角色肖像（手动上传） ─────────────────────────────────────────────────

@app.post("/api/projects/{project}/characters/{char_idx}/portraits/{view}")
async def replace_portrait(project: str, char_idx: int, view: str, file: UploadFile):
    if view not in ("front", "side", "back"):
        raise HTTPException(400, "view must be front/side/back")
    wd = _wd(project)
    portraits_dir = wd / "character_portraits"
    target_dir = next((d for d in portraits_dir.iterdir() if d.is_dir() and d.name.startswith(f"{char_idx}_")), None)
    if not target_dir:
        raise HTTPException(404, "Character portrait directory not found")
    _save_upload(file, target_dir / f"{view}.png")
    return {"ok": True}


# ── 替换首帧/末帧（手动上传） ────────────────────────────────────────────────

@app.post("/api/projects/{project}/shots/{shot_idx}/frames/{frame_type}")
async def replace_frame(project: str, shot_idx: int, frame_type: str, file: UploadFile):
    if frame_type not in ("first", "last"):
        raise HTTPException(400, "frame_type must be first/last")
    wd = _wd(project)
    shot_dir = wd / "shots" / str(shot_idx)
    if not shot_dir.exists():
        raise HTTPException(404, "Shot directory not found")
    _save_upload(file, shot_dir / f"{frame_type}_frame.png")
    return {"ok": True}


# ── 参考场景：上传 / 删除 ────────────────────────────────────────────────────

@app.post("/api/projects/{project}/shots/{shot_idx}/scene_refs")
async def add_scene_ref(project: str, shot_idx: int, file: UploadFile):
    wd = _wd(project)
    shot_dir = wd / "shots" / str(shot_idx)
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
    _save_upload(file, target)
    return {"ok": True, "filename": target.name, "path": f"shots/{shot_idx}/scene_refs/{target.name}"}


@app.delete("/api/projects/{project}/shots/{shot_idx}/scene_refs/{filename}")
async def delete_scene_ref(project: str, shot_idx: int, filename: str):
    if filename.startswith("new_camera_"):
        raise HTTPException(403, "Auto-generated new_camera files cannot be deleted")
    wd = _wd(project)
    target = wd / "shots" / str(shot_idx) / "scene_refs" / filename
    if not target.exists():
        raise HTTPException(404, "File not found")
    target.unlink()
    return {"ok": True}


# ── 编辑 shot 描述 ────────────────────────────────────────────────────────────

@app.patch("/api/projects/{project}/shots/{shot_idx}/description")
async def update_shot_description(project: str, shot_idx: int, request: Request):
    wd = _wd(project)
    desc_path = wd / "shots" / str(shot_idx) / "shot_description.json"
    if not desc_path.exists():
        raise HTTPException(404, "shot_description.json not found")
    desc = json.loads(desc_path.read_text(encoding="utf-8"))
    body = await request.json()
    editable = ("ff_desc", "lf_desc", "motion_desc", "audio_desc", "visual_desc")
    for key in editable:
        if key in body:
            desc[key] = body[key]
    desc_path.write_text(json.dumps(desc, ensure_ascii=False, indent=2), encoding="utf-8")
    return desc


# ── 脚本文件列表 ─────────────────────────────────────────────────────────────

@app.get("/api/projects/{project}/scripts")
async def list_scripts(project: str):
    wd = _wd(project)
    meta_path = wd / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return meta.get("script_files", [])


@app.post("/api/projects/{project}/scripts")
async def add_script(project: str, request: Request):
    wd = _wd(project)
    body = await request.json()
    path = body.get("path", "").strip()
    if not path or not Path(path).exists():
        raise HTTPException(400, f"File not found: {path}")
    meta_path = wd / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    files = meta.setdefault("script_files", [])
    if path not in files:
        files.append(path)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "script_files": files}


@app.delete("/api/projects/{project}/scripts")
async def remove_script(project: str, request: Request):
    wd = _wd(project)
    body = await request.json()
    path = body.get("path", "")
    meta_path = wd / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    files = meta.get("script_files", [])
    meta["script_files"] = [f for f in files if f != path]
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


@app.get("/api/scripts/parse")
async def parse_script(path: str):
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, f"File not found: {path}")
    suffix = p.suffix.lower()
    if suffix == ".docx":
        return _parse_docx(p)
    elif suffix in (".txt", ".md"):
        return {"type": "text", "filename": p.name, "content": p.read_text(encoding="utf-8")}
    else:
        raise HTTPException(400, f"Unsupported file type: {suffix}")


def _parse_docx(p: Path) -> Dict:
    import docx as _docx
    doc = _docx.Document(str(p))

    # 标题段落
    title = ""
    for para in doc.paragraphs:
        if para.text.strip():
            title = para.text.strip()
            break

    # 解析表格（取第一个表格）
    tables = []
    for tbl in doc.tables:
        rows = []
        for i, row in enumerate(tbl.rows):
            cells = [cell.text.strip() for cell in row.cells]
            rows.append({"is_header": i == 0, "cells": cells})
        tables.append(rows)

    return {
        "type": "docx",
        "filename": p.name,
        "title": title,
        "tables": tables,
    }


# ── 保存 metadata（style 等） ─────────────────────────────────────────────────

@app.patch("/api/projects/{project}/metadata")
async def update_metadata(project: str, request: Request):
    wd = _wd(project)
    meta_path = wd / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    body = await request.json()
    meta.update(body)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


# ── Task 状态查询 ─────────────────────────────────────────────────────────────

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in _tasks:
        raise HTTPException(404, "Task not found")
    return _tasks[task_id]


# ── AI 重新生成：首帧/末帧 ───────────────────────────────────────────────────

@app.post("/api/projects/{project}/shots/{shot_idx}/regenerate/frame/{frame_type}")
async def regenerate_frame(project: str, shot_idx: int, frame_type: str):
    if frame_type not in ("first", "last"):
        raise HTTPException(400, "frame_type must be first/last")
    wd = _wd(project)
    desc_path = wd / "shots" / str(shot_idx) / "shot_description.json"
    if not desc_path.exists():
        raise HTTPException(404, "shot_description.json not found")

    pipeline = get_pipeline(project)
    tid = _new_task()

    asyncio.create_task(_run_regenerate_frame(tid, pipeline, wd, shot_idx, frame_type))
    return {"task_id": tid}


async def _run_regenerate_frame(tid: str, pipeline, wd: Path, shot_idx: int, frame_type: str):
    try:
        from interfaces import CharacterInScene, ShotDescription

        ft_key = f"{frame_type}_frame"  # "first_frame" or "last_frame"

        # 删除旧文件（强制重新生成）
        frame_path = wd / "shots" / str(shot_idx) / f"{ft_key}.png"
        selector_path = wd / "shots" / str(shot_idx) / f"{ft_key}_selector_output.json"
        frame_path.unlink(missing_ok=True)
        selector_path.unlink(missing_ok=True)

        # 加载上下文
        desc = ShotDescription.model_validate(
            json.loads((wd / "shots" / str(shot_idx) / "shot_description.json").read_text(encoding="utf-8"))
        )
        characters = [
            CharacterInScene.model_validate(c)
            for c in json.loads((wd / "characters.json").read_text(encoding="utf-8"))
        ]
        registry = json.loads((wd / "character_portraits_registry.json").read_text(encoding="utf-8"))

        vis_idxs = desc.ff_vis_char_idxs if frame_type == "first" else desc.lf_vis_char_idxs
        visible_chars = [c for c in characters if c.idx in vis_idxs]
        frame_desc = desc.ff_desc if frame_type == "first" else desc.lf_desc
        first_shot_ff_pair = _get_first_shot_ff_pair(wd, shot_idx)

        # 预初始化 frame_events
        _setup_frame_events(pipeline, wd, shot_idx, ft_key)

        await pipeline.generate_frame_for_single_shot(
            shot_idx=shot_idx,
            frame_type=ft_key,
            first_shot_ff_path_and_text_pair=first_shot_ff_pair,
            frame_desc=frame_desc,
            visible_characters=visible_chars,
            character_portraits_registry=registry,
        )
        _task_done(tid)
    except Exception as e:
        logger.exception(f"Task {tid} failed")
        _task_error(tid, str(e))


# ── AI 重新生成：视频 ────────────────────────────────────────────────────────

@app.post("/api/projects/{project}/shots/{shot_idx}/regenerate/video")
async def regenerate_video(project: str, shot_idx: int):
    wd = _wd(project)
    desc_path = wd / "shots" / str(shot_idx) / "shot_description.json"
    if not desc_path.exists():
        raise HTTPException(404, "shot_description.json not found")

    pipeline = get_pipeline(project)
    tid = _new_task()
    asyncio.create_task(_run_regenerate_video(tid, pipeline, wd, shot_idx))
    return {"task_id": tid}


async def _run_regenerate_video(tid: str, pipeline, wd: Path, shot_idx: int):
    try:
        from interfaces import ShotDescription
        from tools.protocols import VideoRAIFilteredError

        video_path = wd / "shots" / str(shot_idx) / "video.mp4"
        video_path.unlink(missing_ok=True)

        desc = ShotDescription.model_validate(
            json.loads((wd / "shots" / str(shot_idx) / "shot_description.json").read_text(encoding="utf-8"))
        )

        # 只把磁盘上实际存在的帧传入，空列表 → 文生视频（t2v）
        frame_paths = []
        ff = wd / "shots" / str(shot_idx) / "first_frame.png"
        lf = wd / "shots" / str(shot_idx) / "last_frame.png"
        if ff.exists():
            frame_paths.append(str(ff))
        if lf.exists() and desc.variation_type in ("medium", "large"):
            frame_paths.append(str(lf))

        mode = {0: "t2v", 1: "首帧→视频", 2: "首尾帧→视频"}[len(frame_paths)]
        logger.info(f"Shot {shot_idx} video regeneration: {mode}")

        try:
            video_output = await pipeline.video_generator.generate_single_video(
                prompt=desc.motion_desc + "\n" + desc.audio_desc,
                reference_image_paths=frame_paths,
            )
        except VideoRAIFilteredError:
            logger.warning(f"Shot {shot_idx}: audio_desc filtered by RAI, retrying with motion_desc only")
            video_output = await pipeline.video_generator.generate_single_video(
                prompt=desc.motion_desc,
                reference_image_paths=frame_paths,
            )

        video_output.save(str(video_path))
        _task_done(tid)
    except Exception as e:
        logger.exception(f"Task {tid} failed")
        _task_error(tid, str(e))


# ── AI 重新生成：角色肖像 ────────────────────────────────────────────────────

@app.post("/api/projects/{project}/characters/{char_idx}/portraits/{view}/regenerate")
async def regenerate_portrait(project: str, char_idx: int, view: str):
    if view not in ("front", "side", "back"):
        raise HTTPException(400, "view must be front/side/back")
    wd = _wd(project)
    chars_path = wd / "characters.json"
    if not chars_path.exists():
        raise HTTPException(404, "characters.json not found")

    pipeline = get_pipeline(project)
    tid = _new_task()
    asyncio.create_task(_run_regenerate_portrait(tid, pipeline, wd, char_idx, view))
    return {"task_id": tid}


async def _run_regenerate_portrait(tid: str, pipeline, wd: Path, char_idx: int, view: str):
    try:
        from interfaces import CharacterInScene
        from pipelines.script2video_pipeline import Script2VideoPipeline

        characters = [
            CharacterInScene.model_validate(c)
            for c in json.loads((wd / "characters.json").read_text(encoding="utf-8"))
        ]
        char = next((c for c in characters if c.idx == char_idx), None)
        if not char:
            raise ValueError(f"Character idx={char_idx} not found")

        char_dir = wd / "character_portraits" / f"{char_idx}_{char.identifier_in_scene}"
        front_path = char_dir / "front.png"
        style = _load_style(wd)

        # 预初始化 character_portrait_events
        Script2VideoPipeline.character_portrait_events = {}
        ev = asyncio.Event()
        Script2VideoPipeline.character_portrait_events[char_idx] = ev

        if view == "front":
            front_path.unlink(missing_ok=True)
            output = await pipeline.character_portraits_generator.generate_front_portrait(char, style)
            output.save(str(front_path))

        elif view == "side":
            if not front_path.exists():
                raise ValueError("front portrait must exist to regenerate side portrait")
            side_path = char_dir / "side.png"
            side_path.unlink(missing_ok=True)
            output = await pipeline.character_portraits_generator.generate_side_portrait(char, str(front_path))
            output.save(str(side_path))

        elif view == "back":
            if not front_path.exists():
                raise ValueError("front portrait must exist to regenerate back portrait")
            back_path = char_dir / "back.png"
            back_path.unlink(missing_ok=True)
            output = await pipeline.character_portraits_generator.generate_back_portrait(char, str(front_path))
            output.save(str(back_path))

        ev.set()
        _task_done(tid)
    except Exception as e:
        logger.exception(f"Task {tid} failed")
        _task_error(tid, str(e))


# ── 内部工具 ─────────────────────────────────────────────────────────────────

def _wd(project: str) -> Path:
    wd = WORKING_DIR / project
    if not wd.exists():
        raise HTTPException(404, f"Project '{project}' not found")
    return wd


def _save_upload(file: UploadFile, target_path: Path):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
