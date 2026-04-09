export function setupCharacters({
  currentProject, portraitsRegistry, portraitRefs, portraitBundleVersions, imgTs, modal,
  enc, showToast, startPoll, refreshPortraitVersions, availableApis,
}) {
  const { ref } = Vue;
  const bundlePreviewTs = ref({});
  const charImageModelOverride = ref("");
  function portraitUrl(charName, view) {
    const reg = portraitsRegistry.value[charName];
    if (!reg?.[view]) return "";
    const raw = reg[view].path.replace(/\\/g, "/");
    const inner = raw.split("/").slice(2).join("/");
    const ts = imgTs.value[`portrait_${charName}_${view}`] || "";
    return `/files/${enc(currentProject.value)}/${inner}${ts ? `?t=${ts}` : ""}`;
  }

  function _imageModelOverrideBody() {
    const api = availableApis.value.image_generator.find(a => a.class_path === charImageModelOverride.value);
    if (!api) return {};
    return { model_override: { image_generator: { class_path: api.class_path, init_args: { model: api.model } } } };
  }

  async function regeneratePortrait(charName, charIdx, view) {
    const key = `portrait_${charIdx}_${view}`;
    try {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portraits/${view}/regenerate`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(_imageModelOverrideBody()) }
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

  async function regenerateCharacterAll(charName, charIdx) {
    const key = `portrait_all_${charIdx}`;
    try {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portraits/regenerate_all`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(_imageModelOverrideBody()) }
      );
      if (!res.ok) throw new Error(await res.text());
      const { task_id } = await res.json();
      startPoll(key, task_id, async () => {
        const ts = Date.now();
        for (const view of ["front", "side", "back"]) {
          imgTs.value[`portrait_${charName}_${view}`] = ts;
        }
        await refreshPortraitVersions(charIdx);
        showToast(`${charName} 全部肖像已重新生成`, "success");
      });
    } catch (e) {
      showToast("启动失败: " + e.message, "error");
    }
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

  // ── 参考图 ──────────────────────────────────────────────────────────────────
  function charPortraitRefs(charIdx) {
    return portraitRefs.value[String(charIdx)] || [];
  }

  async function addPortraitRef(charIdx, event) {
    const file = event.target.files[0];
    if (!file) return;
    event.target.value = "";
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portrait_refs`,
        { method: "POST", body: form }
      );
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (!portraitRefs.value[String(charIdx)]) portraitRefs.value[String(charIdx)] = [];
      portraitRefs.value[String(charIdx)].push(data);
      showToast("参考图已添加", "success");
    } catch (e) {
      showToast("添加失败: " + e.message, "error");
    }
  }

  async function togglePortraitRef(charIdx, ref) {
    const newEnabled = !ref.enabled;
    try {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portrait_refs/${enc(ref.filename)}/enabled`,
        { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: newEnabled }) }
      );
      if (!res.ok) throw new Error(await res.text());
      ref.enabled = newEnabled;
    } catch (e) {
      showToast("操作失败: " + e.message, "error");
    }
  }

  async function deletePortraitRef(charIdx, ref) {
    try {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portrait_refs/${enc(ref.filename)}`,
        { method: "DELETE" }
      );
      if (!res.ok) throw new Error(await res.text());
      portraitRefs.value[String(charIdx)] = charPortraitRefs(charIdx).filter(r => r.filename !== ref.filename);
      showToast("已删除", "success");
    } catch (e) {
      showToast("删除失败: " + e.message, "error");
    }
  }

  // ── Bundle 版本 ──────────────────────────────────────────────────────────────
  function charBundleVersions(charIdx) {
    return portraitBundleVersions.value[String(charIdx)] || [];
  }

  async function savePortraitBundle(charIdx) {
    try {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portrait_bundle_versions`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(await res.text());
      portraitBundleVersions.value[String(charIdx)] = await res.json();
      showToast("版本快照已保存", "success");
    } catch (e) {
      showToast("保存失败: " + e.message, "error");
    }
  }

  async function selectPortraitBundle(charIdx, charName, vid) {
    try {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portrait_bundle_versions/${vid}/select`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(await res.text());
      portraitBundleVersions.value[String(charIdx)] = await res.json();
      const ts = Date.now();
      for (const view of ["front", "side", "back"]) {
        imgTs.value[`portrait_${charName}_${view}`] = ts;
      }
      bundlePreviewTs.value[`${charIdx}_${vid}`] = ts;
      showToast("已切换到此版本", "success");
    } catch (e) {
      showToast("切换失败: " + e.message, "error");
    }
  }

  async function updatePortraitBundle(charIdx, charName, vid) {
    try {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portrait_bundle_versions/${vid}`,
        { method: "PUT" }
      );
      if (!res.ok) throw new Error(await res.text());
      portraitBundleVersions.value[String(charIdx)] = await res.json();
      bundlePreviewTs.value[`${charIdx}_${vid}`] = Date.now();
      showToast("快照已更新为当前肖像", "success");
    } catch (e) {
      showToast("更新失败: " + e.message, "error");
    }
  }

  async function deletePortraitBundle(charIdx, charName, vid) {
    try {
      const res = await fetch(
        `/api/projects/${enc(currentProject.value)}/characters/${charIdx}/portrait_bundle_versions/${vid}`,
        { method: "DELETE" }
      );
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      portraitBundleVersions.value[String(charIdx)] = data.entries;
      if (data.was_selected) {
        for (const view of ["front", "side", "back"]) {
          imgTs.value[`portrait_${charName}_${view}`] = Date.now();
        }
      }
      showToast("版本已删除", "success");
    } catch (e) {
      showToast("删除失败: " + e.message, "error");
    }
  }

  return {
    charImageModelOverride,
    portraitUrl, regeneratePortrait, regenerateCharacterAll, openPortraitModal,
    charPortraitRefs, addPortraitRef, togglePortraitRef, deletePortraitRef,
    bundlePreviewTs,
    charBundleVersions, savePortraitBundle, selectPortraitBundle, updatePortraitBundle, deletePortraitBundle,
  };
}
