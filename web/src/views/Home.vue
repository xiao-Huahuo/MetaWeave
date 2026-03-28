<template>
  <div class="file-manager">
    <div class="kb-sidebar">
      <div class="kb-header">
        <h3>知识库</h3>
        <button @click="showAddKB = true" class="btn-add">+</button>
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
          <h2>{{ selectedKB.kb_name }}</h2>
          <span class="path">{{ selectedKB.kb_path }}</span>
        </div>
        <div v-if="loading" class="loading">加载中...</div>
        <div v-else-if="fileList.length === 0" class="empty-files">
          <p>此知识库暂无文件</p>
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
            <tr v-for="file in fileList" :key="file.fid" class="file-row">
              <td class="file-name">
                <svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                  <polyline points="13 2 13 9 20 9"></polyline>
                </svg>
                {{ file.file_name }}
              </td>
              <td>{{ file.file_type || '-' }}</td>
              <td>{{ formatSize(file.file_size) }}</td>
              <td>{{ formatDate(file.modified_at) }}</td>
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
              <input v-model="newKB.kb_path" required />
              <button type="button" @click="selectFolder" class="btn-browse">浏览</button>
            </div>
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
import { ref, onMounted } from 'vue';
import { getKBList, createKB, getFileList } from '@/api/kb';

const kbList = ref([]);
const selectedKB = ref(null);
const fileList = ref([]);
const loading = ref(false);
const showAddKB = ref(false);
const newKB = ref({ kb_name: '', kb_path: '', description: '' });

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
  loading.value = true;
  try {
    const res = await getFileList(kb.kb_id);
    fileList.value = res.data;
  } catch (err) {
    console.error('加载文件失败', err);
  } finally {
    loading.value = false;
  }
};

const selectFolder = async () => {
  if (window.showDirectoryPicker) {
    try {
      const dirHandle = await window.showDirectoryPicker();
      newKB.value.kb_path = dirHandle.name;
    } catch (err) {
      console.log('用户取消选择');
    }
  } else {
    alert('浏览器不支持文件夹选择,请手动输入路径');
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
  return new Date(date).toLocaleString('zh-CN');
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

.btn-add {
  background: #2da44e;
  color: white;
  border: none;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  cursor: pointer;
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

.explorer-header h2 {
  margin: 0 0 4px 0;
  font-size: 20px;
  color: #24292f;
}

.path {
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
  margin-top: 16px;
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
</style>
