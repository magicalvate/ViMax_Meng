export function setupTasks({ taskStatus, showToast }) {
  const _pollers = {};

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

  return { startPoll, taskState, isRunning, taskMsg, taskError, taskPreviewUrl, clearTaskError };
}
