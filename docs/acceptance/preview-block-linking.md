# Preview 结构块联动验收

- 数据：扫描记录持久化 OCR 块及页面坐标，旧记录返回空数组。
- 图片：SVG 与图片位于同一个 `previewer-image-wrap`，缩放前后框的归一化 x 与宽度保持一致。
- PDF：每页 SVG 使用该 PDF 页面的 `viewBox`，随页面缩放和滚动；点击 Markdown 块可定位相应页。
- Markdown：Vditor 渲染结束后按 OCR 内容与阅读顺序写入 `data-ocr-block-id`；共享 active/locked id 完成双向高亮和点击锁定。
- 可见性：块仅存在于 Preview；右侧切换 Edit 后语义块节点为 0，左侧图片仍因保持 Preview 而显示。DOCX 左侧没有空间框入口。
- 浏览器：Chromium 在 1024、768、480 三档完成联动截图和交互断言。
