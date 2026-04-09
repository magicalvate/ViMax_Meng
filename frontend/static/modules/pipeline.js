const { reactive, ref } = Vue;

export function setupPipeline({ currentProject, shots, cameraTree, metadata, enc, showToast, loadProject, availableApis }) {
  const pipelineStages = [
    { key: "extract_characters",    label: "① 提取角色" },
    { key: "generate_portraits",    label: "② 生成角色肖像" },
    { key: "design_storyboard",     label: "③ 分镜设计" },
    { key: "decompose_descriptions",label: "④ 视觉描述拆解" },
    { key: "construct_camera_tree", label: "⑤ 构建相机树" },
    { key: "generate_frames",       label: "⑥ 生成帧图" },
    { key: "generate_videos",       label: "⑦ 生成视频" },
    { key: "concatenate",           label: "⑧ 拼接最终视频" },
  ];
  const stagesStatus = reactive({});
  const stageTasks = reactive({});
  const stageExpanded = reactive({});
  const userRequirement = ref("");
  const storyboard = ref([]);

  function toggleStageExpanded(key) {
    stageExpanded[key] = !stageExpanded[key];
  }

  function stageStyle(key) {
    const meta = metadata.value || {};
    if (key === 'extract_characters') return meta.style || '（未设置）';
    return '';
  }

  function cameraGroups() {
    return cameraTree.value;
  }

  function shotHasFrame(shotIdx, type) {
    const s = shots.value.find(s => s.idx === shotIdx);
    return s ? (type === 'first' ? s.has_first_frame : s.has_last_frame) : false;
  }

  async function fetchStagesStatus() {
    if (!currentProject.value) return;
    try {
      const res = await fetch(`/api/projects/${enc(currentProject.value)}/stages/status`);
      if (!res.ok) return;
      Object.assign(stagesStatus, await res.json());
    } catch {}
  }

  function isStageRunning(key) {
    return stageTasks[key]?.status === "running";
  }

  function stageTaskMsg(key) {
    return stageTasks[key]?.msg || "";
  }

  function stageTaskError(key) {
    const t = stageTasks[key];
    return t?.status === "error" ? (t.error || "未知错误") : null;
  }

  async function runStage(key, force = false) {
    if (!currentProject.value) return;
    stageTasks[key] = { status: "running", msg: "启动中…", error: null, taskId: null };
    try {
      const res = await fetch(`/api/projects/${enc(currentProject.value)}/run/${key}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force }),
      });
      const data = await res.json();
      if (!res.ok) {
        stageTasks[key] = { status: "error", msg: "", error: data.detail || JSON.stringify(data), taskId: null };
        return;
      }
      stageTasks[key].taskId = data.task_id;
      _pollStageTask(key, data.task_id);
    } catch (e) {
      stageTasks[key] = { status: "error", msg: "", error: e.message, taskId: null };
    }
  }

  function _pollStageTask(key, tid) {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/tasks/${tid}`);
        if (!res.ok) return;
        const t = await res.json();
        stageTasks[key].msg = t.status_msg || "";
        if (t.status === "done") {
          clearInterval(interval);
          stageTasks[key].status = "done";
          await fetchStagesStatus();
          await loadProject(currentProject.value);
          showToast("阶段完成", "info");
        } else if (t.status === "error") {
          clearInterval(interval);
          stageTasks[key] = { status: "error", msg: "", error: t.error_msg || "未知错误", taskId: tid };
          showToast(`阶段失败: ${t.error_msg}`, "error");
        }
      } catch {}
    }, 2000);
  }

  async function saveUserRequirement() {
    if (!currentProject.value) return;
    try {
      await fetch(`/api/projects/${enc(currentProject.value)}/metadata`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_requirement: userRequirement.value }),
      });
      showToast("已保存", "info");
    } catch (e) {
      showToast("保存失败: " + e.message, "error");
    }
  }

  async function saveMetadataField(field, value) {
    if (!currentProject.value) return;
    try {
      await fetch(`/api/projects/${enc(currentProject.value)}/metadata`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value }),
      });
      showToast("已保存", "info");
    } catch (e) {
      showToast("保存失败: " + e.message, "error");
    }
  }

  // ── API 配置 ──────────────────────────────────────────────────────────────
  const showApiPanel = ref(false);
  const apiConfig = reactive({
    image_generator: {},
    video_generator: {},
    chat_model: {},
  });
  const apiConfigModel = reactive({
    image_generator: {},
    video_generator: {},
    chat_model: {},
  });

  function toggleApiPanel() {
    showApiPanel.value = !showApiPanel.value;
  }

  async function loadAvailableApis() {
    try {
      const res = await fetch("/api/api-options");
      if (res.ok) {
        Object.assign(availableApis.value, await res.json());
      }
    } catch {}
  }

  async function loadApiConfig() {
    if (!currentProject.value) return;
    try {
      const res = await fetch(`/api/projects/${enc(currentProject.value)}/api-config`);
      if (res.ok) {
        const config = await res.json();
        Object.assign(apiConfig, config);
        Object.assign(apiConfigModel, JSON.parse(JSON.stringify(config)));
      }
    } catch {}
  }

  async function saveApiConfig() {
    if (!currentProject.value) return;
    try {
      const res = await fetch(`/api/projects/${enc(currentProject.value)}/api-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(apiConfigModel),
      });
      if (res.ok) {
        showToast("API 配置已保存（管道将重新加载）", "success");
        Object.assign(apiConfig, apiConfigModel);
      } else {
        showToast("保存失败", "error");
      }
    } catch (e) {
      showToast("保存失败: " + e.message, "error");
    }
  }

  return {
    pipelineStages, stagesStatus, stageTasks, stageExpanded, userRequirement, storyboard,
    toggleStageExpanded, stageStyle, cameraGroups, shotHasFrame,
    fetchStagesStatus, isStageRunning, stageTaskMsg, stageTaskError,
    runStage, saveUserRequirement, saveMetadataField,
    availableApis, apiConfig, apiConfigModel, showApiPanel,
    loadAvailableApis, loadApiConfig, saveApiConfig, toggleApiPanel,
  };
}
