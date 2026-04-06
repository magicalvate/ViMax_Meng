import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from frontend.core import (
    wd, get_pipeline, load_style, preset_all_frame_events,
    new_task, task_done, task_error, task_progress, WORKING_DIR,
)

logger = logging.getLogger("vimax.server")
router = APIRouter()


def _get_script(p: Path) -> str:
    meta_path = p / "metadata.json"
    if not meta_path.exists():
        return ""
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    files = meta.get("script_files", [])
    if not files:
        return ""
    sp = Path(files[0])
    if not sp.exists():
        return ""
    suffix = sp.suffix.lower()
    if suffix in (".txt", ".md"):
        return sp.read_text(encoding="utf-8")
    if suffix == ".docx":
        try:
            import docx as _docx
            doc = _docx.Document(str(sp))
            return "\n".join(para.text for para in doc.paragraphs)
        except Exception:
            return ""
    return ""


def _stages_status(p: Path) -> Dict:
    chars_path = p / "characters.json"
    registry_path = p / "character_portraits_registry.json"
    storyboard_path = p / "storyboard.json"
    camera_tree_path = p / "camera_tree.json"
    final_video_path = p / "final_video.mp4"

    chars: List = []
    if chars_path.exists():
        try:
            chars = json.loads(chars_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    portrait_count = 0
    if registry_path.exists():
        try:
            reg = json.loads(registry_path.read_text(encoding="utf-8"))
            portrait_count = sum(len(v) for v in reg.values())
        except Exception:
            pass

    storyboard: List = []
    if storyboard_path.exists():
        try:
            storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    storyboard_count = len(storyboard)

    shots_dir = p / "shots"
    shot_desc_count = shots_with_ff = shots_with_video = 0
    if shots_dir.exists():
        for d in shots_dir.iterdir():
            if d.is_dir():
                if (d / "shot_description.json").exists():
                    shot_desc_count += 1
                if (d / "first_frame.png").exists():
                    shots_with_ff += 1
                if (d / "video.mp4").exists():
                    shots_with_video += 1

    return {
        "extract_characters": {"done": chars_path.exists(), "count": len(chars)},
        "generate_portraits": {"done": registry_path.exists() and portrait_count > 0, "count": portrait_count},
        "design_storyboard": {"done": storyboard_path.exists() and storyboard_count > 0, "count": storyboard_count},
        "decompose_descriptions": {"done": storyboard_count > 0 and shot_desc_count == storyboard_count, "shots_done": shot_desc_count, "shots_total": storyboard_count},
        "construct_camera_tree": {"done": camera_tree_path.exists()},
        "generate_frames": {"done": storyboard_count > 0 and shots_with_ff == storyboard_count, "shots_done": shots_with_ff, "shots_total": storyboard_count},
        "generate_videos": {"done": storyboard_count > 0 and shots_with_video == storyboard_count, "shots_done": shots_with_video, "shots_total": storyboard_count},
        "concatenate": {"done": final_video_path.exists()},
    }


def _clear_stage_cache(p: Path, stage: str):
    shots_dir = p / "shots"
    if stage == "extract_characters":
        (p / "characters.json").unlink(missing_ok=True)
    elif stage == "generate_portraits":
        (p / "character_portraits_registry.json").unlink(missing_ok=True)
        portraits_dir = p / "character_portraits"
        if portraits_dir.exists():
            shutil.rmtree(str(portraits_dir))
    elif stage == "design_storyboard":
        (p / "storyboard.json").unlink(missing_ok=True)
    elif stage == "decompose_descriptions":
        if shots_dir.exists():
            for d in shots_dir.iterdir():
                if d.is_dir():
                    (d / "shot_description.json").unlink(missing_ok=True)
    elif stage == "construct_camera_tree":
        (p / "camera_tree.json").unlink(missing_ok=True)
    elif stage == "generate_frames":
        if shots_dir.exists():
            for d in shots_dir.iterdir():
                if d.is_dir():
                    for fname in (
                        "first_frame.png", "last_frame.png",
                        "first_frame_selector_output.json", "last_frame_selector_output.json",
                        "first_frame_ref_overrides.json", "last_frame_ref_overrides.json",
                    ):
                        (d / fname).unlink(missing_ok=True)
                    for f in d.glob("transition_video_from_shot_*.mp4"):
                        f.unlink()
                    for f in d.glob("new_camera_*.png"):
                        f.unlink()
    elif stage == "generate_videos":
        if shots_dir.exists():
            for d in shots_dir.iterdir():
                if d.is_dir():
                    (d / "video.mp4").unlink(missing_ok=True)
    elif stage == "concatenate":
        (p / "final_video.mp4").unlink(missing_ok=True)


_STAGE_PREREQUISITES: Dict[str, List[str]] = {
    "extract_characters":      [],
    "generate_portraits":      ["characters.json"],
    "design_storyboard":       ["characters.json"],
    "decompose_descriptions":  ["storyboard.json"],
    "construct_camera_tree":   [],
    "generate_frames":         ["camera_tree.json", "character_portraits_registry.json"],
    "generate_videos":         [],
    "concatenate":             [],
}


@router.get("/api/projects/{project}/stages/status")
async def get_stages_status(project: str):
    return _stages_status(wd(project))


@router.post("/api/projects/{project}/run/{stage}")
async def run_stage(project: str, stage: str, request: Request):
    valid_stages = set(_STAGE_PREREQUISITES.keys())
    if stage not in valid_stages:
        raise HTTPException(400, f"Unknown stage '{stage}'. Valid: {sorted(valid_stages)}")

    p = wd(project)
    body: Dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    force = bool(body.get("force", False))

    for prereq in _STAGE_PREREQUISITES[stage]:
        if not (p / prereq).exists():
            raise HTTPException(400, f"前置条件未满足：{prereq} 不存在，请先运行依赖阶段")

    storyboard_loaded: Optional[List] = None

    def _load_storyboard() -> List:
        nonlocal storyboard_loaded
        if storyboard_loaded is None:
            sp = p / "storyboard.json"
            if not sp.exists():
                raise HTTPException(400, "前置条件未满足：storyboard.json 不存在，请先运行 design_storyboard")
            storyboard_loaded = json.loads(sp.read_text(encoding="utf-8"))
        return storyboard_loaded

    if stage == "construct_camera_tree":
        for shot in _load_storyboard():
            if not (p / "shots" / str(shot["idx"]) / "shot_description.json").exists():
                raise HTTPException(400, f"前置条件未满足：shot {shot['idx']} 的 shot_description.json 不存在，请先运行 decompose_descriptions")
    elif stage == "generate_videos":
        for shot in _load_storyboard():
            if not (p / "shots" / str(shot["idx"]) / "first_frame.png").exists():
                raise HTTPException(400, f"前置条件未满足：shot {shot['idx']} 的 first_frame.png 不存在，请先运行 generate_frames")
    elif stage == "concatenate":
        for shot in _load_storyboard():
            if not (p / "shots" / str(shot["idx"]) / "video.mp4").exists():
                raise HTTPException(400, f"前置条件未满足：shot {shot['idx']} 的 video.mp4 不存在，请先运行 generate_videos")

    if force:
        _clear_stage_cache(p, stage)

    pipeline = get_pipeline(project)
    tid = new_task()
    asyncio.create_task(_run_stage_task(tid, pipeline, p, stage))
    return {"task_id": tid}


async def _run_stage_task(tid: str, pipeline, p: Path, stage: str):
    try:
        if stage == "extract_characters":
            await _stage_extract_characters(tid, pipeline, p)
        elif stage == "generate_portraits":
            await _stage_generate_portraits(tid, pipeline, p)
        elif stage == "design_storyboard":
            await _stage_design_storyboard(tid, pipeline, p)
        elif stage == "decompose_descriptions":
            await _stage_decompose_descriptions(tid, pipeline, p)
        elif stage == "construct_camera_tree":
            await _stage_construct_camera_tree(tid, pipeline, p)
        elif stage == "generate_frames":
            await _stage_generate_frames(tid, pipeline, p)
        elif stage == "generate_videos":
            await _stage_generate_videos(tid, pipeline, p)
        elif stage == "concatenate":
            await _stage_concatenate(tid, p)
        task_done(tid)
    except Exception as e:
        logger.exception(f"Stage task {tid} ({stage}) failed")
        task_error(tid, str(e))


async def _stage_extract_characters(tid: str, pipeline, p: Path):
    task_progress(tid, "读取脚本…")
    script = _get_script(p)
    if not script:
        raise ValueError("找不到脚本文件，请先在项目中添加脚本（scripts）")
    task_progress(tid, "LLM 提取角色中…")
    characters = await pipeline.extract_characters(script=script)
    task_progress(tid, f"完成，提取到 {len(characters)} 个角色")


async def _stage_generate_portraits(tid: str, pipeline, p: Path):
    from interfaces import CharacterInScene
    task_progress(tid, "加载角色信息…")
    characters = [
        CharacterInScene.model_validate(c)
        for c in json.loads((p / "characters.json").read_text(encoding="utf-8"))
    ]
    style = load_style(p)
    task_progress(tid, f"生成 {len(characters)} 个角色的肖像（front/side/back）…")
    await pipeline.generate_character_portraits(characters=characters, character_portraits_registry=None, style=style)
    task_progress(tid, "角色肖像生成完成")


async def _stage_design_storyboard(tid: str, pipeline, p: Path):
    from interfaces import CharacterInScene
    task_progress(tid, "读取脚本和角色…")
    script = _get_script(p)
    if not script:
        raise ValueError("找不到脚本文件，请先在项目中添加脚本（scripts）")
    characters = [
        CharacterInScene.model_validate(c)
        for c in json.loads((p / "characters.json").read_text(encoding="utf-8"))
    ]
    meta: Dict = {}
    meta_path = p / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    task_progress(tid, "LLM 设计分镜中…")
    storyboard = await pipeline.design_storyboard(
        script=script, characters=characters, user_requirement=meta.get("user_requirement", "")
    )
    task_progress(tid, f"分镜设计完成，共 {len(storyboard)} 个镜头")


async def _stage_decompose_descriptions(tid: str, pipeline, p: Path):
    from interfaces import CharacterInScene, ShotBriefDescription
    task_progress(tid, "加载分镜和角色…")
    characters = [
        CharacterInScene.model_validate(c)
        for c in json.loads((p / "characters.json").read_text(encoding="utf-8"))
    ]
    storyboard = [
        ShotBriefDescription.model_validate(s)
        for s in json.loads((p / "storyboard.json").read_text(encoding="utf-8"))
    ]
    task_progress(tid, f"并发拆解 {len(storyboard)} 个镜头的视觉描述…")
    shot_descriptions = await pipeline.decompose_visual_descriptions(
        shot_brief_descriptions=storyboard, characters=characters
    )
    task_progress(tid, f"视觉描述拆解完成，共 {len(shot_descriptions)} 个镜头")


async def _stage_construct_camera_tree(tid: str, pipeline, p: Path):
    from interfaces import ShotDescription
    task_progress(tid, "加载镜头描述…")
    shots_dir = p / "shots"
    shot_descriptions = [
        ShotDescription.model_validate(json.loads((d / "shot_description.json").read_text(encoding="utf-8")))
        for d in sorted(shots_dir.iterdir(), key=lambda x: int(x.name))
        if d.is_dir() and (d / "shot_description.json").exists()
    ]
    task_progress(tid, f"LLM 构建相机树（{len(shot_descriptions)} 个镜头）…")
    camera_tree = await pipeline.construct_camera_tree(shot_descriptions=shot_descriptions)
    task_progress(tid, f"相机树构建完成，共 {len(camera_tree)} 个相机")


async def _stage_generate_frames(tid: str, pipeline, p: Path):
    from interfaces import CharacterInScene, ShotDescription, Camera
    from pipelines.script2video_pipeline import Script2VideoPipeline

    task_progress(tid, "加载上下文…")
    characters = [
        CharacterInScene.model_validate(c)
        for c in json.loads((p / "characters.json").read_text(encoding="utf-8"))
    ]
    registry = json.loads((p / "character_portraits_registry.json").read_text(encoding="utf-8"))
    camera_tree = [
        Camera.model_validate(c)
        for c in json.loads((p / "camera_tree.json").read_text(encoding="utf-8"))
    ]
    shots_dir = p / "shots"
    shot_descriptions = [
        ShotDescription.model_validate(json.loads((d / "shot_description.json").read_text(encoding="utf-8")))
        for d in sorted(shots_dir.iterdir(), key=lambda x: int(x.name))
        if d.is_dir() and (d / "shot_description.json").exists()
    ]

    Script2VideoPipeline.frame_events = {
        sd.idx: {"first_frame": asyncio.Event(), "last_frame": asyncio.Event()}
        for sd in shot_descriptions
    }

    priority_shot_idxs = [cam.parent_cam_idx for cam in camera_tree if cam.parent_cam_idx is not None]
    task_progress(tid, f"并发生成 {len(camera_tree)} 个相机的帧图…")
    await asyncio.gather(*[
        pipeline.generate_frames_for_single_camera(
            camera=cam,
            shot_descriptions=shot_descriptions,
            characters=characters,
            character_portraits_registry=registry,
            priority_shot_idxs=priority_shot_idxs,
        )
        for cam in camera_tree
    ])
    task_progress(tid, "帧图生成完成")


async def _stage_generate_videos(tid: str, pipeline, p: Path):
    from interfaces import ShotDescription
    task_progress(tid, "加载镜头描述…")
    shots_dir = p / "shots"
    shot_descriptions = [
        ShotDescription.model_validate(json.loads((d / "shot_description.json").read_text(encoding="utf-8")))
        for d in sorted(shots_dir.iterdir(), key=lambda x: int(x.name))
        if d.is_dir() and (d / "shot_description.json").exists()
    ]
    preset_all_frame_events(pipeline, p)
    task_progress(tid, f"并发生成 {len(shot_descriptions)} 个镜头的视频…")
    await asyncio.gather(*[
        pipeline.generate_video_for_single_shot(shot_description=sd)
        for sd in shot_descriptions
    ])
    task_progress(tid, "视频生成完成")


async def _stage_concatenate(tid: str, p: Path):
    from moviepy import VideoFileClip, concatenate_videoclips
    task_progress(tid, "加载分镜顺序…")
    storyboard = json.loads((p / "storyboard.json").read_text(encoding="utf-8"))
    shots_dir = p / "shots"
    task_progress(tid, f"拼接 {len(storyboard)} 个镜头…")
    clips = [VideoFileClip(str(shots_dir / str(s["idx"]) / "video.mp4")) for s in storyboard]
    final = concatenate_videoclips(clips)
    final_path = p / "final_video.mp4"
    final.write_videofile(str(final_path), codec="libx264", preset="medium")
    task_progress(tid, f"最终视频已保存：{final_path.name}")
