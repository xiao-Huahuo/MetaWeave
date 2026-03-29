<template>
  <div class="tree-node">
    <div class="kb-item tree-row" :class="{ active: false, root: node.isRoot }">
      <button
        v-if="node.isDir"
        class="tree-toggle"
        :class="{ open: expandedPaths.has(node.path) }"
        @click.stop="$emit('toggle', node.path)"
        aria-label="toggle"
      >
        <svg viewBox="0 0 16 16" width="10" height="10">
          <path d="M6 3l5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <span v-else class="tree-toggle placeholder"></span>
      <svg v-if="node.isDir" class="kb-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
      </svg>
      <svg v-else class="kb-icon tree-file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
        <polyline points="13 2 13 9 20 9"></polyline>
      </svg>
      <span
        class="kb-name tree-name"
        @click="$emit('open', node)"
        @dblclick="$emit('open', node)"
      >{{ node.name }}</span>
    </div>
    <div v-if="node.isDir && expandedPaths.has(node.path)" class="tree-children">
      <TreeNode
        v-for="child in node.children"
        :key="child.path"
        :node="child"
        :expanded-paths="expandedPaths"
        @toggle="$emit('toggle', $event)"
        @open="$emit('open', $event)"
      />
    </div>
  </div>
</template>

<script setup>
defineProps({
  node: { type: Object, required: true },
  expandedPaths: { type: Object, required: true },
});

defineEmits(['toggle', 'open']);
</script>

<style scoped>
.tree-row {
  width: 100%;
  padding: 6px 8px;
  border-left: 2px solid transparent;
}

.tree-row.root {
  font-weight: 600;
}

.tree-toggle {
  border: none;
  background: transparent;
  color: #57606a;
  cursor: pointer;
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.tree-toggle.open {
  transform: rotate(90deg);
}

.tree-toggle.placeholder {
  width: 16px;
  height: 16px;
}

.kb-icon {
  width: 14px;
  height: 14px;
  margin-right: 6px;
}

.tree-file-icon {
  color: #57606a;
}

.tree-children {
  margin-left: 8px;
  border-left: 1px solid #eaeef2;
  padding-left: 6px;
}
</style>
