# Frontend 规范

## 技术方向：Gradio 重构

Vue.js 前端已废弃，新前端用 **Gradio** 重写，挂载进 FastAPI。

```python
# server.py 挂载方式
import gradio as gr
from frontend.gradio_app.app import build_app
gr.mount_gradio_app(app, build_app(), path="/")
```

后端 `frontend/core.py` 和所有 routers 保持不变，handler 直接调 Python 函数，不走 HTTP。

---

## 文件结构

```
frontend/
  gradio_app/
    app.py              # gr.Blocks 入口
    state.py            # gr.State 定义
    tabs/               # 每个 Tab 一个文件
    components/         # 原子组件（stage_accordion, frame_cell 等）
    handlers/           # 事件回调（调用 core.py）
    utils/              # 工具函数（data_loaders, file_urls）
```

---

## 原子组件规范

每个组件文件只暴露一个函数，返回 Gradio 组件列表：

```python
# components/frame_cell.py
def frame_cell(shot_idx: int, frame_type: str) -> tuple[gr.Image, gr.Button, gr.Button]:
    img = gr.Image(label=f"{frame_type}", show_label=True)
    regen_btn = gr.Button("↺ 重生成", size="sm")
    toggle_btn = gr.Button("启用/禁用", size="sm")
    return img, regen_btn, toggle_btn
```

组件 **不含任何业务逻辑**，逻辑全部在 `handlers/` 中。

---

## 关键 Gradio 约束

| 问题 | 解法 |
|------|------|
| N 个 Shot 不能动态渲染 | Dropdown 选 Shot → 单详情面板 |
| 长任务轮询 | `gr.Timer(value=2, active=True)` 驱动状态刷新 |
| 图片/视频文件服务 | 保留 FastAPI `/files/...` 路由，gr.Image 用 URL |
| 文件上传 | `gr.UploadButton` → 调 handler → 调 FastAPI upload |
| 版本历史 | `gr.Gallery` with labeled thumbnails |

---

## 功能设计（延续旧规范）

- **最小粒度**：每个生成操作对应单一 shot + 单一 frame_type
- **局部刷新**：生成完成后只更新对应组件，不全量刷新
- **参数全暴露**：frame_type、scene_refs、shot_description 等都要有操作入口
- **需求不明确时先问**：禁止假设推断

---

## 响应规范

- 修改组件时只输出变更部分，禁止完整重写未变动文件
- 优先复用已有 handler 函数，不重复实现
- 搜索限定在 `frontend/` 目录

---

## 模块参考

完整原子模块清单见：`memory/frontend_gradio_architecture.md`
