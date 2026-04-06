const { createApp, ref, reactive, computed, watch } = Vue;

createApp({
  setup() {
    // ── 状态 ────────────────────────────────────────────────────────────────
    const projects = ref([]);
    const currentProject = ref("");
    const activeTab = ref("shots");
    const loading = ref(false);

    const characters = ref([]);
    const portraitsRegistry = ref({});
    const shots = ref([]);
    const hasFinalVideo = ref(false);
    const metadata = ref({});

    const expandedShots = ref(new Set());
    const editingDesc = ref(new Set());

    // 脚本
    const scriptFiles = ref([]);
    const currentScriptFile = ref("");
    const scriptData = ref(null);
    const scriptLoading = ref(false);
    const newScriptPath = ref("");

    // lightbox
    const lightboxUrl = ref(null);
    function openLightbox(url) { if (url) lightboxUrl.value = url; }

    // replace modal
    const modal = ref(null);

    // task 状态: { key -> {taskId, status, error} }
    // key 格式: "frame_{shotIdx}_{first|last}" | "video_{shotIdx}" | "portrait_{charIdx}_{view}"
    const taskStatus = reactive({});
    const _pollers = {};  // key -> intervalId

    // toast
    const toast = ref(null);
    let toastTimer = null;

    // 图片缓存破坏时间戳
    const imgTs = ref({});

    // ── 初始化 ───────────────────────────────────────────────────────────────
    async function init() {
      const res = await fetch("/api/projects");
      projects.value = await res.json();
      if (projects.value.length > 0) currentProject.value = projects.value[0];
    }

    watch(currentProject, val => { if (val) loadProject(val); });
    watch(activeTab, val => { if (val === 'script' && scriptFiles.value.length === 0) loadScriptFiles(); });

    async function loadProject(name) {
      loading.value = true;
      expandedShots.value = new Set();
      editingDesc.value = new Set();
      imgTs.value = {};
      Object.keys(taskStatus).forEach(k => delete taskStatus[k]);
      try {
        const res = await fetch(`/api/projects/${enc(name)}/data`);
        const data = await res.json();
        characters.value = data.characters || [];
        portraitsRegistry.value = data.portraits_registry || {};
        shots.value = data.shots || [];
        hasFinalVideo.value = data.has_final_video || false;
        metadata.value = data.metadata || {};
      } finally {
        loading.value = false;
      }
    }

    // ── URL 工具 ─────────────────────────────────────────────────────────────
    function enc(s) { return encodeURIComponent(s); }

    function fileUrl(relPath, tsKey) {
      if (!relPath) return "";
      const path = relPath.replace(/\\/g, "/").replace(/^\.working_dir\/[^/]+\//, "");
      const ts = tsKey ? (imgTs.value[tsKey] || "") : "";
      return `/files/${enc(currentProject.value)}/${path}${ts ? `?t=${ts}` : ""}`;
    }

    function portraitUrl(charName, view) {
      const reg = portraitsRegistry.value[charName];
      if (!reg?.[view]) return "";
      const raw = reg[view].path.replace(/\\/g, "/");
      const inner = raw.split("/").slice(2).join("/");
      const ts = imgTs.value[`portrait_${charName}_${view}`] || "";
      return `/files/${enc(currentProject.value)}/${inner}${ts ? `?t=${ts}` : ""}`;
    }

    function shotFileUrl(shotIdx, filename) {
      const ts = imgTs.value[`shot_${shotIdx}_${filename}`] || "";
      return `/files/${enc(currentProject.value)}/shots/${shotIdx}/${filename}${ts ? `?t=${ts}` : ""}`;
    }

    function finalVideoUrl() {
      return `/files/${enc(currentProject.value)}/final_video.mp4`;
    }

    // ── 脚本 ────────────────────────────────────────────────────────────────
    async function loadScriptFiles() {
      if (!currentProject.value) return;
      const res = await fetch(`/api/projects/${enc(currentProject.value)}/scripts`);
      scriptFiles.value = await res.json();
      if (scriptFiles.value.length > 0 && !currentScriptFile.value) {
        loadScript(scriptFiles.value[0]);
      }
    }

    async function loadScript(path) {
      currentScriptFile.value = path;
      scriptLoading.value = true;
      scriptData.value = null;
      try {
        const res = await fetch(`/api/scripts/parse?path=${encodeURIComponent(path)}`);
        if (!res.ok) throw new Error(await res.text());
        scriptData.value = await res.json();
      } catch (e) {
        showToast("解析失败: " + e.message, "error");
      } finally {
        scriptLoading.value = false;
      }
    }

    async function addScript() {
      const path = newScriptPath.value.trim();
      if (!path) return;
      try {
        const res = await fetch(`/api/projects/${enc(currentProject.value)}/scripts`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path }),
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        scriptFiles.value = data.script_files;
        newScriptPath.value = "";
        loadScript(path);
      } catch (e) {
        showToast("添加失败: " + e.message, "error");
      }
    }

    // section row：col[0] 非空且 col[1..] 全为空（章节分隔行）
    function isSectionRow(row) {
      const cells = row.cells;
      return cells[0] && cells.slice(1).every(c => !c);
    }

    // ── 参考人物 ─────────────────────────────────────────────────────────────
    function visibleCharPortraits(shot) {
      const desc = shot.description;
      if (!desc) return [];
      const idxSet = new Set([...(desc.ff_vis_char_idxs || []), ...(desc.lf_vis_char_idxs || [])]);
      return Array.from(idxSet).map(cidx => {
        const char = characters.value.find(c => c.idx === cidx);
        return char ? { charName: char.identifier_in_scene, charIdx: cidx } : null;
      }).filter(Boolean);
    }

    // ── Shot 折叠 / 描述编辑 ─────────────────────────────────────────────────
    function toggleShot(idx) {
      if (expandedShots.value.has(idx)) expandedShots.value.delete(idx);
      else expandedShots.value.add(idx);
    }
    function isShotExpanded(idx) { return expandedShots.value.has(idx); }

    function toggleDescEdit(idx) {
      if (editingDesc.value.has(idx)) editingDesc.value.delete(idx);
      else editingDesc.value.add(idx);
    }
    function isEditingDesc(idx) { return editingDesc.value.has(idx); }

    async function saveDesc(shot) {
      const desc = shot.description;
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/description`,
          { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
            ff_desc: desc.ff_desc, lf_desc: desc.lf_desc,
            motion_desc: desc.motion_desc, audio_desc: desc.audio_desc,
          })}
        );
        if (!res.ok) throw new Error(await res.text());
        showToast("描述已保存", "success");
        editingDesc.value.delete(shot.idx);
      } catch (e) {
        showToast("保存失败: " + e.message, "error");
      }
    }

    // ── Task 轮询 ────────────────────────────────────────────────────────────
    function startPoll(key, taskId, onDone) {
      if (_pollers[key]) clearInterval(_pollers[key]);
      taskStatus[key] = { taskId, status: "running" };
      _pollers[key] = setInterval(async () => {
        try {
          const r = await fetch(`/api/tasks/${taskId}`);
          const t = await r.json();
          taskStatus[key].status = t.status;
          if (t.status === "done") {
            clearInterval(_pollers[key]);
            delete _pollers[key];
            onDone();
          } else if (t.status === "error") {
            clearInterval(_pollers[key]);
            delete _pollers[key];
            showToast("生成失败: " + (t.error_msg || "未知错误"), "error");
          }
        } catch { /* ignore poll errors */ }
      }, 2000);
    }

    function taskState(key) { return taskStatus[key] || null; }
    function isRunning(key) { return taskStatus[key]?.status === "running"; }

    // ── AI 重新生成：帧 ──────────────────────────────────────────────────────
    async function regenerateFrame(shot, frameType) {
      const key = `frame_${shot.idx}_${frameType}`;
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/regenerate/frame/${frameType}`,
          { method: "POST" }
        );
        if (!res.ok) throw new Error(await res.text());
        const { task_id } = await res.json();
        startPoll(key, task_id, () => {
          const tsKey = `shot_${shot.idx}_${frameType}_frame.png`;
          imgTs.value[tsKey] = Date.now();
          shot[`has_${frameType}_frame`] = true;
          showToast(`Shot ${shot.idx} ${frameType === "first" ? "首帧" : "末帧"}已重新生成`, "success");
        });
      } catch (e) {
        showToast("启动失败: " + e.message, "error");
      }
    }

    // ── AI 重新生成：视频 ────────────────────────────────────────────────────
    async function regenerateVideo(shot) {
      const key = `video_${shot.idx}`;
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/regenerate/video`,
          { method: "POST" }
        );
        if (!res.ok) throw new Error(await res.text());
        const { task_id } = await res.json();
        startPoll(key, task_id, () => {
          imgTs.value[`shot_${shot.idx}_video.mp4`] = Date.now();
          shot.has_video = true;
          showToast(`Shot ${shot.idx} 视频已重新生成`, "success");
        });
      } catch (e) {
        showToast("启动失败: " + e.message, "error");
      }
    }

    // ── AI 重新生成：人物肖像 ────────────────────────────────────────────────
    async function regeneratePortrait(charName, charIdx, view) {
      const key = `portrait_${charIdx}_${view}`;
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portraits/${view}/regenerate`,
          { method: "POST" }
        );
        if (!res.ok) throw new Error(await res.text());
        const { task_id } = await res.json();
        startPoll(key, task_id, () => {
          imgTs.value[`portrait_${charName}_${view}`] = Date.now();
          showToast(`${charName} ${view} 肖像已重新生成`, "success");
        });
      } catch (e) {
        showToast("启动失败: " + e.message, "error");
      }
    }

    // ── 手动替换 Modal ───────────────────────────────────────────────────────
    function openFrameModal(shot, frameType) {
      modal.value = {
        title: `替换 Shot ${shot.idx} · ${frameType === "first" ? "首帧" : "末帧"}`,
        previewUrl: shot[`has_${frameType}_frame`] ? shotFileUrl(shot.idx, `${frameType}_frame.png`) : "",
        isPortrait: false,
        pendingFile: null,
        uploading: false,
        async upload() {
          if (!this.pendingFile) return;
          this.uploading = true;
          try {
            const form = new FormData();
            form.append("file", this.pendingFile);
            const res = await fetch(
              `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/frames/${frameType}`,
              { method: "POST", body: form }
            );
            if (!res.ok) throw new Error(await res.text());
            imgTs.value[`shot_${shot.idx}_${frameType}_frame.png`] = Date.now();
            shot[`has_${frameType}_frame`] = true;
            showToast("替换成功", "success");
            modal.value = null;
          } catch (e) {
            showToast("替换失败: " + e.message, "error");
          } finally { this.uploading = false; }
        }
      };
    }

    function openPortraitModal(charName, charIdx, view) {
      modal.value = {
        title: `替换 ${charName} · ${view} 肖像`,
        previewUrl: portraitUrl(charName, view),
        isPortrait: true,
        pendingFile: null,
        uploading: false,
        async upload() {
          if (!this.pendingFile) return;
          this.uploading = true;
          try {
            const form = new FormData();
            form.append("file", this.pendingFile);
            const res = await fetch(
              `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portraits/${view}`,
              { method: "POST", body: form }
            );
            if (!res.ok) throw new Error(await res.text());
            imgTs.value[`portrait_${charName}_${view}`] = Date.now();
            showToast("肖像替换成功", "success");
            modal.value = null;
          } catch (e) {
            showToast("替换失败: " + e.message, "error");
          } finally { this.uploading = false; }
        }
      };
    }

    // ── 参考场景 ─────────────────────────────────────────────────────────────
    async function addSceneRef(shotIdx, event) {
      const file = event.target.files[0];
      if (!file) return;
      event.target.value = "";
      try {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/shots/${shotIdx}/scene_refs`,
          { method: "POST", body: form }
        );
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        const shot = shots.value.find(s => s.idx === shotIdx);
        if (shot) shot.scene_refs.unshift({ filename: data.filename, path: data.path, readonly: false });
        showToast("场景图添加成功", "success");
      } catch (e) {
        showToast("添加失败: " + e.message, "error");
      }
    }

    async function deleteSceneRef(shotIdx, filename) {
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/shots/${shotIdx}/scene_refs/${enc(filename)}`,
          { method: "DELETE" }
        );
        if (!res.ok) throw new Error(await res.text());
        const shot = shots.value.find(s => s.idx === shotIdx);
        if (shot) shot.scene_refs = shot.scene_refs.filter(r => r.filename !== filename);
        showToast("已删除", "success");
      } catch (e) {
        showToast("删除失败: " + e.message, "error");
      }
    }

    // ── modal 通用 ───────────────────────────────────────────────────────────
    function onFileSelected(event) {
      const file = event.target.files[0];
      if (!file || !modal.value) return;
      modal.value.pendingFile = file;
      modal.value.previewUrl = URL.createObjectURL(file);
    }
    function triggerUploadInput() { document.getElementById("upload-input").click(); }
    function closeModal() { modal.value = null; }

    // ── toast ────────────────────────────────────────────────────────────────
    function showToast(msg, type = "info") {
      if (toastTimer) clearTimeout(toastTimer);
      toast.value = { msg, type };
      toastTimer = setTimeout(() => { toast.value = null; }, 4000);
    }

    init();

    return {
      projects, currentProject, activeTab, loading,
      characters, portraitsRegistry, shots, hasFinalVideo, metadata,
      expandedShots, editingDesc, lightboxUrl, openLightbox,
      modal, toast, imgTs, taskStatus,
      scriptFiles, currentScriptFile, scriptData, scriptLoading, newScriptPath,
      loadScript, addScript, isSectionRow,
      portraitUrl, shotFileUrl, finalVideoUrl, fileUrl,
      toggleShot, isShotExpanded,
      toggleDescEdit, isEditingDesc, saveDesc,
      visibleCharPortraits,
      regenerateFrame, regenerateVideo, regeneratePortrait,
      taskState, isRunning,
      openFrameModal, openPortraitModal,
      addSceneRef, deleteSceneRef,
      onFileSelected, triggerUploadInput, closeModal,
    };
  }
}).mount("#app");
