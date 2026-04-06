export function setupScripts({ currentProject, scriptFiles, currentScriptFile, scriptData, scriptLoading, newScriptPath, enc, showToast }) {
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

  async function uploadScript(event) {
    const file = event.target.files[0];
    if (!file) return;
    event.target.value = "";
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`/api/projects/${enc(currentProject.value)}/scripts/upload`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      scriptFiles.value = data.script_files;
      loadScript(data.path);
      showToast("脚本已上传", "success");
    } catch (e) {
      showToast("上传失败: " + e.message, "error");
    }
  }

  function isSectionRow(row) {
    const cells = row.cells;
    return cells[0] && cells.slice(1).every(c => !c);
  }

  return { loadScriptFiles, loadScript, addScript, uploadScript, isSectionRow };
}
