export function setupVersions({ currentProject, portraitVersions, imgTs, enc, showToast }) {
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

  return {
    formatVersionTime, shotVersionList, portraitVersionList,
    refreshShotVersions, refreshPortraitVersions,
    selectShotVersion, deleteShotVersion,
    selectPortraitVersion, deletePortraitVersion,
  };
}
