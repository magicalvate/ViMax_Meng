"""Shared state and utilities for all routers."""
import asyncio
import json
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


# ── JSON 工具 ─────────────────────────────────────────────────────────────────

def _read_json(p: Path, default):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
    for key in ("image_generator", "video_generator"):
        if key not in overrides:
            continue
        ov = overrides[key]
        if ov.get("class_path"):
            config[key]["class_path"] = ov["class_path"]
        if ov.get("init_args"):
            merged = dict(config.get(key, {}).get("init_args", {}))
            for k, v in ov["init_args"].items():
                if v is not None and v != "":
                    merged[k] = v
            config.setdefault(key, {})["init_args"] = merged


def get_available_apis() -> Dict[str, List[Dict]]:
    apis: Dict[str, List[Dict]] = {"image_generator": [], "video_generator": [], "chat_model": []}
    seen: set = set()

    for yaml_file in CONFIGS_DIR.glob("*.yaml"):
        try:
            config = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            cfg_name = yaml_file.stem

            if "image_generator" in config:
                cfg = config["image_generator"]
                cp = cfg.get("class_path", "")
                model = cfg.get("init_args", {}).get("model", "")
                if (cp, model) not in seen:
                    apis["image_generator"].append({"name": f"{cp.split('.')[-1]} - {model or cfg_name}", "class_path": cp, "model": model, "config_file": cfg_name})
                    seen.add((cp, model))

            if "video_generator" in config:
                cfg = config["video_generator"]
                cp = cfg.get("class_path", "")
                t2v = cfg.get("init_args", {}).get("t2v_model", "")
                if (cp, t2v) not in seen:
                    apis["video_generator"].append({"name": f"{cp.split('.')[-1]} - {t2v or cfg_name}", "class_path": cp, "t2v_model": t2v, "config_file": cfg_name})
                    seen.add((cp, t2v))

            if "chat_model" in config:
                cfg = config["chat_model"]
                init = cfg.get("init_args", {})
                model, base_url = init.get("model", ""), init.get("base_url", "")
                if (model, base_url) not in seen:
                    apis["chat_model"].append({"name": model or cfg_name, "model": model, "base_url": base_url, "config_file": cfg_name})
                    seen.add((model, base_url))
        except Exception:
            pass

    return apis


def _build_pipeline(project: str, overrides: dict):
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
    return Script2VideoPipeline(
        chat_model=chat_model,
        image_generator=backend.image_generator,
        video_generator=backend.video_generator,
        working_dir=config["working_dir"],
    )


def get_pipeline(project: str):
    overrides = _read_json(WORKING_DIR / project / "metadata.json", {}).get("api_overrides", {})
    fingerprint = json.dumps(overrides, sort_keys=True)
    cached = _pipeline_cache.get(project)
    if cached and cached[0] == fingerprint:
        return cached[1]
    pipeline = _build_pipeline(project, overrides)
    _pipeline_cache[project] = (fingerprint, pipeline)
    return pipeline


def get_pipeline_for_task(project: str, model_override: Optional[dict] = None):
    """Like get_pipeline but applies a per-task model override (no caching)."""
    if not model_override:
        return get_pipeline(project)
    base = _read_json(WORKING_DIR / project / "metadata.json", {}).get("api_overrides", {})
    merged = {**base}
    for key in ("image_generator", "video_generator"):
        if key in model_override:
            merged[key] = model_override[key]
    return _build_pipeline(project, merged)


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

def _build_frame_events(wd: Path, skip_shot: int = -1, skip_ft: str = "") -> dict:
    events: dict = {}
    shots_dir = wd / "shots"
    for d in sorted(shots_dir.iterdir()):
        if not d.is_dir():
            continue
        idx = int(d.name)
        shot_events = {}
        for ft in ("first_frame", "last_frame"):
            ev = asyncio.Event()
            if not (idx == skip_shot and ft == skip_ft) and (d / f"{ft}.png").exists():
                ev.set()
            shot_events[ft] = ev
        events[idx] = shot_events
    return events


def setup_frame_events(pipeline, wd: Path, target_shot_idx: int, target_frame_type: str):
    from pipelines.script2video_pipeline import Script2VideoPipeline
    Script2VideoPipeline.frame_events = _build_frame_events(wd, target_shot_idx, target_frame_type)


def preset_all_frame_events(pipeline, wd: Path):
    from pipelines.script2video_pipeline import Script2VideoPipeline
    Script2VideoPipeline.frame_events = _build_frame_events(wd)


def get_first_shot_ff_pair(wd: Path, shot_idx: int):
    cameras = _read_json(wd / "camera_tree.json", [])
    for cam in cameras:
        if shot_idx in cam.get("active_shot_idxs", []):
            first_idx = cam["active_shot_idxs"][0]
            shot_dir = wd / "shots" / str(first_idx)
            ff_desc = _read_json(shot_dir / "shot_description.json", {}).get("ff_desc", "")
            return (str(shot_dir / "first_frame.png"), ff_desc)
    shot_dir = wd / "shots" / str(shot_idx)
    ff_desc = _read_json(shot_dir / "shot_description.json", {}).get("ff_desc", "")
    return (str(shot_dir / "first_frame.png"), ff_desc)


def load_style(wd: Path) -> str:
    return _read_json(wd / "metadata.json", {}).get("style", "")


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


def load_ref_overrides(shot_dir: Path, ft_key: str) -> set:
    p = shot_dir / f"{ft_key}_ref_overrides.json"
    return set(_read_json(p, {}).get("disabled_paths", []))


def save_ref_overrides(shot_dir: Path, ft_key: str, disabled_paths: set):
    _write_json(shot_dir / f"{ft_key}_ref_overrides.json", {"disabled_paths": sorted(disabled_paths)})


def load_frame_refs(wd: Path, project: str, shot_dir: Path, ft_key: str) -> List[Dict]:
    selector = _read_json(shot_dir / f"{ft_key}_selector_output.json", None)
    if selector is None:
        return []
    pairs = selector.get("reference_image_path_and_text_pairs", [])
    disabled = load_ref_overrides(shot_dir, ft_key)
    return [
        {"path": ap, "url": f"/files/{project}/{abs_to_rel_path(wd, ap)}", "description": desc, "enabled": ap not in disabled}
        for ap, desc in pairs
    ]


def frame_state_path(shot_dir: Path) -> Path:
    return shot_dir / "frame_state.json"


def load_frame_state(shot_dir: Path) -> Dict:
    return _read_json(frame_state_path(shot_dir), {})


def is_frame_enabled(shot_dir: Path, ft_key: str) -> bool:
    return load_frame_state(shot_dir).get(ft_key, True)


def set_frame_enabled(shot_dir: Path, ft_key: str, enabled: bool):
    state = load_frame_state(shot_dir)
    state[ft_key] = enabled
    _write_json(frame_state_path(shot_dir), state)


# ── 版本管理工具 ──────────────────────────────────────────────────────────────

def new_vid() -> str:
    return _time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def _add_version(src: Path, dst: Path, meta_path: Path, key: str, vid: str, model: str = ""):
    if not src.exists():
        return
    dst.parent.mkdir(exist_ok=True)
    shutil.copy2(str(src), str(dst))
    meta = _read_json(meta_path, {})
    for e in meta.setdefault(key, []):
        e["selected"] = False
    entry: Dict = {"id": vid, "created_at": _time.strftime("%Y-%m-%dT%H:%M:%S"), "selected": True}
    if model:
        entry["model"] = model
    meta[key].append(entry)
    _write_json(meta_path, meta)


# ── Shot 版本 ─────────────────────────────────────────────────────────────────

def asset_ext(asset: str) -> str:
    return "mp4" if asset == "video" else "png"


def active_filename(asset: str) -> str:
    return "video.mp4" if asset == "video" else f"{asset}.png"


def get_model_label(generator) -> str:
    model = (
        getattr(generator, 'model', None) or
        getattr(generator, 't2v_model', None) or
        getattr(generator, 'i2v_model', None) or ""
    )
    if model:
        return str(model)
    cls = type(generator).__name__
    for s in ("ImageGenerator", "VideoGenerator", "GoogleAPI", "YunwuAPI", "SiliconflowAPI", "API"):
        cls = cls.replace(s, "")
    return cls or "unknown"


def load_shot_versions(shot_dir: Path) -> Dict:
    return _read_json(shot_dir / "versions.json", {})


def save_shot_versions(shot_dir: Path, meta: Dict):
    _write_json(shot_dir / "versions.json", meta)


def add_shot_version(shot_dir: Path, asset: str, vid: str, model: str = ""):
    ext = asset_ext(asset)
    _add_version(
        shot_dir / active_filename(asset),
        shot_dir / "versions" / f"{asset}_{vid}.{ext}",
        shot_dir / "versions.json",
        asset, vid, model,
    )


def shot_version_urls(project: str, shot_idx: int, shot_dir: Path) -> Dict:
    meta = load_shot_versions(shot_dir)
    return {
        asset: [{**e, "url": f"/files/{project}/shots/{shot_idx}/versions/{asset}_{e['id']}.{asset_ext(asset)}"}
                for e in entries]
        for asset, entries in meta.items()
    }


# ── Portrait 版本 ─────────────────────────────────────────────────────────────

def load_portrait_versions(char_dir: Path) -> Dict:
    return _read_json(char_dir / "portrait_versions.json", {})


def save_portrait_versions(char_dir: Path, meta: Dict):
    _write_json(char_dir / "portrait_versions.json", meta)


def add_portrait_version(char_dir: Path, view: str, vid: str, model: str = ""):
    _add_version(
        char_dir / f"{view}.png",
        char_dir / "versions" / f"{view}_{vid}.png",
        char_dir / "portrait_versions.json",
        view, vid, model,
    )


def load_portrait_bundle_versions(char_dir: Path) -> List[Dict]:
    return _read_json(char_dir / "portrait_bundle_versions.json", [])


def load_portrait_refs(char_dir: Path, project: str) -> List[Dict]:
    data = _read_json(char_dir / "portrait_refs.json", [])
    wd_base = WORKING_DIR / project
    return [
        {"path": item.get("path", ""), "url": f"/files/{project}/{abs_to_rel_path(wd_base, item.get('path', ''))}", "description": item.get("description", "")}
        for item in data
    ]


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
