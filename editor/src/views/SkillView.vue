<!--
  Skill configuration page.

  Usage:
  Shows built-in and user-level Agent skills, lets the user enable/disable
  them, create custom skills, and read the local Skill format guide.
-->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import { useSkillsStore } from '@/stores/skills'
import { useSettingsStore } from '@/stores/settings'

const skillsStore = useSkillsStore()
const settingsStore = useSettingsStore()
const activeTab = ref<'overview' | 'custom'>('overview')
const specOpen = ref(false)
const tabSwitchRef = ref<HTMLElement | null>(null)
const tabSliderStyle = ref({ width: '0px', left: '0px' })
const name = ref('')
const description = ref('')
const body = ref('')

const groupedSkills = computed(() => [
  { title: '内置 Skill', items: skillsStore.builtinSkills },
  { title: '用户 Skill', items: skillsStore.userSkills },
])

async function openSpec() {
  await skillsStore.loadSpec()
  specOpen.value = true
}

async function createCustomSkill() {
  await skillsStore.addUserSkill({
    name: name.value,
    description: description.value,
    body: body.value,
  })
  name.value = ''
  description.value = ''
  body.value = ''
  activeTab.value = 'overview'
}

function updateTabSlider() {
  nextTick(() => {
    const container = tabSwitchRef.value
    if (!container) return
    const active = container.querySelector('.page-switch-button.active') as HTMLElement | null
    if (!active) return
    tabSliderStyle.value = {
      width: `${active.offsetWidth}px`,
      left: `${active.offsetLeft}px`,
    }
  })
}

function switchTab(tab: 'overview' | 'custom') {
  activeTab.value = tab
  updateTabSlider()
}

onMounted(() => {
  void skillsStore.loadSkills()
  updateTabSlider()
})

watch(
  () => [
    settingsStore.profile.userId,
    settingsStore.profile.knowledgeDir,
    settingsStore.profile.activeLibraryId,
  ],
  () => {
    void skillsStore.loadSkills()
  },
)
</script>

<template>
  <section class="skill-page">
    <header class="skill-header">
      <div ref="tabSwitchRef" class="resource-page-switch" role="tablist" aria-label="Skill views">
        <div class="page-slider" :style="tabSliderStyle"></div>
        <button type="button" class="page-switch-button" :class="{ active: activeTab === 'overview' }" @click="switchTab('overview')">
          <IcIcon name="document" :size="17" />
          <span>概览</span>
        </button>
        <button type="button" class="page-switch-button" :class="{ active: activeTab === 'custom' }" @click="switchTab('custom')">
          <IcIcon name="tune" :size="17" />
          <span>定制</span>
        </button>
      </div>
      <div class="header-actions">
        <button type="button" class="view-button" title="刷新" aria-label="刷新" @click="skillsStore.loadSkills">
          <IcIcon name="refresh" :size="16" />
        </button>
        <button type="button" class="view-button" title="规范" aria-label="规范" @click="openSpec">
          <IcIcon name="book" :size="16" />
        </button>
      </div>
    </header>

    <p v-if="skillsStore.error" class="error-line">{{ skillsStore.error }}</p>

    <div v-if="activeTab === 'overview'" class="overview">
      <div v-if="skillsStore.loading" class="empty-line">Loading skills...</div>
      <section v-for="group in groupedSkills" :key="group.title" class="skill-group">
        <div class="group-title">
          <h2>{{ group.title }}</h2>
          <span>{{ group.items.length }}</span>
        </div>
        <div v-if="group.items.length" class="skill-grid">
          <TransitionGroup appear name="sc" tag="div" class="skill-grid-inner">
          <article v-for="(skill, i) in group.items" :key="skill.skill_id" class="skill-card" :style="{ '--i': i }">
            <div class="card-head">
              <div>
                <h3>{{ skill.name }}</h3>
                <p>{{ skill.skill_id }}</p>
              </div>
              <label class="switch" :title="skill.enabled ? '关闭' : '启用'" @click.stop>
                <input
                  type="checkbox"
                  :checked="skill.enabled"
                  :disabled="skillsStore.saving"
                  @change="skillsStore.updateEnabled(skill.skill_id, ($event.target as HTMLInputElement).checked)"
                />
                <span class="toggle-bg"></span>
                <span class="toggle-thumb">
                  <span class="toggle-dot"></span>
                </span>
              </label>
            </div>
            <p class="description">{{ skill.description || 'No description.' }}</p>
            <div class="card-footer">
              <div class="meta-row">
                <span>{{ skill.source }}</span>
                <span v-if="skill.has_references">references</span>
                <span v-if="skill.has_scripts">scripts</span>
                <span v-if="skill.has_assets">assets</span>
              </div>
              <p class="path">{{ skill.path }}</p>
            </div>
          </article>
          </TransitionGroup>
        </div>
        <div v-else class="empty-line">No skills.</div>
      </section>
    </div>

    <form v-else class="custom-form" @submit.prevent="createCustomSkill">
      <label>
        <span>名称</span>
        <input v-model.trim="name" type="text" required placeholder="writing-helper" />
      </label>
      <label>
        <span>描述</span>
        <input v-model.trim="description" type="text" placeholder="何时应该使用这个 Skill" />
      </label>
      <label>
        <span>正文</span>
        <textarea v-model="body" rows="12" placeholder="写入 SKILL.md 的正文指令"></textarea>
      </label>
      <button type="submit" class="primary-button" :disabled="skillsStore.saving || !name.trim()">
        <IcIcon name="new-folder" :size="16" />
        <span>创建 Skill</span>
      </button>
    </form>

    <div v-if="specOpen" class="spec-overlay" @click.self="specOpen = false">
      <section class="spec-modal" role="dialog" aria-modal="true" aria-label="Skill 规范">
        <header>
          <h2>Skill 规范文档</h2>
          <button type="button" class="icon-button" title="关闭" aria-label="关闭" @click="specOpen = false">
            <IcIcon name="close" :size="18" />
          </button>
        </header>

        <div class="spec-body">
          <section class="spec-section">
            <h3>什么是 Skill？</h3>
            <p>
              Skill（技能）是 AI Agent 从通用型走向专用型的关键能力载体。它将领域知识、操作规范与可执行脚本封装为可复用的模块，使 Agent 能够在特定场景下表现出专家级别的行为。一个 Skill 可以理解为 Agent 的"插件"——它告诉 Agent 在遇到特定任务时应该调用哪些知识、遵循什么流程、使用什么工具。
            </p>
            <p>
              MetaWeave 的 Skill 系统同时兼容 <strong>OpenAI Skills 标准</strong>与 <strong>Anthropic Agent Skills 扩展字段</strong>，这意味着你可以将在其他平台开发的 Skill 无缝迁移到 MetaWeave 中使用。
            </p>
          </section>

          <section class="spec-section">
            <h3>目录结构</h3>
            <p>每个 Skill 是一个独立目录，以 Skill 名称命名，放置在对应的 Skill 根目录下：</p>
            <div class="spec-code-block">
              <pre>skill-name/                # 目录名即 Skill 名称（小写字母、数字、连字符）
  SKILL.md                 # 必需的 Skill 定义文件
  scripts/                 # 可选的可执行脚本目录
  references/              # 可选的参考文档目录
  assets/                  # 可选的资源文件目录</pre>
            </div>
            <div class="spec-note">
              <strong>存放路径：</strong>内置 Skill 位于 <code>resources/skills/</code>，用户级 Skill 位于知识库目录下的 <code>.agents/skills/</code>，按知识库隔离。
            </div>
          </section>

          <section class="spec-section">
            <h3>SKILL.md — 核心定义文件</h3>
            <p>
              <code>SKILL.md</code> 是 Skill 的核心，使用 Markdown 编写。它告诉 Agent 这个 Skill 能做什么、在什么场景下触发、以及具体的行为指令。兼容 OpenAI 与 Anthropic 的 Skill 元信息格式：
            </p>
            <div class="spec-code-block">
              <pre>---
name: skill-name
description: 一句话描述 Skill 的用途和触发场景
model: (可选) 推荐使用的模型
temperature: (可选) 推理温度
tools: (可选) 需要启用的工具列表
---

## 行为指令

在这里用清晰的 Markdown 描述 Agent 应该遵循的行为规范。
包括具体的步骤、规则、边界条件和输出格式要求。

## 使用示例

提供 1-2 个典型场景示例，帮助 Agent 理解如何应用此 Skill。</pre>
            </div>
          </section>

          <section class="spec-section">
            <h3>Skill 路由机制</h3>
            <p>
              MetaWeave 的 <strong>Skill 路由器</strong>在 Agent 每次接收用户输入时自动工作：
            </p>
            <ol>
              <li><strong>智能路由：</strong>调用轻量级模型分析当前用户输入，匹配最相关的 3 个 Skill。小模型不可用或异常时，降级为关键词与 description 的简单匹配。</li>
              <li><strong>按需注入：</strong>将匹配到的 Skill 的 <code>SKILL.md</code> 正文注入当前推理上下文。</li>
              <li><strong>单轮有效：</strong>Skill 正文默认仅对当前轮对话生效，下一轮重新路由，避免上下文污染。</li>
              <li><strong>主动召唤：</strong>用户可通过 "使用 Skill：skill-name" 的格式主动召唤指定 Skill。</li>
            </ol>
          </section>

          <section class="spec-section">
            <h3>可选的附属目录</h3>
            <div class="spec-grid">
              <div class="spec-grid-item">
                <strong>scripts/</strong>
                <p>包含 Agent 可调用的 Python 脚本或其他可执行文件。Agent 在沙盒或完全访问模式下执行这些脚本以完成具体操作。</p>
              </div>
              <div class="spec-grid-item">
                <strong>references/</strong>
                <p>存放参考文档、API 规格说明、格式定义等辅助资料，Agent 在任务执行时可查阅。</p>
              </div>
              <div class="spec-grid-item">
                <strong>assets/</strong>
                <p>存放图表、模板文件、配置文件等静态资源，供 Skill 执行时使用。</p>
              </div>
            </div>
          </section>

          <section class="spec-section">
            <h3>Skill 最佳实践</h3>
            <ul class="spec-tips">
              <li><strong>职责单一：</strong>每个 Skill 只专注一个领域的任务，保持描述精炼、行为明确。</li>
              <li><strong>描述精准：</strong><code>description</code> 字段是路由匹配的关键，使用清晰的关键词描述触发场景。</li>
              <li><strong>示例丰富：</strong>在 SKILL.md 中包含典型使用示例，帮助 Agent 快速理解正确用法。</li>
              <li><strong>独立可测：</strong>Skill 应尽可能自包含，减少对外部环境的隐式依赖。</li>
              <li><strong>安全优先：</strong>scripts 中的代码需要经过审查，避免执行危险操作。</li>
              <li><strong>版本兼容：</strong>遵循 OpenAI 核心标准确保跨平台兼容性，利用 Anthropic 扩展字段增强 MetaWeave 中的表现。</li>
            </ul>
          </section>

          <section class="spec-section">
            <h3>兼容性标准</h3>
            <p>
              统一兼容 <a href="https://developers.openai.com/api/docs/guides/tools-skills" target="_blank" rel="noopener">OpenAI 开放标准</a>作为主标准，兼容 <a href="https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview" target="_blank" rel="noopener">Anthropic 标准</a>扩展字段。
            </p>
            <p>
              这种双标准兼容的设计使得 Skill 可以跨平台复用——在 OpenAI 生态中开发的 Skill 可直接用于 MetaWeave，反之亦然。
            </p>
          </section>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.skill-page {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: var(--space-8) var(--space-12) var(--space-20);
  background: var(--color-bg-app);
  color: var(--color-text-primary);
}

.skill-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-12);
  min-height: 44px;
  margin-bottom: var(--space-16);
  font-size: calc(12px * var(--font-scale));
}

.group-title h2,
.skill-card h3,
.spec-modal h2 {
  margin: 0;
}

.card-head p,
.path,
.description,
.empty-line {
  margin: var(--space-4) 0 0;
  color: var(--color-text-muted);
}

.header-actions,
.card-head,
.group-title,
.meta-row,
.spec-modal header,
.spec-tree {
  display: flex;
  align-items: center;
}

.header-actions {
  gap: var(--space-8);
}

.icon-button,
.primary-button {
  border: 1px solid var(--color-border);
  background: var(--color-bg-panel);
  color: var(--color-text-primary);
}

.icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
}

.view-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--color-border);
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-secondary);
}

.view-button:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.primary-button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
  min-height: 32px;
  padding: 0 var(--space-12);
  border-radius: var(--radius-sm);
}

.resource-page-switch {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 2px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
}

.page-slider {
  position: absolute;
  top: 2px;
  height: calc(100% - 4px);
  border-radius: 999px;
  background: var(--color-primary-softer);
  transition: left 250ms ease, width 250ms ease;
  z-index: 0;
  pointer-events: none;
}

.page-switch-button {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
  height: 28px;
  padding: 0 var(--space-8);
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  outline: none;
}

.page-switch-button:hover {
  color: var(--color-primary);
}

.page-switch-button.active {
  color: var(--color-primary);
}

.primary-button {
  background: var(--color-primary);
  color: #fff;
}

.overview,
.custom-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-20);
}

.skill-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}

.group-title {
  justify-content: space-between;
  border-bottom: 1px solid var(--color-border);
  padding-bottom: var(--space-8);
}

.group-title h2 {
  font-size: 15px;
}

.skill-grid {
  display: contents;
}

.skill-grid-inner {
  column-width: 360px;
  column-gap: var(--space-12);
}

.skill-card {
  position: relative;
  display: inline-flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  min-height: 88px;
  min-width: 0;
  margin-bottom: var(--space-12);
  padding: 14px;
  border: 1px solid var(--color-border);
  border-radius: 28px;
  background: var(--color-surface);
  outline: 2px solid var(--workspace-panel-outline);
  outline-offset: 2px;
  box-shadow: 0 0 0 2px var(--library-form-ring);
  color: var(--color-text);
  transition: background var(--transition-fast), border-color var(--transition-fast);
  break-inside: avoid;
  page-break-inside: avoid;
  vertical-align: top;
}

.skill-card:hover {
  background: var(--color-surface-raised);
}

/* TransitionGroup animations */
.sc-move {
  transition: transform 400ms ease;
}

.sc-enter-active {
  animation: sc-card-in 350ms ease both;
  animation-delay: calc(var(--i, 0) * 40ms);
}

.sc-leave-active {
  transition: opacity 300ms ease;
}

.sc-leave-to {
  opacity: 0;
}

@keyframes sc-card-in {
  from {
    opacity: 0;
    transform: scale(0.92) translateY(12px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.card-head {
  justify-content: space-between;
  gap: var(--space-6);
}

.skill-card h3 {
  font: 600 calc(13px * var(--font-scale))/1.45 var(--font-ui);
  margin: 0;
}

.card-head p {
  overflow-wrap: anywhere;
  font-size: 11px;
  margin: var(--space-2) 0 0;
}

.description {
  font-size: 13px;
  line-height: 1.55;
  color: var(--color-text-secondary);
  margin: 0;
}

.card-footer {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  padding-top: var(--space-10);
  border-top: 1px solid var(--color-border);
  min-height: 64px;
  justify-content: center;
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
}

.meta-row span {
  padding: 2px var(--space-8);
  border: 1px solid color-mix(in srgb, var(--color-primary) 42%, transparent);
  border-radius: 999px;
  background: var(--color-primary-softer);
  color: var(--color-primary);
  font-size: 11px;
}

.path {
  overflow-wrap: anywhere;
  font-size: 11px;
  margin: 0;
  color: var(--color-text-tertiary);
}

/* === tool-registry style toggle === */
.skill-card .switch {
  position: relative;
  width: 32px;
  height: 20px;
  flex-shrink: 0;
}

.skill-card .switch input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
}

.skill-card .switch .toggle-label {
  display: block;
  width: 100%;
  height: 100%;
  position: static;
}

.skill-card .switch .toggle-label::after {
  display: none;
}

.skill-card .switch .toggle-bg {
  position: absolute;
  inset: 0;
  margin: auto;
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: var(--color-text-muted);
  opacity: 0.3;
  transition: opacity 0.3s, background 0.3s;
  pointer-events: none;
}

.skill-card .switch .toggle-thumb {
  position: absolute;
  top: 0;
  left: 0;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--color-text-tertiary);
  transition: left 0.3s, background 0.3s;
  pointer-events: none;
  z-index: 1;
  margin: auto;
  bottom: 0;
}

.skill-card .switch .toggle-dot {
  position: absolute;
  inset: 0;
  margin: auto;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-surface);
  transition: transform 0.2s;
}

.skill-card .switch input:checked ~ .toggle-bg {
  opacity: 1;
  background: var(--color-primary);
}

.skill-card .switch input:checked ~ .toggle-thumb {
  left: 16px;
  background: var(--color-primary);
}

.skill-card .switch input:checked ~ .toggle-thumb .toggle-dot {
  transform: scale(0);
}

.custom-form {
  max-width: 760px;
}

.custom-form label {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  color: var(--color-text-muted);
}

.custom-form input,
.custom-form textarea {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-10);
  background: var(--color-bg-panel);
  color: var(--color-text-primary);
  font: inherit;
}

.custom-form textarea {
  resize: vertical;
  line-height: 1.5;
}

.primary-button {
  align-self: flex-start;
}

.error-line {
  color: var(--color-danger);
}

.spec-overlay {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  align-items: flex-start;
  padding: 48px var(--space-20);
  background: rgba(0, 0, 0, 0.48);
  z-index: 30;
  overflow-y: auto;
}

.spec-modal {
  width: min(960px, calc(100vw - 40px));
  max-height: calc(100vh - 40px);
  overflow-y: auto;
  padding: var(--space-24) var(--space-24);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-lg);
}

.spec-modal header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-20);
  padding-bottom: var(--space-16);
  border-bottom: 2px solid var(--color-border);
}

.spec-modal header h2 {
  margin: 0;
  font-size: 22px;
}

.spec-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-20);
}

.spec-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}

.spec-section h3 {
  margin: 0;
  font-size: 17px;
  color: var(--color-primary);
}

.spec-section p {
  margin: 0;
  line-height: 1.7;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.spec-section ol,
.spec-section ul {
  margin: 0;
  padding-left: var(--space-20);
}

.spec-section li {
  line-height: 1.65;
  color: var(--color-text-secondary);
  font-size: 14px;
  margin-bottom: var(--space-6);
}

.spec-code-block {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-muted);
  overflow-x: auto;
}

.spec-code-block pre {
  margin: 0;
  padding: var(--space-16) var(--space-16);
  font-family: var(--font-code);
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text);
  white-space: pre;
}

.spec-note {
  padding: var(--space-12) var(--space-12);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-primary-softer);
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.55;
}

.spec-note code {
  padding: 1px var(--space-6);
  border-radius: var(--radius-sm);
  background: var(--color-bg-muted);
  font-family: var(--font-code);
  font-size: 12px;
}

.spec-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--space-12);
}

.spec-grid-item {
  padding: var(--space-12);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-muted);
}

.spec-grid-item strong {
  display: block;
  margin-bottom: var(--space-6);
  font-family: var(--font-code);
  font-size: 14px;
  color: var(--color-primary);
}

.spec-grid-item p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text-secondary);
}

.spec-tips {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  padding-left: var(--space-20);
}

.spec-tips li {
  font-size: 14px;
  line-height: 1.65;
  color: var(--color-text-secondary);
}

.spec-tips li strong {
  color: var(--color-text);
}
</style>
