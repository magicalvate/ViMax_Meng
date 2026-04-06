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
    const portraitVersions = ref({});  // charIdx(str) -> {front:[...], side:[...], back:[...]}
    const shots = ref([]);
    const cameraTree = ref([]);
    const hasFinalVideo = ref(false);
    const metadata = ref({});

    const expandedShots = ref(new Set());
    const editingDesc = ref(new Set());
    const frameRefsExpanded = ref({});  // `${shotIdx}_${ftKey}` -> bool

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
    const taskStatus = reactive({});
    const _pollers = {};

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
        portraitVersions.value = data.portrait_versions || {};
        shots.value = data.shots || [];
        cameraTree.value = data.camera_tree || [];
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

    function isSectionRow(row) {
      const cells = row.cells;
      return cells[0] && cells.slice(1).every(c => !c);
    }

    // ── 机位 ─────────────────────────────────────────────────────────────────
    function shotCamera(shot) {
      const cidx = shot.description?.cam_idx;
      if (cidx == null) return null;
      return cameraTree.value.find(c => c.idx === cidx) || null;
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
      taskStatus[key] = { taskId, status: "running", status_msg: "启动中…", error_msg: null };
      _pollers[key] = setInterval(async () => {
        try {
          const r = await fetch(`/api/tasks/${taskId}`);
          const t = await r.json();
          taskStatus[key].status = t.status;
          if (t.status_msg !== undefined) taskStatus[key].status_msg = t.status_msg;
          if (t.preview_url) taskStatus[key].preview_url = t.preview_url;
          if (t.status === "done") {
            clearInterval(_pollers[key]);
            delete _pollers[key];
            onDone(t);
          } else if (t.status === "error") {
            clearInterval(_pollers[key]);
            delete _pollers[key];
            taskStatus[key].error_msg = t.error_msg || "未知错误";
            showToast("生成失败", "error");
          }
        } catch { /* ignore poll errors */ }
      }, 2000);
    }

    function taskState(key) { return taskStatus[key] || null; }
    function isRunning(key) { return taskStatus[key]?.status === "running"; }
    function taskMsg(key) { return taskStatus[key]?.status_msg || "生成中…"; }
    function taskError(key) { return taskStatus[key]?.error_msg || null; }
    function taskPreviewUrl(key) { return taskStatus[key]?.preview_url || null; }
    function clearTaskError(key) { if (taskStatus[key]) taskStatus[key].error_msg = null; }

    // ── 版本工具 ─────────────────────────────────────────────────────────────
    function formatVersionTime(isoStr) {
      if (!isoStr) return "";
      const d = new Date(isoStr);
      const pad = n => String(n).padStart(2, "0");
      return `${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    function shotVersionList(shot, asset) {
      return (shot.versions && shot.versions[asset]) || [];
    }

    function portraitVersionList(charIdx, view) {
      return (portraitVersions.value[String(charIdx)] || {})[view] || [];
    }

    async function refreshShotVersions(shot) {
      try {
        const res = await fetch(`/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/versions`);
        if (res.ok) shot.versions = await res.json();
      } catch {}
    }

    async function refreshPortraitVersions(charIdx) {
      try {
        const res = await fetch(`/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portraits/versions`);
        if (res.ok) {
          portraitVersions.value = { ...portraitVersions.value, [String(charIdx)]: await res.json() };
        }
      } catch {}
    }

    async function selectShotVersion(shot, asset, vid) {
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/versions/${asset}/${vid}/select`,
          { method: "POST" }
        );
        if (!res.ok) throw new Error(await res.text());
        await refreshShotVersions(shot);
        // 刷新活动图/视频
        const tsKey = asset === "video" ? `shot_${shot.idx}_video.mp4` : `shot_${shot.idx}_${asset}.png`;
        imgTs.value[tsKey] = Date.now();
        showToast("已切换版本", "success");
      } catch (e) {
        showToast("切换失败: " + e.message, "error");
      }
    }

    async function deleteShotVersion(shot, asset, vid) {
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/versions/${asset}/${vid}`,
          { method: "DELETE" }
        );
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        shot.versions = data.versions;
        if (data.was_selected) {
          const tsKey = asset === "video" ? `shot_${shot.idx}_video.mp4` : `shot_${shot.idx}_${asset}.png`;
          imgTs.value[tsKey] = Date.now();
          if (!shot.versions[asset] || shot.versions[asset].length === 0) {
            if (asset === "video") shot.has_video = false;
            else if (asset === "first_frame") shot.has_first_frame = false;
            else if (asset === "last_frame") shot.has_last_frame = false;
          }
        }
        showToast("版本已删除", "success");
      } catch (e) {
        showToast("删除失败: " + e.message, "error");
      }
    }

    async function selectPortraitVersion(charIdx, charName, view, vid) {
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portraits/${view}/versions/${vid}/select`,
          { method: "POST" }
        );
        if (!res.ok) throw new Error(await res.text());
        await refreshPortraitVersions(charIdx);
        imgTs.value[`portrait_${charName}_${view}`] = Date.now();
        showToast("已切换版本", "success");
      } catch (e) {
        showToast("切换失败: " + e.message, "error");
      }
    }

    async function deletePortraitVersion(charIdx, charName, view, vid) {
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portraits/${view}/versions/${vid}`,
          { method: "DELETE" }
        );
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        portraitVersions.value = {
          ...portraitVersions.value,
          [String(charIdx)]: { ...(portraitVersions.value[String(charIdx)] || {}), ...data.versions }
        };
        if (data.was_selected) imgTs.value[`portrait_${charName}_${view}`] = Date.now();
        showToast("版本已删除", "success");
      } catch (e) {
        showToast("删除失败: " + e.message, "error");
      }
    }

    // ── 帧参考图 ────────────────────────────────────────────────────────────
    function frameRefsList(shot, ftKey) {
      return (shot.frame_refs && shot.frame_refs[ftKey]) || [];
    }

    function toggleFrameRefs(shotIdx, ftKey) {
      const key = `${shotIdx}_${ftKey}`;
      frameRefsExpanded.value[key] = !frameRefsExpanded.value[key];
    }
    function isFrameRefsExpanded(shotIdx, ftKey) {
      return !!frameRefsExpanded.value[`${shotIdx}_${ftKey}`];
    }

    async function toggleFrameRef(shot, frameType, ref) {
      const newEnabled = !ref.enabled;
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/frames/${frameType}/refs`,
          { method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: ref.path, enabled: newEnabled }) }
        );
        if (!res.ok) throw new Error(await res.text());
        ref.enabled = newEnabled;
        showToast(newEnabled ? "参考图已启用" : "参考图已禁用（重生成时将排除）", "success");
      } catch (e) {
        showToast("操作失败: " + e.message, "error");
      }
    }

    async function refreshFrameRefs(shot, frameType) {
      const ftKey = `${frameType}_frame`;
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/frames/${frameType}/refs`
        );
        if (res.ok) {
          if (!shot.frame_refs) shot.frame_refs = {};
          shot.frame_refs[ftKey] = await res.json();
        }
      } catch {}
    }

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
        startPoll(key, task_id, async (t) => {
          const asset = `${frameType}_frame`;
          const tsKey = `shot_${shot.idx}_${asset}.png`;
          imgTs.value[tsKey] = Date.now();
          shot[`has_${frameType}_frame`] = true;
          shot[`${asset}_enabled`] = true;
          await refreshShotVersions(shot);
          await refreshFrameRefs(shot, frameType);
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
        startPoll(key, task_id, async () => {
          imgTs.value[`shot_${shot.idx}_video.mp4`] = Date.now();
          shot.has_video = true;
          await refreshShotVersions(shot);
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
        startPoll(key, task_id, async () => {
          imgTs.value[`portrait_${charName}_${view}`] = Date.now();
          await refreshPortraitVersions(charIdx);
          showToast(`${charName} ${view} 肖像已重新生成`, "success");
        });
      } catch (e) {
        showToast("启动失败: " + e.message, "error");
      }
    }

    // ── 启用/禁用帧 ─────────────────────────────────────────────────────────
    async function toggleFrameEnabled(shot, frameType) {
      const ft_key = `${frameType}_frame`;
      const newEnabled = !shot[`${ft_key}_enabled`];
      try {
        const res = await fetch(
          `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/frames/${frameType}/enabled`,
          { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: newEnabled }) }
        );
        if (!res.ok) throw new Error(await res.text());
        shot[`${ft_key}_enabled`] = newEnabled;
        showToast(`Shot ${shot.idx} ${frameType === "first" ? "首帧" : "末帧"}已${newEnabled ? "启用" : "禁用"}`, "success");
      } catch (e) {
        showToast("操作失败: " + e.message, "error");
      }
    }

    // ── 视频生成模式标签 ─────────────────────────────────────────────────────
    function videoModeLabel(shot) {
      const hasFF = shot.has_first_frame && shot.first_frame_enabled;
      const varType = shot.description?.variation_type;
      const hasLF = shot.has_last_frame && shot.last_frame_enabled && (varType === "medium" || varType === "large");
      if (hasFF && hasLF) return "首尾帧→视频";
      if (hasFF) return "首帧→视频";
      return "文生视频";
    }

    // ── 参考人物动态编辑 ─────────────────────────────────────────────────────
    const charPickerShot = ref(null);  // 当前展开选择器的 shot.idx

    function toggleCharPicker(shotIdx) {
      charPickerShot.value = charPickerShot.value === shotIdx ? null : shotIdx;
    }
    function isCharPickerOpen(shotIdx) { return charPickerShot.value === shotIdx; }

    function availableCharsToAdd(shot) {
      const desc = shot.description;
      if (!desc) return characters.value;
      const current = new Set([...(desc.ff_vis_char_idxs || []), ...(desc.lf_vis_char_idxs || [])]);
      return characters.value.filter(c => !current.has(c.idx));
    }

    async function _saveVisChars(shot, ffIdxs, lfIdxs) {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/description`,
        { method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ff_vis_char_idxs: ffIdxs, lf_vis_char_idxs: lfIdxs }) }
      );
      if (!res.ok) throw new Error(await res.text());
      const updated = await res.json();
      shot.description.ff_vis_char_idxs = updated.ff_vis_char_idxs;
      shot.description.lf_vis_char_idxs = updated.lf_vis_char_idxs;
    }

    async function addVisChar(shot, charIdx) {
      try {
        const desc = shot.description;
        const ff = [...new Set([...(desc.ff_vis_char_idxs || []), charIdx])];
        const lf = [...new Set([...(desc.lf_vis_char_idxs || []), charIdx])];
        await _saveVisChars(shot, ff, lf);
        charPickerShot.value = null;
      } catch (e) { showToast("添加失败: " + e.message, "error"); }
    }

    async function removeVisChar(shot, charIdx) {
      try {
        const desc = shot.description;
        const ff = (desc.ff_vis_char_idxs || []).filter(i => i !== charIdx);
        const lf = (desc.lf_vis_char_idxs || []).filter(i => i !== charIdx);
        await _saveVisChars(shot, ff, lf);
      } catch (e) { showToast("移除失败: " + e.message, "error"); }
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
      characters, portraitsRegistry, portraitVersions, shots, cameraTree, hasFinalVideo, metadata,
      expandedShots, editingDesc, lightboxUrl, openLightbox,
      modal, toast, imgTs, taskStatus,
      scriptFiles, currentScriptFile, scriptData, scriptLoading, newScriptPath,
      loadScript, addScript, isSectionRow,
      portraitUrl, shotFileUrl, finalVideoUrl, fileUrl,
      toggleShot, isShotExpanded,
      toggleDescEdit, isEditingDesc, saveDesc,
      visibleCharPortraits, shotCamera,
      regenerateFrame, regenerateVideo, regeneratePortrait,
      toggleFrameEnabled, videoModeLabel,
      taskState, isRunning, taskMsg, taskError, taskPreviewUrl, clearTaskError,
      openFrameModal, openPortraitModal,
      addSceneRef, deleteSceneRef,
      onFileSelected, triggerUploadInput, closeModal,
      // 版本管理
      shotVersionList, portraitVersionList,
      selectShotVersion, deleteShotVersion,
      selectPortraitVersion, deletePortraitVersion,
      formatVersionTime,
      // 参考人物编辑
      charPickerShot, toggleCharPicker, isCharPickerOpen,
      availableCharsToAdd, addVisChar, removeVisChar,
      // 帧参考图
      frameRefsExpanded, frameRefsList,
      toggleFrameRefs, isFrameRefsExpanded,
      toggleFrameRef, refreshFrameRefs,
    };
  }
}).mount("#app");
