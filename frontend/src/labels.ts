/* 界面展示用的中性标签：对使用者只呈现「AI 模型」，不暴露具体模型厂商与型号。
 *
 * 后端按真实模型名调用；接口输出与前端下拉统一使用中性别名 standard / reasoner，
 * 因此前端源码与打包产物里都不需要出现任何厂商名。
 */

/** 把节点配置 / 接口返回里的模型值折算为界面别名（standard / reasoner / mock） */
export function modelAlias(model?: string | null): string {
  const v = String(model ?? '').trim().toLowerCase()
  if (!v) return 'standard'
  if (v.startsWith('mock')) return 'mock'
  if (v.includes('reason')) return 'reasoner'   // 深度思考档位
  return 'standard'                             // 标准档位（含任何历史遗留值）
}

/** 模型展示名：界面上一律显示「AI 模型」 */
export function modelLabel(model?: string | null): string {
  const v = modelAlias(model)
  if (v === 'mock') return '模拟模式'
  if (v === 'reasoner') return 'AI 模型 · 深度思考'
  if (v === 'standard') return 'AI 模型 · 标准'
  return 'AI 模型'
}

/** 模型下拉框的选项文案 */
export function modelOptionLabel(model: string): string {
  return modelAlias(model) === 'reasoner' ? '深度思考（更慢更细，适合长稿）' : '标准（默认，推荐）'
}
