/** Knowledge-work prompt catalog. Cards and prefix completions share the same entries. */
export type PromptStarter = {
  /** Prefix inserted when a card is selected. */
  prefix: string
  /** Short function label displayed on the card. */
  title: string
  /** Semantic name from the shared IcIcon registry. */
  icon: string
  /** Function color registered in the global settings palette. */
  color: keyof typeof import('@/stores/settings').AGENT_STARTER_COLORS
  /** Complete prompts, all beginning with this entry's prefix. */
  suggestions: string[]
}

export const promptStarters: PromptStarter[] = [
  { prefix: '检索', title: '检索知识库', icon: 'manage-search', color: 'search', suggestions: [
    '检索知识库中与当前主题相关的资料，并标注来源',
    '检索能回答这个问题的原文段落',
    '检索不同资料对同一问题的观点与依据',
    '检索某个概念的定义及相关文献',
  ] },
  { prefix: '整理', title: '整理资料', icon: 'folder-open', color: 'organize', suggestions: [
    '整理知识库中的资料，先给出分类方案',
    '整理这个文件夹，找出重复和待归类的文件',
    '整理阅读笔记，按主题归纳重点',
    '整理图书馆中的资料，建议标签和集锦',
  ] },
  { prefix: '阅读', title: '阅读文献', icon: 'book', color: 'read', suggestions: [
    '阅读这篇文献，总结研究问题、方法和结论',
    '阅读这份资料，用易懂的语言解释关键概念',
    '阅读几篇文献，对比方法、结果和局限',
    '阅读这篇论文，提炼值得继续研究的问题',
  ] },
  { prefix: '提取', title: '智能表格', icon: 'table-chart', color: 'extract', suggestions: [
    '提取文献中的研究对象、方法和结论，整理为智能表格',
    '提取这些资料中的关键指标，并保留原文依据',
    '提取多篇论文的信息，先设计对比表格的字段',
    '提取表格中缺失字段的信息，并标出需要核对的内容',
  ] },
  { prefix: '关联', title: '发现知识关联', icon: 'graph', color: 'connect', suggestions: [
    '关联知识库中与这个概念有关的文档和实体',
    '关联几篇资料中的共同主题与不同观点',
    '关联当前笔记与已有文档，建议双向链接',
    '关联知识图谱中的实体，解释它们之间的关系',
  ] },
  { prefix: '撰写', title: '撰写文档', icon: 'edit-note', color: 'write', suggestions: [
    '撰写一份基于知识库资料的主题综述，并注明来源',
    '撰写这份文档的大纲，再按章节展开',
    '撰写一份阅读笔记，保留关键引用',
    '撰写一份报告，将现有笔记整理成连贯的内容',
  ] },
  { prefix: '绘制', title: '绘制图表', icon: 'image', color: 'visualize', suggestions: [
    '绘制一张展示这些数据差异的图表',
    '绘制这份资料的流程图，梳理关键步骤',
    '绘制一个概念关系图，说明知识之间的联系',
    '绘制适合报告的图示，先查找组件库中可复用的素材',
  ] },
  { prefix: '规划', title: '规划任务', icon: 'todo', color: 'plan', suggestions: [
    '规划这个研究主题的阅读与资料收集任务',
    '规划一份待办清单，列出步骤和完成标准',
    '规划这份报告的写作任务与时间安排',
    '规划一个定时整理资料的自动化任务，先确认执行范围',
  ] },
]

/** Uniformly shuffle a copy once per blank conversation; resizing never resamples. */
export function samplePromptStarters(): PromptStarter[] {
  const shuffled = [...promptStarters]
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const target = Math.floor(Math.random() * (index + 1))
    const current = shuffled[index]!
    shuffled[index] = shuffled[target]!
    shuffled[target] = current
  }
  return shuffled.slice(0, 4)
}
