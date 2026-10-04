/*
 * 子 Agent 头像分配工具。
 *
 * 用法:
 * 从 avatar 目录收集头像图片,按 run_id 哈希稳定分配,保证同一子 Agent
 * 在会话内刷新时头像不变。
 */

const avatarModules = import.meta.glob('@/assets/images/avatar/*.jpg', { eager: true })
const avatars = Object.values(avatarModules)
  .map((module) => (module as { default?: string }).default)
  .filter((value): value is string => typeof value === 'string')

function hashString(value: string): number {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0
  }
  return Math.abs(hash)
}

export function getChildAgentAvatar(runId: string): string {
  if (avatars.length === 0) return ''
  return avatars[hashString(runId) % avatars.length] ?? ''
}
