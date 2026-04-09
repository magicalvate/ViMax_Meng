const { ref } = Vue;

export function setupShots({
  currentProject, shots, characters, portraitsRegistry, imgTs,
  enc, shotFileUrl, portraitUrl, showToast,
  startPoll, refreshShotVersions, availableApis,
}) {
  const expandedShots = ref(new Set());
  const frameImageModelOverride = ref("");
  const videoModelOverride = ref("");
  const editingDesc = ref(new Set());
  const frameRefsExpanded = ref({});
  const charPickerShot = ref(null);
  const modal = ref(null);

  // ── Shot 折叠 / 描述编辑 ────────────────────────────────────────────────────
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

  // ── 帧参考图 ────────────────────────────────────────────────────────────────
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

  // ── AI 重新生成 ──────────────────────────────────────────────────────────────
  function _frameModelOverrideBody() {
    const api = availableApis?.value?.image_generator?.find(a => a.class_path === frameImageModelOverride.value);
    if (!api) return {};
    return { model_override: { image_generator: { class_path: api.class_path, init_args: { model: api.model } } } };
  }

  function _videoModelOverrideBody() {
    const api = availableApis?.value?.video_generator?.find(a => a.class_path === videoModelOverride.value);
    if (!api) return {};
    return { model_override: { video_generator: { class_path: api.class_path, init_args: { t2v_model: api.t2v_model } } } };
  }

  async function regenerateFrame(shot, frameType) {
    const key = `frame_${shot.idx}_${frameType}`;
    try {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/regenerate/frame/${frameType}`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(_frameModelOverrideBody()) }
      );
      if (!res.ok) throw new Error(await res.text());
      const { task_id } = await res.json();
      startPoll(key, task_id, async () => {
        const asset = `${frameType}_frame`;
        imgTs.value[`shot_${shot.idx}_${asset}.png`] = Date.now();
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

  async function regenerateVideo(shot) {
    const key = `video_${shot.idx}`;
    try {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/shots/${shot.idx}/regenerate/video`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(_videoModelOverrideBody()) }
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

  function videoModeLabel(shot) {
    const hasFF = shot.has_first_frame && shot.first_frame_enabled;
    const varType = shot.description?.variation_type;
    const hasLF = shot.has_last_frame && shot.last_frame_enabled && (varType === "medium" || varType === "large");
    if (hasFF && hasLF) return "首尾帧→视频";
    if (hasFF) return "首帧→视频";
    return "文生视频";
  }

  // ── 参考人物 ─────────────────────────────────────────────────────────────────
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

  // ── 参考场景 ─────────────────────────────────────────────────────────────────
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

  // ── 替换帧 Modal ──────────────────────────────────────────────────────────────
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

  function onFileSelected(event) {
    const file = event.target.files[0];
    if (!file || !modal.value) return;
    modal.value.pendingFile = file;
    modal.value.previewUrl = URL.createObjectURL(file);
  }
  function triggerUploadInput() { document.getElementById("upload-input").click(); }
  function closeModal() { modal.value = null; }

  return {
    expandedShots, editingDesc, frameRefsExpanded, charPickerShot, modal,
    frameImageModelOverride, videoModelOverride,
    toggleShot, isShotExpanded,
    toggleDescEdit, isEditingDesc, saveDesc,
    frameRefsList, toggleFrameRefs, isFrameRefsExpanded, toggleFrameRef, refreshFrameRefs,
    regenerateFrame, regenerateVideo, toggleFrameEnabled, videoModeLabel,
    toggleCharPicker, isCharPickerOpen, availableCharsToAdd, addVisChar, removeVisChar,
    addSceneRef, deleteSceneRef,
    openFrameModal, onFileSelected, triggerUploadInput, closeModal,
  };
}
