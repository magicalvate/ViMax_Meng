"""Shared state and utilities for all routers."""
import asyncio
import json
import mimetypes
import shutil
import time as _time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from fastapi import HTTPException, UploadFile

BASE_DIR = Path(__file__).parent.parent
WORKING_DIR = BASE_DIR / ".working_dir"
STATIC_DIR = Path(__file__).parent / "static"
CONFIGS_DIR = BASE_DIR / "configs"

SCENE_REF_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


# ── Config 发现 ──────────────────────────────────────────────────────────────

_config_cache: Dict[str, str] = {}


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

_pipeline_cache: Dict[str, tuple] = {}


def _apply_api_overrides(config: dict, overrides: dict):
    if "chat_model" in overrides:
        for k, v in overrides["chat_model"].items():
            if v is not None and v != "":
                config.setdefault("chat_model", {}).setdefault("init_args", {})[k] = v
    if "image_generator" in overrides:
        ov = overrides["image_generator"]
        if ov.get("class_path"):
            config["image_generator"]["class_path"] = ov["class_path"]
        if ov.get("init_args"):
            merged = dict(config.get("image_generator", {}).get("init_args", {}))
            for k, v in ov["init_args"].items():
                if v is not None and v != "":
                    merged[k] = v
            config.setdefault("image_generator", {})["init_args"] = merged
    if "video_generator" in overrides:
        ov = overrides["video_generator"]
        if ov.get("class_path"):
            config["video_generator"]["class_path"] = ov["class_path"]
        if ov.get("init_args"):
            merged = dict(config.get("video_generator", {}).get("init_args", {}))
            for k, v in ov["init_args"].items():
                if v is not None and v != "":
                    merged[k] = v
            config.setdefault("video_generator", {})["init_args"] = merged


def get_available_apis() -> Dict[str, List[Dict]]:
    """扫描所有配置文件，返回可用的 API 选项。

    Returns:
        {
            "image_generator": [
                {"name": "...", "class_path": "...", "model": "..."},
                ...
            ],
            "video_generator": [...],
            "chat_model": [...]
        }
    """
    apis = {
        "image_generator": [],
        "video_generator": [],
        "chat_model": [],
    }

    seen_configs = set()
    for yaml_file in CONFIGS_DIR.glob("*.yaml"):
        try:
            config = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            config_name = yaml_file.stem

            # 提取图片生成器
            if "image_generator" in config:
                img_cfg = config["image_generator"]
                class_path = img_cfg.get("class_path", "")
                init_args = img_cfg.get("init_args", {})
                model = init_args.get("model", "")

                key = (class_path, model)
                if key not in seen_configs:
                    apis["image_generator"].append({
                        "name": f"{class_path.split('.')[-1]} - {model or config_name}",
                        "class_path": class_path,
                        "model": model,
                        "config_file": config_name,
                    })
                    seen_configs.add(key)

            # 提取视频生成器
            if "video_generator" in config:
                vid_cfg = config["video_generator"]
                class_path = vid_cfg.get("class_path", "")
                init_args = vid_cfg.get("init_args", {})
                t2v_model = init_args.get("t2v_model", "")

                key = (class_path, t2v_model)
                if key not in seen_configs:
                    apis["video_generator"].append({
                        "name": f"{class_path.split('.')[-1]} - {t2v_model or config_name}",
                        "class_path": class_path,
                        "t2v_model": t2v_model,
                        "config_file": config_name,
                    })
                    seen_configs.add(key)

            # 提取聊天模型
            if "chat_model" in config:
                chat_cfg = config["chat_model"]
                init_args = chat_cfg.get("init_args", {})
                model = init_args.get("model", "")
                base_url = init_args.get("base_url", "")

                key = (model, base_url)
                if key not in seen_configs:
                    apis["chat_model"].append({
                        "name": f"{model or config_name}",
                        "model": model,
                        "base_url": base_url,
                        "config_file": config_name,
                    })
                    seen_configs.add(key)
        except Exception as e:
            # 忽略解析错误
            pass

    return apis


def get_pipeline(project: str):
    wd = WORKING_DIR / project
    meta_path = wd / "metadata.json"
    overrides: dict = {}
    if meta_path.exists():
        try:
            overrides = json.loads(meta_path.read_text(encoding="utf-8")).get("api_overrides", {})
        except Exception:
            pass
    fingerprint = json.dumps(overrides, sort_keys=True)

    cached = _pipeline_cache.get(project)
    if cached and cached[0] == fingerprint:
        return cached[1]

    config_path = find_config(project)
    if not config_path:
        raise HTTPException(404, f"No config file found for project '{project}'")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    _apply_api_overrides(config, overrides)

    from langchain.chat_models import init_chat_model
    from tools.render_backend import RenderBackend
    from pipelines.script2video_pipeline import Script2VideoPipeline

    chat_model = init_chat_model(**config["chat_model"]["init_args"])
    backend = RenderBackend.from_config(config)
    pipeline = Script2VideoPipeline(
        chat_model=chat_model,
        image_generator=backend.image_generator,
        video_generator=backend.video_generator,
        working_dir=config["working_dir"],
    )
    _pipeline_cache[project] = (fingerprint, pipeline)
    return pipeline


# ── Task 系统 ────────────────────────────────────────────────────────────────

_tasks: Dict[str, Dict] = {}


def new_task() -> str:
    tid = str(uuid.uuid4())
    _tasks[tid] = {"status": "running", "error_msg": None}
    return tid


def task_done(tid: str):
    _tasks[tid]["status"] = "done"
    _tasks[tid]["status_msg"] = ""


def task_error(tid: str, msg: str):
    _tasks[tid]["status"] = "error"
    _tasks[tid]["error_msg"] = msg


def task_progress(tid: str, msg: str):
    _tasks[tid]["status_msg"] = msg


# ── Frame events 工具 ────────────────────────────────────────────────────────

def setup_frame_events(pipeline, wd: Path, target_shot_idx: int, target_frame_type: str):
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
            if not (idx == target_shot_idx and ft == target_frame_type):
                if (d / f"{ft}.png").exists():
                    ev.set()
            events[ft] = ev
        Script2VideoPipeline.frame_events[idx] = events


def preset_all_frame_events(pipeline, wd: Path):
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


def get_first_shot_ff_pair(wd: Path, shot_idx: int):
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
    ff_path = str(wd / "shots" / str(shot_idx) / "first_frame.png")
    desc_path = wd / "shots" / str(shot_idx) / "shot_description.json"
    ff_desc = json.loads(desc_path.read_text(encoding="utf-8")).get("ff_desc", "") if desc_path.exists() else ""
    return (ff_path, ff_desc)


def load_style(wd: Path) -> str:
    meta_path = wd / "metadata.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8")).get("style", "")
    return ""


# ── Frame 启用/禁用状态 ────────────────────────────────────────────────────────

def abs_to_rel_path(wd: Path, abs_path: str) -> str:
    p = Path(abs_path)
    if p.is_absolute():
        try:
            return str(p.relative_to(wd)).replace("\\", "/")
        except ValueError:
            return abs_path
    resolved = BASE_DIR / p
    try:
        return str(resolved.relative_to(wd)).replace("\\", "/")
    except ValueError:
        return abs_path


def ref_overrides_path(shot_dir: Path, ft_key: str) -> Path:
    return shot_dir / f"{ft_key}_ref_overrides.json"


def load_ref_overrides(shot_dir: Path, ft_key: str) -> set:
    p = ref_overrides_path(shot_dir, ft_key)
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")).get("disabled_paths", []))


def save_ref_overrides(shot_dir: Path, ft_key: str, disabled_paths: set):
    ref_overrides_path(shot_dir, ft_key).write_text(
        json.dumps({"disabled_paths": sorted(disabled_paths)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_frame_refs(wd: Path, project: str, shot_dir: Path, ft_key: str) -> List[Dict]:
    selector_path = shot_dir / f"{ft_key}_selector_output.json"
    if not selector_path.exists():
        return []
    try:
        selector = json.loads(selector_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    pairs = selector.get("reference_image_path_and_text_pairs", [])
    disabled = load_ref_overrides(shot_dir, ft_key)
    refs = []
    for abs_path, desc in pairs:
        rel = abs_to_rel_path(wd, abs_path)
        refs.append({
            "path": abs_path,
            "url": f"/files/{project}/{rel}",
            "description": desc,
            "enabled": abs_path not in disabled,
        })
    return refs


def frame_state_path(shot_dir: Path) -> Path:
    return shot_dir / "frame_state.json"


def load_frame_state(shot_dir: Path) -> Dict:
    p = frame_state_path(shot_dir)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def is_frame_enabled(shot_dir: Path, ft_key: str) -> bool:
    return load_frame_state(shot_dir).get(ft_key, True)


def set_frame_enabled(shot_dir: Path, ft_key: str, enabled: bool):
    state = load_frame_state(shot_dir)
    state[ft_key] = enabled
    frame_state_path(shot_dir).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── 版本管理工具 ──────────────────────────────────────────────────────────────

def new_vid() -> str:
    return _time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


# ── Shot 版本 ──────────────────────────────────────────────────────────────────

def shot_versions_meta_path(shot_dir: Path) -> Path:
    return shot_dir / "versions.json"


def load_shot_versions(shot_dir: Path) -> Dict:
    p = shot_versions_meta_path(shot_dir)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_shot_versions(shot_dir: Path, meta: Dict):
    shot_versions_meta_path(shot_dir).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def asset_ext(asset: str) -> str:
    return "mp4" if asset == "video" else "png"


def active_filename(asset: str) -> str:
    return "video.mp4" if asset == "video" else f"{asset}.png"


def add_shot_version(shot_dir: Path, asset: str, vid: str):
    ext = asset_ext(asset)
    active = shot_dir / active_filename(asset)
    if not active.exists():
        return
    ver_dir = shot_dir / "versions"
    ver_dir.mkdir(exist_ok=True)
    shutil.copy2(str(active), str(ver_dir / f"{asset}_{vid}.{ext}"))

    meta = load_shot_versions(shot_dir)
    for e in meta.setdefault(asset, []):
        e["selected"] = False
    meta[asset].append({
        "id": vid,
        "created_at": _time.strftime("%Y-%m-%dT%H:%M:%S"),
        "selected": True,
    })
    save_shot_versions(shot_dir, meta)


def shot_version_urls(project: str, shot_idx: int, shot_dir: Path) -> Dict:
    meta = load_shot_versions(shot_dir)
    result = {}
    for asset, entries in meta.items():
        ext = asset_ext(asset)
        result[asset] = [
            {**e, "url": f"/files/{project}/shots/{shot_idx}/versions/{asset}_{e['id']}.{ext}"}
            for e in entries
        ]
    return result


# ── Portrait 版本 ─────────────────────────────────────────────────────────────

def portrait_versions_meta_path(char_dir: Path) -> Path:
    return char_dir / "portrait_versions.json"


def load_portrait_versions(char_dir: Path) -> Dict:
    p = portrait_versions_meta_path(char_dir)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_portrait_versions(char_dir: Path, meta: Dict):
    portrait_versions_meta_path(char_dir).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_portrait_version(char_dir: Path, view: str, vid: str):
    active = char_dir / f"{view}.png"
    if not active.exists():
        return
    ver_dir = char_dir / "versions"
    ver_dir.mkdir(exist_ok=True)
    shutil.copy2(str(active), str(ver_dir / f"{view}_{vid}.png"))

    meta = load_portrait_versions(char_dir)
    for e in meta.setdefault(view, []):
        e["selected"] = False
    meta[view].append({
        "id": vid,
        "created_at": _time.strftime("%Y-%m-%dT%H:%M:%S"),
        "selected": True,
    })
    save_portrait_versions(char_dir, meta)


def find_char_dir(wd: Path, char_idx: int) -> Optional[Path]:
    portraits_dir = wd / "character_portraits"
    if not portraits_dir.exists():
        return None
    for d in portraits_dir.iterdir():
        if d.is_dir() and d.name.startswith(f"{char_idx}_"):
            return d
    return None


# ── 内部工具 ─────────────────────────────────────────────────────────────────

def wd(project: str) -> Path:
    p = WORKING_DIR / project
    if not p.exists():
        raise HTTPException(404, f"Project '{project}' not found")
    return p


def save_upload(file: UploadFile, target_path: Path):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
