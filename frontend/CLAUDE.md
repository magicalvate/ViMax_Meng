# Frontend 规范

## 技术栈

Vue.js 3（CDN）+ 原生 HTML/CSS，挂载进 FastAPI。

```bash
uv run uvicorn frontend.server:app --reload
# 访问 http://localhost:8000
```

后端 `frontend/core.py` 和所有 routers 保持不变。

---

## 文件结构

```
frontend/
  server.py              # FastAPI 服务入口
  core.py                # 后端核心函数（勿改）
  routers/               # REST API 路由层
  static/                # 前端页面（Vue.js CDN）
    index.html           # 骨架（顶栏 + Tab 导航 + Modal），约 80 行
    modules/             # 按功能拆分的 JS 模块
    tabs/                # 各 Tab 的 HTML 片段，服务端拼入骨架
  gradio_app/            # [DEPRECATED] 旧 Gradio 界面，勿读勿改
```

---

## 8 Tab 设计（对应 pipeline 8 个 stage）

| Tab 名 | activeTab 值 | HTML 片段文件 | JS 模块 |
|---|---|---|---|
| 脚本 | `extract_characters` | `tabs/tab_extract_characters.html` | `scripts.js`, `pipeline.js` |
| 人物 | `generate_portraits` | `tabs/tab_generate_portraits.html` | `characters.js`, `versions.js`, `pipeline.js` |
| 分镜 | `design_storyboard` | `tabs/tab_design_storyboard.html` | `shots.js`, `pipeline.js` |
| 描述 | `decompose_descriptions` | `tabs/tab_decompose_descriptions.html` | `shots.js`, `pipeline.js` |
| 机位 | `construct_camera_tree` | `tabs/tab_construct_camera_tree.html` | `shots.js`, `pipeline.js` |
| 帧 | `generate_frames` | `tabs/tab_generate_frames.html` | `shots.js`, `versions.js`, `pipeline.js` |
| 视频 | `generate_videos` | `tabs/tab_generate_videos.html` | `shots.js`, `versions.js`, `pipeline.js` |
| 最终视频 | `concatenate` | `tabs/tab_concatenate.html` | `pipeline.js` |

每个 Tab 顶部有该 stage 的运行控制栏（运行 / 强制重跑 / 状态展示）。

---

## 功能设计原则

- **最小粒度**：每个生成操作对应单一 shot + 单一 frame_type
- **局部刷新**：生成完成后只更新对应组件，不全量刷新
- **参数全暴露**：frame_type、scene_refs、shot_description 等都要有操作入口
- **需求不明确时先问**：禁止假设推断

---

## 响应规范

- 修改组件时只输出变更部分，禁止完整重写未变动文件
- 优先复用已有 handler 函数，不重复实现
- 搜索限定在 `frontend/` 目录
