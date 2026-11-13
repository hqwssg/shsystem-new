Vue 3 统一升级说明（2026-11-13）

一、范围
本次升级 ruoyi-ui 和 tpfhs-9/frontend。GoView 不变。
标准 Vue 3，不依赖 @vue/compat；保留 Options API、JavaScript、原有业务接口和布局。
主前端使用 Vuex 4.1.0，不迁移 Pinia。没有数据库脚本、数据初始化或后端算法变更。

二、版本
两个前端 dependencies：
vue 3.5.34、element-plus 2.13.7、axios 1.16.0（以上均精确锁定）；
echarts ^5.5.1、vue-router ^4.4.5、@element-plus/icons-vue ^2.3.1。
devDependencies：@vitejs/plugin-vue ^5.0.4、vite ^5.2.8、@vue/compiler-sfc 3.5.34。
package-lock.json 已提交，安装请使用 npm ci，不能丢弃锁文件重新生成。
验证环境 Node 24.22.1 / npm 11.6.2；请使用 Node 20 或以上，建议统一交付方的 Node 22/24 构建环境。
原 npm run build:prod、npm run build:stage（主前端）、npm run build:server（模型前端）入口保留。

三、主要修改
主前端从 Vue CLI/Webpack 改为 Vite，入口 HTML 移到 ruoyi-ui/index.html。
createApp、Vuex 4、Router 4 动态路由及退出后的清理；权限规则沿用各自分支。
Element Plus 的图标、日期格式、表单绑定、弹窗、插槽、表格、上传和分页适配。
树选择使用 Element Plus；数字动画使用现有界面所需的小组件；剪贴板、裁剪和拖拽改为 Vue 3 用法。
表单设计器和导出 Vue 文件使用 Vue 3 语法。移除旧 Element UI 主题文件、Vue 2 编译器、Vue CLI 和无调用的旧弹窗拖拽指令。
主题切换使用 Element Plus CSS 变量，不再下载 Element UI 样式。
VUE_APP_ 前缀保留；浏览器源码改为 import.meta.env，私有配置仍由部署环境提供。
已有 .env 文件不在本次补丁中覆盖；不要把服务端密钥写进 VUE_APP_ 变量。

四、同步远程
交付补丁以 a51f29c381205e3a7c3a62856ba1804704988166 为基线。
先在干净分支或独立工作目录操作，保存当前源码提交及原前端静态文件。
在仓库根目录执行：
  git apply --check <解压目录>/upgrade.patch
  git apply <解压目录>/upgrade.patch
若基线已更新且检查不通过，先比较冲突，不能用整个本地仓库覆盖远程。
changed-files/ 供逐文件审阅；tools/start-local.ps1 仅提供补丁，不分发完整启动配置。
deleted-files.txt 中列出的旧文件也需删除，单纯覆盖会留下旧构建入口。
没有自动推送、自动上线、自动初始化数据库的操作。

五、安装、校验、构建
从仓库根目录运行以下命令，每个步骤成功后再执行下一项：
  npm --prefix ruoyi-ui ci
  npm --prefix tpfhs-9/frontend ci
  node scripts/vue3/check.cjs
  node scripts/vue3/test_router.cjs
  node scripts/vue3/test_request.cjs
  node scripts/energy-analysis/test_navigation.cjs
  node scripts/test-heavy-upgrade-20261109.cjs
  node scripts/test-single-upgrade-20261109.cjs
  node scripts/energy-analysis/test_artifact_downloads.cjs
  node scripts/energy-analysis/test_document_downloads.cjs
  node scripts/report-period/test_frontend.cjs
  node scripts/report-compat/test_report_imports.mjs
  node scripts/report-compat/test_monitoring_import.mjs
  node scripts/report-compat/test_monitoring_ui.mjs
  npm --prefix ruoyi-ui run build:prod
  npm --prefix tpfhs-9/frontend run build:server
需要预发布包时再运行 npm --prefix ruoyi-ui run build:stage。
主前端产物仍为 ruoyi-ui/dist；模型前端仍为 tpfhs-9/frontend/dist，生产 base 为 /carbon-model/。
现有 docker/web-main 使用预构建静态文件，这两个目录的交付位置不变。不要修改 GoView 镜像或复制 GoView 产物。
部署时替换完整静态文件目录并清理页面缓存；仅复制新的 index.html 不够，旧缓存可能引用旧资源。
本地开发：后端 8081/8082 启动后，分别在两个前端目录执行 npm run dev。
本次本地已运行主前端 80、模型前端 5177，仍沿用各自本地 .env 配置。

六、验收与限制
详见 VALIDATION.txt。组件编译和现有前端业务回归不等于所有真实业务任务已重新运行。
请在交付环境复验：登录/退出及角色菜单、模型嵌入、统计筛选/导出、报告导入/生成/下载、算法表单与结果附件。
本轮浏览器实际下载 Excel 未获得授权，因此真实文件落盘未计为通过；没有通过其他方式绕过下载授权。
没有自动提交新的算法任务或重算业务数据。

七、回退
先切回部署前保留的两个完整静态目录，确保 index.html 与其资源来自同一版本。
源码未叠加其他修改时，先检查：
  git apply --check <解压目录>/rollback.patch
再执行 git apply <解压目录>/rollback.patch。
源码已有后续修改时，按本次提交进行 revert/人工合并，避免覆盖后续工作。
回退源码后要使用对应旧锁文件重新安装并构建；不要在 Vue 3 的 node_modules 上直接运行旧 Vue CLI。
本地源码回退标签：pre-sync-66-vue3-unification-20261113。
私有配置回退引用只保存在本机 refs/local-config/，不随交付包分发。

参考官方迁移说明：
https://v3-migration.vuejs.org/breaking-changes/
https://router.vuejs.org/guide/migration/
https://element-plus.org/en-US/component/date-picker.html
