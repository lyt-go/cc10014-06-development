# 古建筑修缮管理平台

文保工程师、工匠和监理共同管理古建筑修缮工序，审核修缮方案，签收变更后按确认版施工。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 建筑勘查 | `building_survey` | 勘查记录 | 建筑名称、勘查部位、病害类型 |
| 修缮方案 | `restoration_plan` | 修缮方案 | 方案编号、对应勘查、修缮工艺 |
| 材料核验 | `material_verify` | 材料核验单 | 材料名称、规格型号、供应商 |
| 工匠分配 | `craftsman_assign` | 工匠分配单 | 工匠姓名、技艺类别、资质等级 |
| 工序编排 | `work_sequence` | 工序卡 | 工序名称、前置工序、所需工匠 |
| 质量检查 | `quality_inspect` | 检查记录 | 检查工序、检查项目、技术标准 |
| 历史图纸 | `historical_drawing` | 历史图纸 | 图纸编号、绘制年代、绘制内容 |
| 构件登记 | `component_registry` | 构件档案 | 构件名称、所属建筑、材质类型 |
| 环境监测 | `env_monitor` | 监测数据 | 监测位置、温度读数、湿度读数 |
| 修缮日志 | `restoration_log` | 施工日志 | 施工日期、对应工序、施工内容 |
| 验收记录 | `acceptance_record` | 验收报告 | 验收工序、验收标准、验收结论 |
| 修缮支出 | `funding_use` | 支出记录 | 支出项目、支出类别、预算金额 |
| 档案归档 | `archive_mgmt` | 修缮档案 | 档案名称、档案类别、形成日期 |
| 专家评审 | `expert_review` | 评审意见 | 评审方案、专家姓名、专业领域 |
| 安全交底 | `safety_briefing` | 交底记录 | 交底工序、危险源、防护措施 |
| 施工排期 | `construction_schedule` | 排期计划 | 计划工序、开始日期、结束日期 |
| 变更签证 | `change_order` | 变更签证单 | 变更事项、变更原因、影响工序 |
| 竣工总结 | `completion_summary` | 竣工报告 | 修缮项目、开工日期、竣工日期 |
| 费用交账包 | `fund_package` | 费用交账包 | 交账包编号、关联报告、数据时点、实付净额 |

### 费用交账包（竣工备案用）

修缮支出原本只能导出分散的当前行，无法支撑竣工总结执行备案。费用交账包把
**指定竣工报告范围内**的费用在同一数据时点冻结成包：

- `POST /api/fund-packages/reports/{report_id}`：从竣工报告生成交账包，冻结
  核准支出、负数退款（按原支出归属抵减）和关联签证；
- `GET /api/fund-packages/{id}` / `GET /api/fund-packages/{id}/file`：查看包内
  凭据 / 下载 CSV（合计、逐条明细、排除说明、签证与附件清单同处一份文件）；
- `POST /api/fund-packages/{id}/file`：编制人核对净额后提交备案，重复提交只保留
  一次费用确认；
- `GET /api/fund-packages/reports/{report_id}/new-approved`：查看最新包之后出现
  的新核准行（含迟到退款）。

关键规则：

1. 未核准费用不进实付净额，只在包内“未装入项”留痕说明；
2. 退款必须标注原支出，按原支出归属抵减，原支出超范围或未核准则退款不入包；
3. 超出报告施工范围的支出不得装入（显式施工范围优先，未填时回退到报告工期）；
4. 包内合计、条目、附件来自同一快照时点，之后新增核准行不影响旧包，可再发起新包，
   旧备案与新报告各自按自己的证据继续办理；
5. 竣工报告执行备案前，必须存在一份已备案的费用交账包（备案待办随交账包状态更新）。

种子数据已内置「大殿六月修缮」报告、500 元原款（#4）、60 元退款（#5，归属 #4）、
一笔未核准尾款和一笔超范围支出，可直接验证净额 440 元与逐条可辨性。

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：应用开发
子方向：web前端/全栈开发
