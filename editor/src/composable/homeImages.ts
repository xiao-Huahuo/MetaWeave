/**
 * 主页背景图注册表。
 *
 * 用法:
 * 通过 import.meta.glob 一次性加载 home 目录下全部块的背景图,
 * 按「块名 + 形状」分组, 供 useHomeBlockImage 取用。
 *
 * 图片目录约定:
 *   assets/images/home/<块名>/block/*       方形图
 *   assets/images/home/<块名>/rectangle/*   矩形图
 *
 * 不硬编码任何具体图片的文件名/格式/数量: 换图、换格式或增减张数都无需改代码;
 * 某块没有对应目录时其分组为空, 调用方自然回退到纯色底。
 */

/** 某一块在两种形状下的图片 URL 池。 */
export interface HomeImageSet {
  /** 方形(宽高比接近 1)图片池。 */
  block: string[]
  /** 矩形(明显横扁)图片池。 */
  rectangle: string[]
}

type HomeImageShape = keyof HomeImageSet

const modules = import.meta.glob(
  '@/assets/images/home/*/{block,rectangle}/*.{png,jpg,jpeg,webp,avif,gif,svg}',
  { eager: true, import: 'default' },
) as Record<string, string>

/** 块名 → 两种形状图片池 的注册表(模块级只构建一次)。 */
export const homeImageSets: ReadonlyMap<string, HomeImageSet> = (() => {
  const map = new Map<string, HomeImageSet>()
  for (const [path, url] of Object.entries(modules)) {
    const match = path.match(/\/home\/([^/]+)\/(block|rectangle)\/[^/]+$/)
    if (!match) continue
    const [, name, shape] = match
    if (!name || !shape) continue
    let set = map.get(name)
    if (!set) {
      set = { block: [], rectangle: [] }
      map.set(name, set)
    }
    set[shape as HomeImageShape].push(url)
  }
  return map
})()

/** 取某块的图片池; 该块无图时返回 undefined。 */
export function getHomeImageSet(name: string): HomeImageSet | undefined {
  return homeImageSets.get(name)
}
