export function setupCharacters({
  currentProject, portraitsRegistry, imgTs, modal,
  enc, showToast, startPoll, refreshPortraitVersions,
}) {
  function portraitUrl(charName, view) {
    const reg = portraitsRegistry.value[charName];
    if (!reg?.[view]) return "";
    const raw = reg[view].path.replace(/\\/g, "/");
    const inner = raw.split("/").slice(2).join("/");
    const ts = imgTs.value[`portrait_${charName}_${view}`] || "";
    return `/files/${enc(currentProject.value)}/${inner}${ts ? `?t=${ts}` : ""}`;
  }

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

  return { portraitUrl, regeneratePortrait, openPortraitModal };
}
