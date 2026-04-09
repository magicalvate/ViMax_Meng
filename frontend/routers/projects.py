import json
import mimetypes
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from frontend.core import (
    WORKING_DIR, STATIC_DIR, SCENE_REF_EXTS,
    wd, load_frame_refs, is_frame_enabled, shot_version_urls,
    load_portrait_versions, load_portrait_refs, load_portrait_bundle_versions, _tasks,
)

router = APIRouter()

_TAB_ORDER = [
    "tab_extract_characters",
    "tab_generate_portraits",
    "tab_design_storyboard",
    "tab_decompose_descriptions",
    "tab_construct_camera_tree",
    "tab_generate_frames",
    "tab_generate_videos",
    "tab_concatenate",
]


@router.get("/")
async def index():
    tabs_dir = STATIC_DIR / "tabs"
    tabs_html = "\n".join((tabs_dir / f"{name}.html").read_text() for name in _TAB_ORDER)
    skeleton = (STATIC_DIR / "index.html").read_text()
    html = skeleton.replace("<!-- TABS_PLACEHOLDER -->", tabs_html)
    return HTMLResponse(html)


@router.get("/api/projects")
async def list_projects():
    if not WORKING_DIR.exists():
        return []
    return sorted(d.name for d in WORKING_DIR.iterdir() if d.is_dir() and not d.name.startswith("."))


@router.get("/api/projects/{project}/data")
async def get_project_data(project: str):
    p = wd(project)

    def load(path: Path):
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    characters = load(p / "characters.json") or []
    portraits_registry = load(p / "character_portraits_registry.json") or {}
    storyboard = load(p / "storyboard.json") or []
    camera_tree = load(p / "camera_tree.json") or []
    metadata = load(p / "metadata.json") or {}

    shots = []
    shots_dir = p / "shots"
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
            has_ff = (shot_dir / "first_frame.png").exists()
            has_lf = (shot_dir / "last_frame.png").exists()
            frame_refs = {}
            for ft_key in ("first_frame", "last_frame"):
                if (shot_dir / f"{ft_key}.png").exists():
                    frame_refs[ft_key] = load_frame_refs(p, project, shot_dir, ft_key)
            shots.append({
                "idx": idx,
                "description": desc,
                "has_first_frame": has_ff,
                "has_last_frame": has_lf,
                "has_video": (shot_dir / "video.mp4").exists(),
                "first_frame_enabled": is_frame_enabled(shot_dir, "first_frame") if has_ff else False,
                "last_frame_enabled": is_frame_enabled(shot_dir, "last_frame") if has_lf else False,
                "scene_refs": scene_refs,
                "frame_refs": frame_refs,
                "versions": shot_version_urls(project, idx, shot_dir),
            })

    portrait_versions: Dict[str, Dict] = {}
    portrait_refs: Dict[str, List] = {}
    portrait_bundle_versions: Dict[str, List] = {}
    portraits_dir = p / "character_portraits"
    if portraits_dir.exists():
        for char_dict in characters:
            cidx = char_dict.get("idx")
            cname = char_dict.get("identifier_in_scene", "")
            if cidx is not None:
                char_dir = portraits_dir / f"{cidx}_{cname}"
                pv = load_portrait_versions(char_dir)
                pv_with_urls: Dict[str, List] = {}
                for view, entries in pv.items():
                    pv_with_urls[view] = [
                        {**e, "url": f"/files/{project}/character_portraits/{cidx}_{cname}/versions/{view}_{e['id']}.png"}
                        for e in entries
                    ]
                portrait_versions[str(cidx)] = pv_with_urls
                portrait_refs[str(cidx)] = load_portrait_refs(char_dir, project)
                bundle_entries = load_portrait_bundle_versions(char_dir)
                portrait_bundle_versions[str(cidx)] = [
                    {**e, "preview_url": f"/files/{project}/character_portraits/{cidx}_{cname}/versions/bundle_{e['id']}_front.png"}
                    for e in bundle_entries
                ]

    return {
        "characters": characters,
        "portraits_registry": portraits_registry,
        "portrait_versions": portrait_versions,
        "portrait_refs": portrait_refs,
        "portrait_bundle_versions": portrait_bundle_versions,
        "storyboard": storyboard,
        "camera_tree": camera_tree,
        "shots": shots,
        "has_final_video": (p / "final_video.mp4").exists(),
        "metadata": metadata,
    }


@router.get("/files/{project}/{path:path}")
async def serve_file(project: str, path: str):
    p = wd(project)
    file_path = p / path
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    media_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(str(file_path), media_type=media_type or "application/octet-stream")


@router.patch("/api/projects/{project}/metadata")
async def update_metadata(project: str, request: Request):
    p = wd(project)
    meta_path = p / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    body = await request.json()
    meta.update(body)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


@router.patch("/api/projects/{project}/characters/{idx}")
async def update_character(project: str, idx: int, request: Request):
    p = wd(project)
    chars_path = p / "characters.json"
    chars = json.loads(chars_path.read_text(encoding="utf-8")) if chars_path.exists() else []
    body = await request.json()
    for char in chars:
        if char.get("idx") == idx:
            char.update(body)
            chars_path.write_text(json.dumps(chars, ensure_ascii=False, indent=2), encoding="utf-8")
            return char
    raise HTTPException(404, "Character not found")


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in _tasks:
        raise HTTPException(404, "Task not found")
    return _tasks[task_id]
