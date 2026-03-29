<template>
  <div class="file-manager">
    <div 
      class="kb-sidebar" 
      :style="{ width: isSidebarCollapsed ? '0px' : sidebarWidth + 'px' }"
      :class="{ collapsed: isSidebarCollapsed }"
    >
      <div class="sidebar-content" v-show="!isSidebarCollapsed">
        <div class="kb-header">
          <h3>知识库</h3>
          <div class="header-actions">
            <button @click="handleSync" class="btn-icon" title="同步本地文件" :disabled="syncing || !selectedKB || scanRunning">
              <svg :class="{ spinning: syncing }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M23 4v6h-6M1 20v-6h6"></path>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
            </button>
            <button @click="showAddKB = true" class="btn-add">+</button>
          </div>
        </div>
        <div v-if="kbList.length === 0" class="empty-state">
          <p>暂无知识库</p>
          <button @click="showAddKB = true" class="btn-primary">添加知识库</button>
        </div>
        <div v-else class="kb-list">
          <div
            v-for="kb in kbList"
            :key="kb.kb_id"
            :class="['kb-item', { active: selectedKB?.kb_id === kb.kb_id }]"
            @click="selectKB(kb)"
          >
            <svg class="kb-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
            </svg>
            <span class="kb-name">{{ kb.kb_name }}</span>
          </div>
        </div>
        <div v-if="selectedKB" class="tree-section">
          <div class="tree-list">
            <TreeNode
              v-if="fileTree"
              :node="fileTree"
              :expanded-paths="expandedPaths"
              @toggle="toggleNode"
              @open="handleTreeDoubleClick"
            />
          </div>
        </div>
      </div>
    </div>
    
    <div class="sidebar-resizer" @mousedown="startResizing" v-show="!isSidebarCollapsed"></div>
    
    <button class="toggle-sidebar-btn" @click="toggleSidebar" :class="{ 'is-collapsed': isSidebarCollapsed }">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path v-if="isSidebarCollapsed" d="M9 18l6-6-6-6" />
        <path v-else d="M15 18l-6-6 6-6" />
      </svg>
    </button>

    <main class="main-content">
      <div v-if="!selectedKB" class="welcome">
        <h2>欢迎使用 MetaWeave</h2>
        <p>请选择或创建一个知识库开始管理文件</p>
      </div>
      <div v-else class="file-explorer">
        <div class="explorer-header">
          <div class="header-main-row">
            <div class="title-row">
              <h2>{{ selectedKB.kb_name }}</h2>
              <div class="breadcrumb">
                <span class="breadcrumb-item" @click="currentPath = ''">根目录</span>
                <template v-for="(part, index) in pathParts" :key="index">
                  <span class="separator">/</span>
                  <span class="breadcrumb-item" @click="navigateToPart(index)">{{ part }}</span>
                </template>
              </div>
            </div>
            <button class="btn-settings" @click="openSettings" title="知识库设置">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3"></circle>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
              </svg>
            </button>
          </div>
          <span class="full-path">本地路径: {{ selectedKB.kb_path }}</span>
        </div>

        <div v-if="scanRunning || scanStatus?.status === 'failed'" class="scan-progress">
          <div class="scan-row">
            <span>{{ scanStatus?.status === 'failed' ? '解析失败' : '正在解析文件...' }}</span>
            <span class="scan-count">{{ scanStatus.processed }} / {{ scanStatus.total }} ({{ scanPercent }}%)</span>
          </div>
          <div class="scan-bar">
            <div class="scan-bar-inner" :style="{ width: scanPercent + '%' }"></div>
          </div>
          <div class="scan-meta">
            <span>成功 {{ scanStatus.success }}</span>
            <span>失败 {{ scanStatus.failed }}</span>
            <span>跳过 {{ scanStatus.skipped }}</span>
            <span v-if="scanStatus?.message">原因: {{ scanStatus.message }}</span>
          </div>
        </div>
        <div v-if="loading" class="loading">加载中...</div>
        <div v-else-if="previewFile" class="preview-panel">
          <div class="preview-header">
            <button class="back-btn" @click="closePreview">← 返回</button>
            <div class="preview-meta">
              <h3>{{ previewFile.file_name }}</h3>
              <p>{{ previewFile.file_path }}</p>
            </div>
          </div>
          <div v-if="previewLoading" class="loading">正在加载文件...</div>
          <div v-else-if="previewError" class="error">{{ previewError }}</div>
          <div v-else class="preview-body">
            <pre v-if="previewType === 'text'" class="text-preview">{{ previewText }}</pre>
            <img v-else-if="previewType === 'image'" :src="previewRawUrl" class="image-preview" />
            <iframe v-else-if="previewType === 'pdf'" class="pdf-preview" :src="previewRawUrl"></iframe>
            <div v-else-if="previewType === 'docx'" ref="docxContainer" class="docx-preview"></div>
            <div v-else-if="previewType === 'pptx'" class="pptx-preview">
              <VueOfficePptx :src="previewRawUrl" />
            </div>
            <div v-else class="unsupported">暂不支持预览该格式</div>
          </div>
        </div>
        <div v-else-if="displayFiles.length === 0" class="empty-files">
          <p>此文件夹暂无文件</p>
          <button v-if="currentPath !== ''" @click="goBack" class="btn-link">返回上级</button>
        </div>
        <table v-else class="file-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>大小</th>
              <th>修改时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="currentPath !== ''" class="file-row" @click="goBack">
              <td colspan="4" class="file-name back-row">
                <svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M11 17l-5-5 5-5M18 17l-5-5 5-5"></path>
                </svg>
                .. (返回上级)
              </td>
            </tr>
            <tr
              v-for="item in displayFiles"
              :key="item.id"
              class="file-row"
              @click="item.isDir ? enterDir(item.name) : openFilePreview(item)"
              @dblclick="item.isDir ? enterDir(item.name) : null"
            >
              <td class="file-name">
                <svg v-if="item.isDir" class="file-icon folder-icon" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"></path>
                </svg>
                <svg v-else class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                  <polyline points="13 2 13 9 20 9"></polyline>
                </svg>
                {{ item.name }}
              </td>
              <td>{{ item.isDir ? '文件夹' : (item.file_type || '-') }}</td>
              <td>{{ item.isDir ? '-' : formatSize(item.file_size) }}</td>
              <td>{{ formatDate(item.modified_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </main>

    <!-- 添加知识库对话框 -->
    <div v-if="showAddKB" class="modal" @click.self="showAddKB = false">
      <div class="modal-content">
        <h3>添加知识库</h3>
        <form @submit.prevent="handleAddKB">
          <div class="form-group">
            <label>知识库名称</label>
            <input v-model="newKB.kb_name" required />
          </div>
          <div class="form-group">
            <label>文件夹路径</label>
            <div class="path-input">
              <input v-model="newKB.kb_path" placeholder="例如: D:\Documents\Notes" required />
              <button type="button" @click="selectFolder" class="btn-browse">浏览</button>
            </div>
            <p class="hint">注：由于浏览器安全限制，"浏览"只能获取文件夹名。<b>请确保手动输入的完整绝对路径在电脑上确实存在。</b></p>
          </div>
          <div class="form-group">
            <label>描述</label>
            <textarea v-model="newKB.description"></textarea>
          </div>
          <div class="form-actions">
            <button type="button" @click="showAddKB = false" class="btn-cancel">取消</button>
            <button type="submit" class="btn-primary">创建</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 知识库设置对话框 -->
    <div v-if="showSettings" class="modal" @click.self="showSettings = false">
      <div class="modal-content">
        <h3>知识库设置</h3>
        <form @submit.prevent="handleUpdateKB">
          <div class="form-group">
            <label>知识库名称</label>
            <input v-model="editKB.kb_name" required />
          </div>
          <div class="form-group">
            <label>文件夹路径</label>
            <input v-model="editKB.kb_path" required />
          </div>
          <div class="form-group">
            <label>描述</label>
            <textarea v-model="editKB.description"></textarea>
          </div>
          
          <div class="danger-zone">
            <h4>危险区域</h4>
            <div class="delete-box">
              <p>删除知识库将清空所有索引数据，但不会删除本地实际文件。</p>
              <button type="button" class="btn-danger-outline" @click="showDeleteConfirm = true">删除此知识库</button>
            </div>
          </div>

          <div class="form-actions">
            <button type="button" @click="showSettings = false" class="btn-cancel">取消</button>
            <button type="submit" class="btn-primary">保存修改</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 删除确认对话框 -->
    <div v-if="showDeleteConfirm" class="modal" @click.self="showDeleteConfirm = false">
      <div class="modal-content confirm-modal">
        <h3>确认删除？</h3>
        <p>您确定要删除知识库 <b>{{ selectedKB?.kb_name }}</b> 吗？此操作不可撤销。</p>
        <div class="form-actions">
          <button type="button" @click="showDeleteConfirm = false" class="btn-cancel">取消</button>
          <button type="button" @click="handleDeleteKB" class="btn-danger">确认删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, onUnmounted } from 'vue';
import { renderAsync } from 'docx-preview';
import VueOfficePptx from '@vue-office/pptx';
import { apiClient } from '@/router/api_routes';
import TreeNode from '@/components/home/TreeNode.vue';
import { getKBList, createKB, getFileList, syncKBFiles, updateKB, deleteKB, verifyKBPath, getScanStatus, getFileRaw } from '@/api/kb';

const kbList = ref([]);
const selectedKB = ref(null);
const allFiles = ref([]);
const loading = ref(false);
const syncing = ref(false);
const scanStatus = ref(null);
const scanTimer = ref(null);
const autoSyncedKbIds = new Set();
const expandedPaths = ref(new Set());

const previewFile = ref(null);
const previewLoading = ref(false);
const previewError = ref('');
const previewText = ref('');
const previewRawUrl = ref('');
const docxContainer = ref(null);
const showAddKB = ref(false);
const showSettings = ref(false);
const showDeleteConfirm = ref(false);
const newKB = ref({ kb_name: '', kb_path: '', description: '' });
const editKB = ref({ kb_id: null, kb_name: '', kb_path: '', description: '' });
const currentPath = ref(''); 

// 侧边栏宽度控制
const sidebarWidth = ref(260);
const isSidebarCollapsed = ref(false);
const isResizing = ref(false);

const startResizing = (e) => {
  isResizing.value = true;
  document.addEventListener('mousemove', handleMouseMove);
  document.addEventListener('mouseup', stopResizing);
  document.body.style.cursor = 'col-resize';
};

const handleMouseMove = (e) => {
  if (!isResizing.value) return;
  const newWidth = e.clientX;
  if (newWidth > 150 && newWidth < 600) {
    sidebarWidth.value = newWidth;
  }
};

const stopResizing = () => {
  isResizing.value = false;
  document.removeEventListener('mousemove', handleMouseMove);
  document.removeEventListener('mouseup', stopResizing);
  document.body.style.cursor = '';
};

const toggleSidebar = () => {
  isSidebarCollapsed.value = !isSidebarCollapsed.value;
};

const loadKBList = async () => {
  try {
    const res = await getKBList();
    kbList.value = res.data;
  } catch (err) {
    console.error('加载知识库失败', err);
  }
};

const selectKB = async (kb) => {
  stopScanPolling();
  closePreview();
  // 路径验证
  try {
    const check = await verifyKBPath(kb.kb_id);
    if (!check.data.exists) {
      alert(`本地路径不存在: ${kb.kb_path}\n该知识库将被自动清理。`);
      await deleteKB(kb.kb_id);
      await loadKBList();
      if (selectedKB.value?.kb_id === kb.kb_id) {
        selectedKB.value = null;
      }
      return;
    }
  } catch (err) {
    console.error('验证路径失败', err);
  }

  selectedKB.value = kb;
  currentPath.value = '';
  expandedPaths.value = new Set(['']);
  await loadFiles();
  await fetchScanStatus();
  triggerAutoSyncIfNeeded();
};

const loadFiles = async () => {
  if (!selectedKB.value) return;
  loading.value = true;
  try {
    const res = await getFileList(selectedKB.value.kb_id);
    allFiles.value = res.data;
    if (previewFile.value) {
      const updated = allFiles.value.find(f => f.fid === previewFile.value.fid);
      if (updated) {
        previewFile.value = updated;
        previewRawUrl.value = buildRawUrl(updated.fid, updated.file_hash, updated.modified_at);
        loadPreview(updated);
      }
    }
  } catch (err) {
    console.error('加载文件失败', err);
  } finally {
    loading.value = false;
  }
};

const handleSync = async () => {
  if (!selectedKB.value || syncing.value) return;
  syncing.value = true;
  try {
    const res = await syncKBFiles(selectedKB.value.kb_id);
    scanStatus.value = res.data?.job || null;
    startScanPolling();
  } catch (err) {
    alert('同步失败: ' + (err.response?.data?.detail || err.message));
  } finally {
    syncing.value = false;
  }
};

const openSettings = () => {
  if (!selectedKB.value) return;
  editKB.value = { ...selectedKB.value };
  showSettings.value = true;
};

const handleUpdateKB = async () => {
  try {
    await updateKB(editKB.value.kb_id, editKB.value);
    showSettings.value = false;
    await loadKBList();
    if (selectedKB.value?.kb_id === editKB.value.kb_id) {
      selectedKB.value = { ...selectedKB.value, ...editKB.value };
    }
  } catch (err) {
    alert('更新失败: ' + (err.response?.data?.detail || err.message));
  }
};

const handleDeleteKB = async () => {
  try {
    await deleteKB(selectedKB.value.kb_id);
    showDeleteConfirm.value = false;
    showSettings.value = false;
    selectedKB.value = null;
    await loadKBList();
  } catch (err) {
    alert('删除失败: ' + (err.response?.data?.detail || err.message));
  }
};

const pathParts = computed(() => {
  return currentPath.value ? currentPath.value.split('/').filter(p => p) : [];
});

const displayFiles = computed(() => {
  if (!selectedKB.value) return [];
  const kbPath = selectedKB.value.kb_path.replace(/\\/g, '/');
  const targetDir = currentPath.value ? `${kbPath}/${currentPath.value}`.replace(/\/+$/, '') : kbPath;
  
  const filesMap = new Map();
  const dirsSet = new Set();

  allFiles.value.forEach(file => {
    const filePath = file.file_path.replace(/\\/g, '/');
    const parentFolder = file.parent_folder.replace(/\\/g, '/');

    if (parentFolder === targetDir) {
      filesMap.set(file.file_name, {
        id: file.fid,
        name: file.file_name,
        isDir: false,
        ...file
      });
    } else if (parentFolder.startsWith(targetDir + '/')) {
      const relative = parentFolder.substring(targetDir.length).replace(/^\/+/, '');
      const firstPart = relative.split('/')[0];
      if (firstPart) {
        dirsSet.add(firstPart);
      }
    }
  });

  const result = [];
  dirsSet.forEach(dirName => {
    result.push({
      id: 'dir-' + dirName,
      name: dirName,
      isDir: true,
      modified_at: '',
      file_size: 0
    });
  });

  return [...result, ...Array.from(filesMap.values())].sort((a, b) => {
    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
});

const enterDir = (dirName) => {
  closePreview();
  if (currentPath.value) {
    currentPath.value += '/' + dirName;
  } else {
    currentPath.value = dirName;
  }
};

const goBack = () => {
  closePreview();
  const parts = currentPath.value.split('/');
  parts.pop();
  currentPath.value = parts.join('/');
};

const navigateToPart = (index) => {
  const parts = currentPath.value.split('/');
  currentPath.value = parts.slice(0, index + 1).join('/');
};

const selectFolder = async () => {
  if (window.showDirectoryPicker) {
    try {
      const dirHandle = await window.showDirectoryPicker();
      newKB.value.kb_path = dirHandle.name;
      alert('已获取文件夹名称: ' + dirHandle.name + '。由于浏览器安全限制，请手动补充完整路径（如 D:\\Projects\\' + dirHandle.name + '）。');
    } catch (err) {
      console.log('用户取消选择');
    }
  } else {
    alert('浏览器不支持文件夹选择，请手动输入完整绝对路径。');
  }
};

const handleAddKB = async () => {
  try {
    await createKB(newKB.value);
    showAddKB.value = false;
    newKB.value = { kb_name: '', kb_path: '', description: '' };
    await loadKBList();
  } catch (err) {
    alert('创建失败: ' + (err.response?.data?.detail || err.message));
  }
};

const fetchScanStatus = async () => {
  if (!selectedKB.value) return;
  try {
    const res = await getScanStatus(selectedKB.value.kb_id);
    const prevStatus = scanStatus.value?.status;
    scanStatus.value = res.data;
    if (scanRunning.value) {
      startScanPolling();
    } else {
      stopScanPolling();
      if (prevStatus === 'running' && (scanStatus.value?.status === 'completed' || scanStatus.value?.status === 'failed')) {
        await loadFiles();
      }
    }
  } catch (err) {
    console.error('获取解析进度失败', err);
  }
};

const startScanPolling = () => {
  if (scanTimer.value) return;
  scanTimer.value = setInterval(fetchScanStatus, 1000);
};

const stopScanPolling = () => {
  if (!scanTimer.value) return;
  clearInterval(scanTimer.value);
  scanTimer.value = null;
};

const scanRunning = computed(() => scanStatus.value?.status === 'running');
const scanPercent = computed(() => {
  const total = scanStatus.value?.total || 0;
  if (!total) return 0;
  return Math.min(100, Math.floor((scanStatus.value?.processed || 0) / total * 100));
});

const triggerAutoSyncIfNeeded = async () => {
  if (!selectedKB.value) return;
  if (autoSyncedKbIds.has(selectedKB.value.kb_id)) return;
  autoSyncedKbIds.add(selectedKB.value.kb_id);
  try {
    const res = await syncKBFiles(selectedKB.value.kb_id);
    scanStatus.value = res.data?.job || null;
    startScanPolling();
  } catch (err) {
    console.error('自动解析失败', err);
  }
};

const buildFileTree = () => {
  if (!selectedKB.value) return [];
  const kbPath = selectedKB.value.kb_path.replace(/\\/g, '/');
  const root = { name: '根目录', path: '', isDir: true, children: new Map(), isRoot: true };

  allFiles.value.forEach(file => {
    const filePath = file.file_path.replace(/\\/g, '/');
    const relative = filePath.replace(kbPath, '').replace(/^\/+/, '');
    if (!relative) return;
    const parts = relative.split('/');
    let node = root;
    parts.forEach((part, idx) => {
      const isLast = idx === parts.length - 1;
      const currentPath = parts.slice(0, idx + 1).join('/');
      if (!node.children.has(part)) {
        node.children.set(part, {
          name: part,
          path: currentPath,
          isDir: !isLast,
          children: new Map(),
          ...(!isLast ? {} : file)
        });
      }
      node = node.children.get(part);
    });
  });

  const sortTree = (a, b) => {
    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
    return a.name.localeCompare(b.name);
  };

  const toArray = (map) => {
    return Array.from(map.values()).map(item => {
      if (item.isDir) {
        return {
          ...item,
          children: toArray(item.children).sort(sortTree)
        };
      }
      return item;
    }).sort(sortTree);
  };

  return {
    ...root,
    children: toArray(root.children)
  };
};

const fileTree = computed(() => buildFileTree());

const toggleNode = (path) => {
  const set = new Set(expandedPaths.value);
  if (set.has(path)) set.delete(path);
  else set.add(path);
  expandedPaths.value = set;
};

const handleTreeDoubleClick = (node) => {
  if (node.isDir) {
    toggleNode(node.path);
    currentPath.value = node.path;
  } else {
    openFilePreview(node);
  }
};

const formatSize = (bytes) => {
  if (!bytes) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
};

const formatDate = (date) => {
  return date ? new Date(date).toLocaleString('zh-CN') : '-';
};

const buildRawUrl = (fid, fileHash, modifiedAt) => {
  const token = localStorage.getItem('token');
  const base = apiClient.defaults.baseURL || '/api';
  const cacheBuster = encodeURIComponent(Date.now());
  if (!token) return `${base}/file/raw/${fid}?v=${cacheBuster}`;
  return `${base}/file/raw/${fid}?token=${encodeURIComponent(token)}&v=${cacheBuster}`;
};

const previewType = computed(() => {
  const ext = (previewFile.value?.file_type || '').toLowerCase();
  if (['txt', 'md'].includes(ext)) return 'text';
  if (['png', 'jpg', 'jpeg', 'webp', 'bmp'].includes(ext)) return 'image';
  if (['pdf'].includes(ext)) return 'pdf';
  if (['docx'].includes(ext)) return 'docx';
  if (['pptx'].includes(ext)) return 'pptx';
  return 'unknown';
});

const openFilePreview = (item) => {
  if (!item?.fid) return;
  previewFile.value = item;
  previewText.value = '';
  previewError.value = '';
  previewRawUrl.value = buildRawUrl(item.fid, item.file_hash, item.modified_at);
  loadPreview(item);
};

const closePreview = () => {
  previewFile.value = null;
  previewText.value = '';
  previewError.value = '';
  previewRawUrl.value = '';
};

const loadPreview = async (item) => {
  previewLoading.value = true;
  try {
    if (previewType.value === 'text') {
      const res = await getFileRaw(item.fid);
      const decoder = new TextDecoder('utf-8');
      previewText.value = decoder.decode(res.data);
    } else if (previewType.value === 'docx') {
      const res = await getFileRaw(item.fid);
      await renderAsync(res.data, docxContainer.value, null, { inWrapper: false });
    }
  } catch (err) {
    previewError.value = err.response?.data?.detail || err.message || '加载失败';
  } finally {
    previewLoading.value = false;
  }
};

onMounted(loadKBList);
onUnmounted(stopScanPolling);
</script>

<style scoped>
.file-manager {
  display: flex;
  height: 100%;
  background: #ffffff;
  position: relative;
}

.kb-sidebar {
  background: #f6f8fa;
  border-right: 1px solid #d0d7de;
  display: flex;
  flex-direction: column;
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  z-index: 5;
}

.sidebar-content {
  width: 100%;
  min-width: 200px;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.sidebar-resizer {
  width: 4px;
  cursor: col-resize;
  background: transparent;
  transition: background 0.2s;
  z-index: 10;
}

.sidebar-resizer:hover {
  background: #0969da;
}

.toggle-sidebar-btn {
  position: absolute;
  left: v-bind('sidebarWidth + "px"');
  top: 50%;
  transform: translateY(-50%) translateX(-50%);
  width: 24px;
  height: 24px;
  background: #ffffff;
  border: 1px solid #d0d7de;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 15;
  color: #57606a;
  transition: left 0.3s cubic-bezier(0.4, 0, 0.2, 1), transform 0.2s;
}

.toggle-sidebar-btn:hover {
  background: #f6f8fa;
  color: #24292f;
  border-color: #8c959f;
}

.toggle-sidebar-btn.is-collapsed {
  left: 12px;
}

.toggle-sidebar-btn svg {
  width: 14px;
  height: 14px;
}

.kb-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #d0d7de;
  white-space: nowrap;
}

.kb-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #24292f;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.btn-add, .btn-icon {
  background: #2da44e;
  color: white;
  border: none;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.btn-icon {
  background: #f6f8fa;
  color: #57606a;
  border: 1px solid #d0d7de;
}

.btn-icon:hover:not(:disabled) {
  background: #eaeef2;
  color: #24292f;
}

.btn-icon:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-icon svg {
  width: 16px;
  height: 16px;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.btn-add {
  font-size: 18px;
}

.btn-add:hover {
  background: #2c974b;
}

.kb-list {
  max-height: 220px;
  overflow-y: auto;
}

.tree-section {
  border-top: 1px solid #d0d7de;
  padding: 6px 0 12px 0;
  overflow-y: auto;
  flex: 1;
}

.tree-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}


.kb-item {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  cursor: pointer;
  border-left: 2px solid transparent;
  white-space: nowrap;
}

.kb-item:hover {
  background: #eaeef2;
}

.kb-item.active {
  background: #ffffff;
  border-left-color: #0969da;
}

.kb-icon {
  width: 16px;
  height: 16px;
  margin-right: 8px;
  color: #57606a;
}

.kb-name {
  font-size: 14px;
  color: #24292f;
  overflow: hidden;
  text-overflow: ellipsis;
}

.main-content {
  flex: 1;
  overflow-y: auto;
  background: #ffffff;
}

.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #57606a;
}

.file-explorer {
  padding: 24px;
}

.explorer-header {
  margin-bottom: 16px;
}

.header-main-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 4px;
}

.title-row {
  display: flex;
  align-items: baseline;
  gap: 16px;
}

.explorer-header h2 {
  margin: 0;
  font-size: 20px;
  color: #24292f;
}

.btn-settings {
  background: none;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  padding: 4px 8px;
  cursor: pointer;
  color: #57606a;
  display: flex;
  align-items: center;
}

.btn-settings:hover {
  background: #f6f8fa;
  color: #24292f;
}

.btn-settings svg {
  width: 18px;
  height: 18px;
}

.breadcrumb {
  display: flex;
  align-items: center;
  font-size: 14px;
  color: #57606a;
}

.breadcrumb-item {
  cursor: pointer;
  color: #0969da;
}

.breadcrumb-item:hover {
  text-decoration: underline;
}

.separator {
  margin: 0 4px;
  color: #afb8c1;
}

.full-path {
  color: #57606a;
  font-size: 12px;
}

.file-table {
  width: 100%;
  border-collapse: collapse;
}

.preview-panel {
  border: 1px solid #d0d7de;
  border-radius: 10px;
  overflow: hidden;
  background: #ffffff;
}

.preview-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid #d0d7de;
  background: #f6f8fa;
}

.back-btn {
  border: 1px solid #d0d7de;
  background: #ffffff;
  color: #24292f;
  border-radius: 6px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 13px;
}

.back-btn:hover {
  background: #eaeef2;
}

.preview-meta h3 {
  margin: 0;
  font-size: 15px;
  color: #24292f;
}

.preview-meta p {
  margin: 4px 0 0;
  font-size: 12px;
  color: #57606a;
}

.preview-body {
  padding: 16px;
  min-height: 60vh;
}

.text-preview {
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 13px;
  line-height: 1.6;
  color: #24292f;
  background: #f6f8fa;
  border: 1px solid #d0d7de;
  border-radius: 8px;
  padding: 16px;
}

.image-preview {
  max-width: 100%;
  height: auto;
  border: 1px solid #d0d7de;
  border-radius: 6px;
}

.pdf-preview {
  width: 100%;
  height: 80vh;
  border: 1px solid #d0d7de;
  border-radius: 8px;
  background: #ffffff;
}

.docx-preview,
.pptx-preview {
  border: 1px solid #d0d7de;
  border-radius: 8px;
  background: #ffffff;
  padding: 16px;
  min-height: 60vh;
}

.unsupported {
  color: #57606a;
}

.scan-progress {
  border: 1px solid #d0d7de;
  background: #f6f8fa;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
  color: #24292f;
  font-size: 13px;
}

.scan-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}

.scan-bar {
  height: 8px;
  background: #ffffff;
  border: 1px solid #d0d7de;
  border-radius: 999px;
  margin: 8px 0;
  overflow: hidden;
}

.scan-bar-inner {
  height: 100%;
  background: #2da44e;
  transition: width 0.3s ease;
}

.scan-meta {
  display: flex;
  gap: 12px;
  color: #57606a;
}

.file-table th {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid #d0d7de;
  font-size: 12px;
  font-weight: 600;
  color: #57606a;
  background: #f6f8fa;
}

.file-row {
  border-bottom: 1px solid #d0d7de;
  cursor: pointer;
}

.file-row:hover {
  background: #f6f8fa;
}

.file-row td {
  padding: 8px 12px;
  font-size: 14px;
  color: #24292f;
}

.file-name {
  display: flex;
  align-items: center;
}

.file-icon {
  width: 16px;
  height: 16px;
  margin-right: 8px;
  color: #57606a;
}

.folder-icon {
  color: #54aeff;
}

.modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: #ffffff;
  border: 1px solid #d0d7de;
  border-radius: 12px;
  padding: 24px;
  width: 520px;
  max-width: 90%;
  box-shadow: 0 8px 24px rgba(0,0,0,0.1);
}

.modal-content h3 {
  margin: 0 0 20px 0;
  font-size: 18px;
  color: #24292f;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #24292f;
}

.form-group input,
.form-group textarea {
  width: 100%;
  padding: 8px 12px;
  background: #ffffff;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  color: #24292f;
  font-size: 14px;
}

.danger-zone {
  margin-top: 24px;
  border-top: 1px solid #d0d7de;
  padding-top: 16px;
}

.danger-zone h4 {
  color: #cf222e;
  font-size: 14px;
  margin: 0 0 12px 0;
}

.delete-box {
  border: 1px dashed #cf222e;
  border-radius: 6px;
  padding: 16px;
  background: #fffbfa;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.delete-box p {
  margin: 0;
  font-size: 13px;
  color: #24292f;
  line-height: 1.5;
}

.btn-danger-outline {
  background: #ffffff;
  color: #cf222e;
  border: 1px solid #d0d7de;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}

.btn-danger-outline:hover {
  background: #cf222e;
  color: #ffffff;
  border-color: #cf222e;
}

.btn-danger {
  background: #cf222e;
  color: white;
  border: 1px solid rgba(27, 31, 36, 0.15);
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.form-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 24px;
}

.btn-primary {
  background: #2da44e;
  color: white;
  border: 1px solid rgba(27, 31, 36, 0.15);
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.btn-primary:hover {
  background: #2c974b;
}

.btn-cancel {
  background: #f6f8fa;
  color: #24292f;
  border: 1px solid #d0d7de;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

.confirm-modal {
  width: 400px;
}
</style>
