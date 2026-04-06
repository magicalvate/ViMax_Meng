const { inject } = Vue;

export default {
  name: 'PipelineTab',
  setup() { return inject('app'); },
  template: `
<div class="pipeline-panel">

  <!-- API 配置面板 -->
  <div class="api-config-panel" style="margin-bottom:20px;border:1px solid #2d3148;border-radius:8px;padding:16px;background:#1a1d27">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
      <h3 style="margin:0;font-size:14px;flex:1">⚙️ API 配置</h3>
      <button class="btn btn-primary" style="padding:4px 12px;font-size:12px" @click="loadAvailableApis(); loadApiConfig()">刷新</button>
      <button class="btn btn-ghost" style="padding:4px 12px;font-size:12px" @click="toggleApiPanel">{{ showApiPanel ? '收起' : '展开' }}</button>
    </div>

    <div v-if="showApiPanel" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px">
      <!-- 图片生成器选择 -->
      <div style="border:1px solid #252840;border-radius:6px;padding:12px;background:#252840">
        <label style="display:block;font-size:12px;color:#64748b;margin-bottom:8px;font-weight:600">图片生成器</label>
        <select v-model="apiConfigModel.image_generator.class_path" style="width:100%;padding:6px;background:#1a1d27;border:1px solid #3d4266;border-radius:4px;color:#e2e8f0;font-size:12px">
          <option value="">默认</option>
          <option v-for="api in availableApis.image_generator" :key="api.class_path + api.model" :value="api.class_path">
            {{ api.name }}
          </option>
        </select>
        <div style="margin-top:8px;max-height:100px;overflow:auto;font-size:11px;color:#94a3b8">
          <div v-if="apiConfigModel.image_generator.class_path">
            选中: {{ availableApis.image_generator.find(a => a.class_path === apiConfigModel.image_generator.class_path)?.name }}
          </div>
        </div>
      </div>

      <!-- 视频生成器选择 -->
      <div style="border:1px solid #252840;border-radius:6px;padding:12px;background:#252840">
        <label style="display:block;font-size:12px;color:#64748b;margin-bottom:8px;font-weight:600">视频生成器</label>
        <select v-model="apiConfigModel.video_generator.class_path" style="width:100%;padding:6px;background:#1a1d27;border:1px solid #3d4266;border-radius:4px;color:#e2e8f0;font-size:12px">
          <option value="">默认</option>
          <option v-for="api in availableApis.video_generator" :key="api.class_path + api.t2v_model" :value="api.class_path">
            {{ api.name }}
          </option>
        </select>
        <div style="margin-top:8px;max-height:100px;overflow:auto;font-size:11px;color:#94a3b8">
          <div v-if="apiConfigModel.video_generator.class_path">
            选中: {{ availableApis.video_generator.find(a => a.class_path === apiConfigModel.video_generator.class_path)?.name }}
          </div>
        </div>
      </div>

      <!-- 聊天模型选择 -->
      <div style="border:1px solid #252840;border-radius:6px;padding:12px;background:#252840">
        <label style="display:block;font-size:12px;color:#64748b;margin-bottom:8px;font-weight:600">聊天模型</label>
        <select v-model="apiConfigModel.chat_model.model" style="width:100%;padding:6px;background:#1a1d27;border:1px solid #3d4266;border-radius:4px;color:#e2e8f0;font-size:12px">
          <option value="">默认</option>
          <option v-for="api in availableApis.chat_model" :key="api.model + api.base_url" :value="api.model">
            {{ api.name }}
          </option>
        </select>
        <div style="margin-top:8px;max-height:100px;overflow:auto;font-size:11px;color:#94a3b8">
          <div v-if="apiConfigModel.chat_model.model">
            选中: {{ availableApis.chat_model.find(a => a.model === apiConfigModel.chat_model.model)?.name }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="showApiPanel" style="margin-top:12px;display:flex;gap:8px;justify-content:flex-end">
      <button class="btn btn-ghost" @click="loadApiConfig">取消</button>
      <button class="btn btn-primary" @click="saveApiConfig">保存配置</button>
    </div>
  </div>

  <!-- ① 提取角色 -->
  <div class="pipeline-stage-card" :class="{done: stagesStatus.extract_characters?.done, running: isStageRunning('extract_characters')}">
    <div class="pipeline-stage-header" @click="toggleStageExpanded('extract_characters')">
      <span class="pipeline-stage-icon">
        <span v-if="isStageRunning('extract_characters')" class="spinner"></span>
        <span v-else-if="stagesStatus.extract_characters?.done" class="done-icon">&#10003;</span>
        <span v-else class="stage-pending-icon">&#9675;</span>
      </span>
      <div class="pipeline-stage-info">
        <span class="pipeline-stage-name">&#9312; 提取角色</span>
        <span class="pipeline-stage-detail">{{ stagesStatus.extract_characters?.done ? stagesStatus.extract_characters.count + ' 个角色' : '未完成' }}</span>
      </div>
      <span class="chevron" :class="{open: stageExpanded.extract_characters}">&#9662;</span>
    </div>
    <div class="pipeline-running-bar" v-if="isStageRunning('extract_characters')">{{ stageTaskMsg('extract_characters') }}</div>
    <div class="pipeline-stage-error" v-if="stageTaskError('extract_characters')">{{ stageTaskError('extract_characters') }}</div>
    <div class="pipeline-io" v-if="stageExpanded.extract_characters">
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输入 · 脚本文件</div>
        <div v-if="scriptFiles.length === 0" class="pipeline-io-empty">尚未添加脚本</div>
        <div class="script-file-list" v-if="scriptFiles.length > 0" style="margin-bottom:8px">
          <button v-for="sf in scriptFiles" :key="sf" class="script-file-btn"
            :class="{active: currentScriptFile===sf}" @click="loadScript(sf)">{{ sf.split('/').pop() }}</button>
        </div>
        <div class="script-add" style="margin-bottom:10px">
          <label class="btn btn-primary" style="cursor:pointer">
            选择脚本文件
            <input type="file" accept=".txt,.md,.docx" @change="uploadScript($event)" style="display:none" />
          </label>
        </div>
        <div v-if="scriptLoading" class="loading" style="padding:8px 0">解析中...</div>
        <div v-else-if="scriptData && scriptData.type==='text'" class="script-text-wrap" style="max-height:300px;overflow:auto">
          <h4 class="script-title" style="margin:0 0 6px">{{ scriptData.filename }}</h4>
          <pre class="script-text" style="font-size:12px">{{ scriptData.content }}</pre>
        </div>
        <div v-else-if="scriptData && scriptData.type==='docx'" class="script-docx-wrap" style="max-height:300px;overflow:auto">
          <h4 class="script-title" style="margin:0 0 6px">{{ scriptData.title || scriptData.filename }}</h4>
          <div class="script-table-wrap" v-for="(tbl, ti) in scriptData.tables" :key="ti">
            <table class="script-table">
              <thead>
                <tr v-if="tbl[0] && tbl[0].is_header">
                  <th v-for="(cell, ci) in tbl[0].cells" :key="ci">{{ cell }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, ri) in tbl.slice(1)" :key="ri" :class="{'section-row': isSectionRow(row)}">
                  <td v-for="(cell, ci) in row.cells" :key="ci">{{ cell }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输出 · 角色列表</div>
        <div v-if="characters.length === 0" class="pipeline-io-empty">尚未生成</div>
        <div v-for="char in characters" :key="char.idx" class="char-io-row">
          <span class="char-io-name">{{ char.identifier_in_scene }}</span>
          <span class="char-io-feat">外貌：{{ char.static_features }}</span>
          <span class="char-io-feat">服饰：{{ char.dynamic_features }}</span>
        </div>
      </div>
    </div>
    <div class="pipeline-stage-actions">
      <button class="btn btn-primary pipeline-run-btn" :disabled="isStageRunning('extract_characters')" @click="runStage('extract_characters', false)">
        {{ isStageRunning('extract_characters') ? '运行中…' : (stagesStatus.extract_characters?.done ? '重新运行' : '运行') }}
      </button>
      <button class="btn btn-ghost pipeline-force-btn" :disabled="isStageRunning('extract_characters')" @click="runStage('extract_characters', true)">强制重跑</button>
    </div>
  </div>

  <!-- ② 生成角色肖像 -->
  <div class="pipeline-stage-card" :class="{done: stagesStatus.generate_portraits?.done, running: isStageRunning('generate_portraits')}">
    <div class="pipeline-stage-header" @click="toggleStageExpanded('generate_portraits')">
      <span class="pipeline-stage-icon">
        <span v-if="isStageRunning('generate_portraits')" class="spinner"></span>
        <span v-else-if="stagesStatus.generate_portraits?.done" class="done-icon">&#10003;</span>
        <span v-else class="stage-pending-icon">&#9675;</span>
      </span>
      <div class="pipeline-stage-info">
        <span class="pipeline-stage-name">&#9313; 生成角色肖像</span>
        <span class="pipeline-stage-detail">{{ stagesStatus.generate_portraits?.done ? stagesStatus.generate_portraits.count + ' 张肖像' : '未完成' }}</span>
      </div>
      <span class="chevron" :class="{open: stageExpanded.generate_portraits}">&#9662;</span>
    </div>
    <div class="pipeline-running-bar" v-if="isStageRunning('generate_portraits')">{{ stageTaskMsg('generate_portraits') }}</div>
    <div class="pipeline-stage-error" v-if="stageTaskError('generate_portraits')">{{ stageTaskError('generate_portraits') }}</div>
    <div class="pipeline-io" v-if="stageExpanded.generate_portraits">
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输入 · 角色 & 风格</div>
        <div v-if="characters.length === 0" class="pipeline-io-empty">角色列表为空，请先运行①</div>
        <div v-for="char in characters" :key="char.idx" class="pipeline-io-tag">{{ char.identifier_in_scene }}</div>
        <div class="pipeline-io-row" style="margin-top:8px">
          <span class="pipeline-io-label">风格 (style)：</span>
          <input class="pipeline-meta-input" v-model="metadata.style" placeholder="输入画面风格…" style="width:100%" />
          <button class="btn btn-ghost" style="margin-top:4px" @click="saveMetadataField('style', metadata.style)">保存风格</button>
        </div>
      </div>
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输出 · 角色肖像（front / side / back）</div>
        <div v-if="characters.length === 0" class="pipeline-io-empty">尚未生成</div>
        <div v-for="char in characters" :key="char.idx" class="portrait-io-row">
          <span class="portrait-io-name">{{ char.identifier_in_scene }}</span>
          <div class="portrait-io-imgs">
            <div v-for="view in ['front','side','back']" :key="view" class="portrait-io-item">
              <img :src="portraitUrl(char.identifier_in_scene, view)" @error="$event.target.style.opacity='0.1'" @click="openLightbox(portraitUrl(char.identifier_in_scene, view))" />
              <span>{{ view }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="pipeline-stage-actions">
      <button class="btn btn-primary pipeline-run-btn" :disabled="isStageRunning('generate_portraits')" @click="runStage('generate_portraits', false)">
        {{ isStageRunning('generate_portraits') ? '运行中…' : (stagesStatus.generate_portraits?.done ? '重新运行' : '运行') }}
      </button>
      <button class="btn btn-ghost pipeline-force-btn" :disabled="isStageRunning('generate_portraits')" @click="runStage('generate_portraits', true)">强制重跑</button>
    </div>
  </div>

  <!-- ③ 分镜设计 -->
  <div class="pipeline-stage-card" :class="{done: stagesStatus.design_storyboard?.done, running: isStageRunning('design_storyboard')}">
    <div class="pipeline-stage-header" @click="toggleStageExpanded('design_storyboard')">
      <span class="pipeline-stage-icon">
        <span v-if="isStageRunning('design_storyboard')" class="spinner"></span>
        <span v-else-if="stagesStatus.design_storyboard?.done" class="done-icon">&#10003;</span>
        <span v-else class="stage-pending-icon">&#9675;</span>
      </span>
      <div class="pipeline-stage-info">
        <span class="pipeline-stage-name">&#9314; 分镜设计</span>
        <span class="pipeline-stage-detail">{{ stagesStatus.design_storyboard?.done ? stagesStatus.design_storyboard.count + ' 个镜头' : '未完成' }}</span>
      </div>
      <span class="chevron" :class="{open: stageExpanded.design_storyboard}">&#9662;</span>
    </div>
    <div class="pipeline-running-bar" v-if="isStageRunning('design_storyboard')">{{ stageTaskMsg('design_storyboard') }}</div>
    <div class="pipeline-stage-error" v-if="stageTaskError('design_storyboard')">{{ stageTaskError('design_storyboard') }}</div>
    <div class="pipeline-io" v-if="stageExpanded.design_storyboard">
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输入 · 脚本 & 用户需求</div>
        <div v-for="sf in scriptFiles" :key="sf" class="pipeline-io-file"><span class="file-icon">&#128196;</span>{{ sf.split('/').pop() }}</div>
        <div class="pipeline-io-row" style="margin-top:8px">
          <span class="pipeline-io-label">user_requirement：</span>
          <span class="pipeline-io-value">{{ userRequirement || '（未填写）' }}</span>
        </div>
        <textarea class="pipeline-meta-input" v-model="userRequirement" rows="2" placeholder="例如：Fast-paced, no more than 15 shots" style="margin-top:8px;width:100%"></textarea>
        <button class="btn btn-ghost" style="margin-top:6px" @click="saveUserRequirement">保存需求</button>
      </div>
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输出 · 分镜列表</div>
        <div v-if="storyboard.length === 0" class="pipeline-io-empty">尚未生成</div>
        <div v-for="shot in storyboard" :key="shot.idx" class="storyboard-io-row">
          <div class="storyboard-io-header">
            <span class="shot-num" style="font-size:11px">Shot {{ shot.idx }}</span>
            <span class="cam-badge" style="font-size:11px">机位 {{ shot.cam_idx }}</span>
          </div>
          <p class="storyboard-io-visual">{{ shot.visual_desc }}</p>
          <p class="storyboard-io-audio" v-if="shot.audio_desc">&#128266; {{ shot.audio_desc }}</p>
        </div>
      </div>
    </div>
    <div class="pipeline-stage-actions">
      <button class="btn btn-primary pipeline-run-btn" :disabled="isStageRunning('design_storyboard')" @click="runStage('design_storyboard', false)">
        {{ isStageRunning('design_storyboard') ? '运行中…' : (stagesStatus.design_storyboard?.done ? '重新运行' : '运行') }}
      </button>
      <button class="btn btn-ghost pipeline-force-btn" :disabled="isStageRunning('design_storyboard')" @click="runStage('design_storyboard', true)">强制重跑</button>
    </div>
  </div>

  <!-- ④ 视觉描述拆解 -->
  <div class="pipeline-stage-card" :class="{done: stagesStatus.decompose_descriptions?.done, running: isStageRunning('decompose_descriptions')}">
    <div class="pipeline-stage-header" @click="toggleStageExpanded('decompose_descriptions')">
      <span class="pipeline-stage-icon">
        <span v-if="isStageRunning('decompose_descriptions')" class="spinner"></span>
        <span v-else-if="stagesStatus.decompose_descriptions?.done" class="done-icon">&#10003;</span>
        <span v-else class="stage-pending-icon">&#9675;</span>
      </span>
      <div class="pipeline-stage-info">
        <span class="pipeline-stage-name">&#9315; 视觉描述拆解</span>
        <span class="pipeline-stage-detail">{{ stagesStatus.decompose_descriptions?.shots_done }}/{{ stagesStatus.decompose_descriptions?.shots_total }} 个镜头</span>
      </div>
      <span class="chevron" :class="{open: stageExpanded.decompose_descriptions}">&#9662;</span>
    </div>
    <div class="pipeline-running-bar" v-if="isStageRunning('decompose_descriptions')">{{ stageTaskMsg('decompose_descriptions') }}</div>
    <div class="pipeline-stage-error" v-if="stageTaskError('decompose_descriptions')">{{ stageTaskError('decompose_descriptions') }}</div>
    <div class="pipeline-io" v-if="stageExpanded.decompose_descriptions">
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输入 · 分镜（storyboard）</div>
        <div v-if="storyboard.length === 0" class="pipeline-io-empty">分镜为空，请先运行③</div>
        <div v-else class="pipeline-io-summary">{{ storyboard.length }} 个分镜 × {{ characters.length }} 个角色</div>
      </div>
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输出 · 首帧 / 末帧 / 运动描述</div>
        <div v-if="shots.filter(s=>s.description).length === 0" class="pipeline-io-empty">尚未生成</div>
        <div v-for="shot in shots.filter(s=>s.description)" :key="shot.idx" class="decomp-io-row">
          <div class="decomp-io-header">
            <span class="shot-num" style="font-size:11px">Shot {{ shot.idx }}</span>
            <span class="variation-badge" :class="shot.description.variation_type" style="font-size:10px">{{ shot.description.variation_type }}</span>
            <span class="cam-badge" style="font-size:11px">机位 {{ shot.description.cam_idx }}</span>
          </div>
          <div class="decomp-io-fields">
            <div class="decomp-io-field"><span class="decomp-io-label">首帧</span><span>{{ shot.description.ff_desc }}</span></div>
            <div class="decomp-io-field" v-if="shot.description.variation_type !== 'small'"><span class="decomp-io-label">末帧</span><span>{{ shot.description.lf_desc }}</span></div>
            <div class="decomp-io-field"><span class="decomp-io-label">运动</span><span>{{ shot.description.motion_desc }}</span></div>
            <div class="decomp-io-field" v-if="shot.description.audio_desc"><span class="decomp-io-label">音频</span><span>{{ shot.description.audio_desc }}</span></div>
          </div>
        </div>
      </div>
    </div>
    <div class="pipeline-stage-actions">
      <button class="btn btn-primary pipeline-run-btn" :disabled="isStageRunning('decompose_descriptions')" @click="runStage('decompose_descriptions', false)">
        {{ isStageRunning('decompose_descriptions') ? '运行中…' : (stagesStatus.decompose_descriptions?.done ? '重新运行' : '运行') }}
      </button>
      <button class="btn btn-ghost pipeline-force-btn" :disabled="isStageRunning('decompose_descriptions')" @click="runStage('decompose_descriptions', true)">强制重跑</button>
    </div>
  </div>

  <!-- ⑤ 构建相机树 -->
  <div class="pipeline-stage-card" :class="{done: stagesStatus.construct_camera_tree?.done, running: isStageRunning('construct_camera_tree')}">
    <div class="pipeline-stage-header" @click="toggleStageExpanded('construct_camera_tree')">
      <span class="pipeline-stage-icon">
        <span v-if="isStageRunning('construct_camera_tree')" class="spinner"></span>
        <span v-else-if="stagesStatus.construct_camera_tree?.done" class="done-icon">&#10003;</span>
        <span v-else class="stage-pending-icon">&#9675;</span>
      </span>
      <div class="pipeline-stage-info">
        <span class="pipeline-stage-name">&#9316; 构建相机树</span>
        <span class="pipeline-stage-detail">{{ stagesStatus.construct_camera_tree?.done ? cameraTree.length + ' 个机位' : '未完成' }}</span>
      </div>
      <span class="chevron" :class="{open: stageExpanded.construct_camera_tree}">&#9662;</span>
    </div>
    <div class="pipeline-running-bar" v-if="isStageRunning('construct_camera_tree')">{{ stageTaskMsg('construct_camera_tree') }}</div>
    <div class="pipeline-stage-error" v-if="stageTaskError('construct_camera_tree')">{{ stageTaskError('construct_camera_tree') }}</div>
    <div class="pipeline-io" v-if="stageExpanded.construct_camera_tree">
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输入 · 镜头视觉描述</div>
        <div v-if="shots.filter(s=>s.description).length===0" class="pipeline-io-empty">视觉描述为空，请先运行④</div>
        <div v-else class="pipeline-io-summary">{{ shots.filter(s=>s.description).length }} 个镜头描述，涉及机位编号：{{ [...new Set(shots.filter(s=>s.description).map(s=>s.description.cam_idx))].sort((a,b)=>a-b).join('、') }}</div>
      </div>
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输出 · 相机树</div>
        <div v-if="cameraTree.length === 0" class="pipeline-io-empty">尚未生成</div>
        <div v-for="cam in cameraTree" :key="cam.idx" class="camera-io-row">
          <div class="camera-io-header">
            <span class="cam-badge">机位 {{ cam.idx }}</span>
            <span class="camera-io-shots">镜头：{{ cam.active_shot_idxs.map(i=>'Shot '+i).join('、') }}</span>
          </div>
          <div class="camera-io-parent" v-if="cam.parent_cam_idx != null">
            父机位：机位 {{ cam.parent_cam_idx }}（依赖 Shot {{ cam.parent_shot_idx }}）
            <span v-if="cam.is_parent_fully_covers_child === false" class="camera-missing">缺失：{{ cam.missing_info }}</span>
          </div>
          <div class="camera-io-parent" v-else>根机位（无父节点）</div>
        </div>
      </div>
    </div>
    <div class="pipeline-stage-actions">
      <button class="btn btn-primary pipeline-run-btn" :disabled="isStageRunning('construct_camera_tree')" @click="runStage('construct_camera_tree', false)">
        {{ isStageRunning('construct_camera_tree') ? '运行中…' : (stagesStatus.construct_camera_tree?.done ? '重新运行' : '运行') }}
      </button>
      <button class="btn btn-ghost pipeline-force-btn" :disabled="isStageRunning('construct_camera_tree')" @click="runStage('construct_camera_tree', true)">强制重跑</button>
    </div>
  </div>

  <!-- ⑥ 生成帧图 -->
  <div class="pipeline-stage-card" :class="{done: stagesStatus.generate_frames?.done, running: isStageRunning('generate_frames')}">
    <div class="pipeline-stage-header" @click="toggleStageExpanded('generate_frames')">
      <span class="pipeline-stage-icon">
        <span v-if="isStageRunning('generate_frames')" class="spinner"></span>
        <span v-else-if="stagesStatus.generate_frames?.done" class="done-icon">&#10003;</span>
        <span v-else class="stage-pending-icon">&#9675;</span>
      </span>
      <div class="pipeline-stage-info">
        <span class="pipeline-stage-name">&#9317; 生成帧图</span>
        <span class="pipeline-stage-detail">{{ stagesStatus.generate_frames?.shots_done }}/{{ stagesStatus.generate_frames?.shots_total }} 个镜头</span>
      </div>
      <span class="chevron" :class="{open: stageExpanded.generate_frames}">&#9662;</span>
    </div>
    <div class="pipeline-running-bar" v-if="isStageRunning('generate_frames')">{{ stageTaskMsg('generate_frames') }}</div>
    <div class="pipeline-stage-error" v-if="stageTaskError('generate_frames')">{{ stageTaskError('generate_frames') }}</div>
    <div class="pipeline-io" v-if="stageExpanded.generate_frames">
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输入 · 相机树 & 角色肖像</div>
        <div v-if="cameraTree.length===0" class="pipeline-io-empty">相机树为空，请先运行⑤</div>
        <div v-else class="pipeline-io-summary">{{ cameraTree.length }} 个机位 · {{ characters.length }} 个角色肖像</div>
      </div>
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输出 · 首帧 / 末帧图像</div>
        <div v-if="shots.filter(s=>s.has_first_frame).length===0" class="pipeline-io-empty">尚未生成</div>
        <div class="frames-io-grid">
          <div v-for="shot in shots" :key="shot.idx" class="frames-io-cell">
            <div class="frames-io-label">Shot {{ shot.idx }}</div>
            <div class="frames-io-imgs">
              <div class="frames-io-img-wrap" v-if="shot.has_first_frame" @click="openLightbox(shotFileUrl(shot.idx,'first_frame.png'))">
                <img :src="shotFileUrl(shot.idx,'first_frame.png')" />
                <span class="frames-io-badge">首帧</span>
              </div>
              <div class="frames-io-empty-img" v-else><span>首帧未生成</span></div>
              <div class="frames-io-img-wrap" v-if="shot.has_last_frame" @click="openLightbox(shotFileUrl(shot.idx,'last_frame.png'))">
                <img :src="shotFileUrl(shot.idx,'last_frame.png')" />
                <span class="frames-io-badge">末帧</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="pipeline-stage-actions">
      <button class="btn btn-primary pipeline-run-btn" :disabled="isStageRunning('generate_frames')" @click="runStage('generate_frames', false)">
        {{ isStageRunning('generate_frames') ? '运行中…' : (stagesStatus.generate_frames?.done ? '重新运行' : '运行') }}
      </button>
      <button class="btn btn-ghost pipeline-force-btn" :disabled="isStageRunning('generate_frames')" @click="runStage('generate_frames', true)">强制重跑</button>
    </div>
  </div>

  <!-- ⑦ 生成视频 -->
  <div class="pipeline-stage-card" :class="{done: stagesStatus.generate_videos?.done, running: isStageRunning('generate_videos')}">
    <div class="pipeline-stage-header" @click="toggleStageExpanded('generate_videos')">
      <span class="pipeline-stage-icon">
        <span v-if="isStageRunning('generate_videos')" class="spinner"></span>
        <span v-else-if="stagesStatus.generate_videos?.done" class="done-icon">&#10003;</span>
        <span v-else class="stage-pending-icon">&#9675;</span>
      </span>
      <div class="pipeline-stage-info">
        <span class="pipeline-stage-name">&#9318; 生成视频</span>
        <span class="pipeline-stage-detail">{{ stagesStatus.generate_videos?.shots_done }}/{{ stagesStatus.generate_videos?.shots_total }} 个镜头</span>
      </div>
      <span class="chevron" :class="{open: stageExpanded.generate_videos}">&#9662;</span>
    </div>
    <div class="pipeline-running-bar" v-if="isStageRunning('generate_videos')">{{ stageTaskMsg('generate_videos') }}</div>
    <div class="pipeline-stage-error" v-if="stageTaskError('generate_videos')">{{ stageTaskError('generate_videos') }}</div>
    <div class="pipeline-io" v-if="stageExpanded.generate_videos">
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输入 · 帧图 & 运动描述</div>
        <div class="frames-io-grid">
          <div v-for="shot in shots.filter(s=>s.has_first_frame)" :key="shot.idx" class="frames-io-cell">
            <div class="frames-io-label">Shot {{ shot.idx }}</div>
            <div class="frames-io-imgs">
              <div class="frames-io-img-wrap" @click="openLightbox(shotFileUrl(shot.idx,'first_frame.png'))">
                <img :src="shotFileUrl(shot.idx,'first_frame.png')" />
                <span class="frames-io-badge">首帧</span>
              </div>
              <div class="frames-io-img-wrap" v-if="shot.has_last_frame" @click="openLightbox(shotFileUrl(shot.idx,'last_frame.png'))">
                <img :src="shotFileUrl(shot.idx,'last_frame.png')" />
                <span class="frames-io-badge">末帧</span>
              </div>
            </div>
            <p class="frames-io-desc" v-if="shot.description">{{ shot.description.motion_desc?.slice(0,80) }}…</p>
          </div>
        </div>
      </div>
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输出 · 镜头视频</div>
        <div v-if="shots.filter(s=>s.has_video).length===0" class="pipeline-io-empty">尚未生成</div>
        <div class="videos-io-grid">
          <div v-for="shot in shots.filter(s=>s.has_video)" :key="shot.idx" class="videos-io-cell">
            <div class="frames-io-label">Shot {{ shot.idx }}</div>
            <video :src="shotFileUrl(shot.idx,'video.mp4')" controls muted></video>
          </div>
        </div>
      </div>
    </div>
    <div class="pipeline-stage-actions">
      <button class="btn btn-primary pipeline-run-btn" :disabled="isStageRunning('generate_videos')" @click="runStage('generate_videos', false)">
        {{ isStageRunning('generate_videos') ? '运行中…' : (stagesStatus.generate_videos?.done ? '重新运行' : '运行') }}
      </button>
      <button class="btn btn-ghost pipeline-force-btn" :disabled="isStageRunning('generate_videos')" @click="runStage('generate_videos', true)">强制重跑</button>
    </div>
  </div>

  <!-- ⑧ 拼接最终视频 -->
  <div class="pipeline-stage-card" :class="{done: stagesStatus.concatenate?.done, running: isStageRunning('concatenate')}">
    <div class="pipeline-stage-header" @click="toggleStageExpanded('concatenate')">
      <span class="pipeline-stage-icon">
        <span v-if="isStageRunning('concatenate')" class="spinner"></span>
        <span v-else-if="stagesStatus.concatenate?.done" class="done-icon">&#10003;</span>
        <span v-else class="stage-pending-icon">&#9675;</span>
      </span>
      <div class="pipeline-stage-info">
        <span class="pipeline-stage-name">&#9319; 拼接最终视频</span>
        <span class="pipeline-stage-detail">{{ stagesStatus.concatenate?.done ? '已完成' : '未完成' }}</span>
      </div>
      <span class="chevron" :class="{open: stageExpanded.concatenate}">&#9662;</span>
    </div>
    <div class="pipeline-running-bar" v-if="isStageRunning('concatenate')">{{ stageTaskMsg('concatenate') }}</div>
    <div class="pipeline-stage-error" v-if="stageTaskError('concatenate')">{{ stageTaskError('concatenate') }}</div>
    <div class="pipeline-io" v-if="stageExpanded.concatenate">
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输入 · 镜头视频</div>
        <div class="pipeline-io-summary">{{ shots.filter(s=>s.has_video).length }}/{{ shots.length }} 个视频已就绪</div>
      </div>
      <div class="pipeline-io-block">
        <div class="pipeline-io-title">输出 · 最终视频</div>
        <div v-if="!hasFinalVideo" class="pipeline-io-empty">尚未生成</div>
        <div v-else class="final-io-wrap">
          <video class="final-io-video" controls :src="finalVideoUrl()"></video>
          <a class="download-btn" :href="finalVideoUrl()" download="final_video.mp4" style="margin-top:8px;display:inline-block">下载视频</a>
        </div>
      </div>
    </div>
    <div class="pipeline-stage-actions">
      <button class="btn btn-primary pipeline-run-btn" :disabled="isStageRunning('concatenate')" @click="runStage('concatenate', false)">
        {{ isStageRunning('concatenate') ? '运行中…' : (stagesStatus.concatenate?.done ? '重新运行' : '运行') }}
      </button>
      <button class="btn btn-ghost pipeline-force-btn" :disabled="isStageRunning('concatenate')" @click="runStage('concatenate', true)">强制重跑</button>
    </div>
  </div>

</div>
  `
};
