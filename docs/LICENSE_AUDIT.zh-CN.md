# translate-layout-pdf 开源许可证审计

审计日期：2026-09-05

## 可发布结论

当前实现可以放入 Git 公共仓库，但仓库应使用 **AGPL-3.0-only**，并保留 `LICENSE`、`THIRD_PARTY_NOTICES.md` 和 `requirements.txt`。原因是核心引擎在进程内直接 import 并调用 PyMuPDF；PyMuPDF 的官方授权是 GNU AGPL v3 或单独的 Artifex 商业许可。官方明确说明，分发调用它的应用时需要履行 AGPL 开源义务。

如果希望将本项目改为 MIT、BSD 或 Apache-2.0，则不能继续按当前方式使用 AGPL 版 PyMuPDF。可行路径只有两类：

1. 从 Artifex 获得覆盖该用途和分发方式的 PyMuPDF 商业许可。
2. 完整替换 PyMuPDF/MuPDF 引擎，并重新审计替代库及其传递依赖。

## 运行依赖

| 组件 | 当前测试版本 | 许可证 | 对项目的影响 |
|---|---:|---|---|
| PyMuPDF / MuPDF | 1.26.5 | AGPL-3.0 或 Artifex 商业许可 | 决定当前公开版项目采用 AGPL-3.0-only |
| Pillow | 11.1.0 | MIT-CMU | 可与 AGPL 项目一起使用；分发依赖时保留其声明 |
| fontTools | 4.55.3 | MIT | 可与 AGPL 项目一起使用；分发依赖时保留其声明 |
| jsonschema | 4.23.0 | MIT | 可与 AGPL 项目一起使用；分发依赖时保留其声明 |

当前 Skill ZIP 不包含这些第三方 wheel 或源码，只在 `requirements.txt` 中声明版本范围。如果以后发布 Docker 镜像、EXE、离线安装包或 vendored Python 环境，还必须把实际随包分发的每个直接和传递依赖的许可文本一起带上。

## 设计参考项目

| 项目 | 审计提交 | 许可证 | 当前关系 |
|---|---|---|---|
| Archify | `06dd052602dd9a369e4d034e24faef0917b5a60c` | MIT | 只参考 Skill 分层、类型化中间表示、验证证据和原子交付理念 |
| BabelDOC | `38d3896dcde9b5a940c62cf5563cadea673a64d3` | AGPL-3.0 | 只研究解析、翻译和重建的职责分离 |
| PDFMathTranslate | `f273d5434c4ed3baac2d66097cec636bd8cd3e4b` | AGPL-3.0 | 只研究公式保护和 PDF 翻译流程 |
| PDFMathTranslate-next | `3538a8195d8379fe3fb4a0117c88d15c5b7b5e89` | AGPL-3.0 | 只研究后端边界和文档重建流程 |

当前仓库不包含上述四个项目的源文件、渲染器、schema、测试样片、图片、字体或运行依赖。对当前 Skill 和四个参考仓库做了长行文本扫描，没有发现长度至少 80 字符的完全相同代码或文档行。这个扫描是来源审计证据，不能代替人工版权判断。

Archify 的 MIT 许可允许复制和改作，但如果未来实际复制了其软件或文档的实质部分，必须同时保留 Archify LICENSE 中的版权和许可声明。当前 `THIRD_PARTY_NOTICES.md` 已自愿保留项目名称、提交号、许可证和设计参考范围。

## 字体和样片

- Skill 仓库不包含字体文件。
- Windows 上开发时使用的等线字体报告 `fsType = 8`，即可编辑嵌入；它仍是 Microsoft 提供的系统字体，不应把 TTF/TTC 文件加入公共仓库。
- Linux 默认候选是 Noto Sans CJK。只有确认实际字体包是 SIL OFL-1.1 并同时附带 OFL 文本后，才应随发布包分发字体。
- 合成测试 PDF 由测试代码在本地生成，可以放入 CI。用于验收的 ACL/NeurIPS 论文页及翻译样片不在 Skill ZIP 中，不应在未审核论文版权条款时一起发布。

## 发布前必须保留

- `LICENSE`：GNU AGPL v3 完整文本。
- `SKILL.md` 头部的 `license: AGPL-3.0-only`。
- `THIRD_PARTY_NOTICES.md`：直接依赖、设计参考、字体和发布注意事项。
- `requirements.txt`：已审计的直接依赖版本范围。
- 公开并保持实际分发版本的完整对应源码，包括网络服务中使用的修改版。

## 核对来源

- PyMuPDF 官方授权说明：https://pymupdf.io/ 和 https://github.com/pymupdf/PyMuPDF
- MuPDF 官方仓库和 COPYING：https://github.com/ArtifexSoftware/mupdf
- Pillow LICENSE：https://github.com/python-pillow/Pillow/blob/main/LICENSE
- fontTools 仓库和 LICENSE：https://github.com/fonttools/fonttools
- jsonschema pyproject 与 COPYING：https://github.com/python-jsonschema/jsonschema
- Archify LICENSE：https://github.com/tt-a1i/archify/blob/main/LICENSE
- BabelDOC：https://github.com/funstory-ai/BabelDOC
- PDFMathTranslate 组织仓库：https://github.com/PDFMathTranslate

这是针对当前源码、依赖和预定公开发布方式做的工程合规审计。如果将来需要闭源商业分发、SaaS 提供或与其他强 copyleft 组件组合，应让法务或知识产权律师审查实际发布结构和 Artifex 商业许可条款。
