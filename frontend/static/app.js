import { setupTasks } from './modules/tasks.js';
import { setupVersions } from './modules/versions.js';
import { setupShots } from './modules/shots.js';
import { setupCharacters } from './modules/characters.js';
import { setupScripts } from './modules/scripts.js';
import { setupPipeline } from './modules/pipeline.js';
const { createApp, ref, reactive, watch, provide } = Vue;

createApp({
  setup() {
    // ── 全局状态 ────────────────────────────────────────────────────────────
    const projects = ref([]);
    const currentProject = ref("");
    const activeTab = ref("extract_characters");
    const loading = ref(false);

    const characters = ref([]);
    const portraitsRegistry = ref({});
    const portraitVersions = ref({});
    const shots = ref([]);
    const cameraTree = ref([]);
    const hasFinalVideo = ref(false);
    const metadata = ref({});

    const taskStatus = reactive({});
    const imgTs = ref({});
    const lightboxUrl = ref(null);

    const scriptFiles = ref([]);
    const currentScriptFile = ref("");
    const scriptData = ref(null);
    const scriptLoading = ref(false);
    const newScriptPath = ref("");

    // toast
    const toast = ref(null);
    let toastTimer = null;
    function showToast(msg, type = "info") {
      if (toastTimer) clearTimeout(toastTimer);
      toast.value = { msg, type };
      toastTimer = setTimeout(() => { toast.value = null; }, 4000);
    }

    // ── URL 工具 ─────────────────────────────────────────────────────────────
    function enc(s) { return encodeURIComponent(s); }

    function fileUrl(relPath, tsKey) {
      if (!relPath) return "";
      const path = relPath.replace(/\\/g, "/").replace(/^\.working_dir\/[^/]+\//, "");
      const ts = tsKey ? (imgTs.value[tsKey] || "") : "";
      return `/files/${enc(currentProject.value)}/${path}${ts ? `?t=${ts}` : ""}`;
    }

    function shotFileUrl(shotIdx, filename) {
      const ts = imgTs.value[`shot_${shotIdx}_${filename}`] || "";
      return `/files/${enc(currentProject.value)}/shots/${shotIdx}/${filename}${ts ? `?t=${ts}` : ""}`;
    }

    function finalVideoUrl() {
      return `/files/${enc(currentProject.value)}/final_video.mp4`;
    }

    function openLightbox(url) { if (url) lightboxUrl.value = url; }

    // ── 初始化模块 ───────────────────────────────────────────────────────────
    const tasks = setupTasks({ taskStatus, showToast });
    const { startPoll } = tasks;

    const versions = setupVersions({ currentProject, portraitVersions, imgTs, enc, showToast });
    const { refreshShotVersions, refreshPortraitVersions } = versions;

    const shotsModule = setupShots({
      currentProject, shots, characters, portraitsRegistry, imgTs,
      enc, shotFileUrl, portraitUrl: () => {}, showToast,
      startPoll, refreshShotVersions,
    });
    const { modal } = shotsModule;

    const charsModule = setupCharacters({
      currentProject, portraitsRegistry, imgTs, modal,
      enc, showToast, startPoll, refreshPortraitVersions,
    });

    const scriptsModule = setupScripts({
      currentProject, scriptFiles, currentScriptFile, scriptData,
      scriptLoading, newScriptPath, enc, showToast, characters,
    });

    // ── 加载项目 ─────────────────────────────────────────────────────────────
    async function loadProject(name) {
      loading.value = true;
      shotsModule.expandedShots.value = new Set();
      shotsModule.editingDesc.value = new Set();
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
        pipelineModule.storyboard.value = data.storyboard || [];
        pipelineModule.userRequirement.value = metadata.value.user_requirement || "";
        await scriptsModule.loadScriptFiles();
        pipelineModule.fetchStagesStatus();
      } finally {
        loading.value = false;
      }
    }

    const pipelineModule = setupPipeline({
      currentProject, shots, cameraTree, metadata, enc, showToast, loadProject,
    });

    async function init() {
      const res = await fetch("/api/projects");
      projects.value = await res.json();
      if (projects.value.length > 0) currentProject.value = projects.value[0];
    }

    watch(currentProject, val => { if (val) loadProject(val); });
    watch(activeTab, val => {
      if (val === 'extract_characters') {
        pipelineModule.loadAvailableApis();
        pipelineModule.loadApiConfig();
      }
      pipelineModule.fetchStagesStatus();
    });

    // ── 辅助查询 ─────────────────────────────────────────────────────────────
    function shotCamera(shot) {
      const cidx = shot.description?.cam_idx;
      if (cidx == null) return null;
      return cameraTree.value.find(c => c.idx === cidx) || null;
    }

    function visibleCharPortraits(shot) {
      const desc = shot.description;
      if (!desc) return [];
      const idxSet = new Set([...(desc.ff_vis_char_idxs || []), ...(desc.lf_vis_char_idxs || [])]);
      return Array.from(idxSet).map(cidx => {
        const char = characters.value.find(c => c.idx === cidx);
        return char ? { charName: char.identifier_in_scene, charIdx: cidx } : null;
      }).filter(Boolean);
    }

    init();

    const appState = {
      // 状态
      projects, currentProject, activeTab, loading,
      characters, portraitsRegistry, portraitVersions, shots, cameraTree, hasFinalVideo, metadata,
      imgTs, lightboxUrl, openLightbox, toast, taskStatus,
      scriptFiles, currentScriptFile, scriptData, scriptLoading, newScriptPath,
      // URL 工具
      fileUrl, shotFileUrl, finalVideoUrl,
      // 辅助
      shotCamera, visibleCharPortraits,
      // tasks
      ...tasks,
      // versions
      ...versions,
      // shots
      ...shotsModule,
      // characters
      ...charsModule,
      // scripts
      ...scriptsModule,
      // pipeline
      ...pipelineModule,
    };
    provide('app', appState);
    return appState;
  },
}).mount("#app");
