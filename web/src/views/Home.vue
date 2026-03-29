<template>
  <div class="file-manager">
    <div class="kb-sidebar">
      <div class="kb-header">
        <h3>知识库</h3>
        <div class="header-actions">
          <button @click="handleSync" class="btn-icon" title="同步本地文件" :disabled="syncing || !selectedKB">
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
    </div>

    <main class="main-content">
      <div v-if="!selectedKB" class="welcome">
        <h2>欢迎使用 MetaWeave</h2>
        <p>请选择或创建一个知识库开始管理文件</p>
      </div>
      <div v-else class="file-explorer">
        <div class="explorer-header">
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
          <span class="full-path">本地路径: {{ selectedKB.kb_path }}</span>
        </div>

        <div v-if="loading" class="loading">加载中...</div>
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
            <tr v-for="item in displayFiles" :key="item.id" class="file-row" @click="item.isDir ? enterDir(item.name) : null">
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
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue';
import { getKBList, createKB, getFileList, syncKBFiles } from '@/api/kb';

const kbList = ref([]);
const selectedKB = ref(null);
const allFiles = ref([]);
const loading = ref(false);
const syncing = ref(false);
const showAddKB = ref(false);
const newKB = ref({ kb_name: '', kb_path: '', description: '' });
const currentPath = ref(''); // 相对知识库根目录的路径，例如 "folder1/subfolder"

const pathParts = computed(() => {
  return currentPath.value ? currentPath.value.split('/').filter(p => p) : [];
});

const loadKBList = async () => {
  try {
    const res = await getKBList();
    kbList.value = res.data;
  } catch (err) {
    console.error('加载知识库失败', err);
  }
};

const selectKB = async (kb) => {
  selectedKB.value = kb;
  currentPath.value = '';
  await loadFiles();
};

const loadFiles = async () => {
  if (!selectedKB.value) return;
  loading.value = true;
  try {
    const res = await getFileList(selectedKB.value.kb_id);
    allFiles.value = res.data;
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
    await syncKBFiles(selectedKB.value.kb_id);
    await loadFiles();
  } catch (err) {
    alert('同步失败: ' + (err.response?.data?.detail || err.message));
  } finally {
    syncing.value = false;
  }
};

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
      // 在当前目录下
      filesMap.set(file.file_name, {
        id: file.fid,
        name: file.file_name,
        isDir: false,
        ...file
      });
    } else if (parentFolder.startsWith(targetDir + '/')) {
      // 在当前目录的子目录下
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
  if (currentPath.value) {
    currentPath.value += '/' + dirName;
  } else {
    currentPath.value = dirName;
  }
};

const goBack = () => {
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

onMounted(loadKBList);
</script>

<style scoped>
.file-manager {
  display: flex;
  height: 100%;
  background: #ffffff;
}

.kb-sidebar {
  width: 260px;
  background: #f6f8fa;
  border-right: 1px solid #d0d7de;
  display: flex;
  flex-direction: column;
}

.kb-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #d0d7de;
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

.empty-state {
  padding: 24px 16px;
  text-align: center;
}

.empty-state p {
  color: #57606a;
  margin-bottom: 12px;
  font-size: 14px;
}

.kb-list {
  flex: 1;
  overflow-y: auto;
}

.kb-item {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  cursor: pointer;
  border-left: 2px solid transparent;
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

.title-row {
  display: flex;
  align-items: baseline;
  gap: 16px;
  margin-bottom: 4px;
}

.explorer-header h2 {
  margin: 0;
  font-size: 20px;
  color: #24292f;
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

.loading, .empty-files {
  text-align: center;
  padding: 48px;
  color: #57606a;
}

.file-table {
  width: 100%;
  border-collapse: collapse;
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

.back-row {
  color: #57606a;
  font-style: italic;
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
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: #ffffff;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  padding: 24px;
  width: 480px;
  max-width: 90%;
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

.form-group textarea {
  resize: vertical;
  min-height: 80px;
}

.hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: #57606a;
  line-height: 1.5;
}

.path-input {
  display: flex;
  gap: 8px;
}

.path-input input {
  flex: 1;
}

.btn-browse {
  background: #f6f8fa;
  color: #24292f;
  border: 1px solid #d0d7de;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

.btn-browse:hover {
  background: #eaeef2;
}

.form-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 20px;
}

.btn-primary {
  background: #2da44e;
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
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

.btn-cancel:hover {
  background: #eaeef2;
}

.btn-link {
  background: none;
  border: none;
  color: #0969da;
  cursor: pointer;
  padding: 0;
  font-size: 14px;
  margin-top: 8px;
}

.btn-link:hover {
  text-decoration: underline;
}
</style>
