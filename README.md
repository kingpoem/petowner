# PawStay 宠物寄养

面向宠物寄养门店的 Web 应用（课程精简版）：主人在官网查房、预约与支付、查看护理动态；门店在运营后台管理房间、订单与护理记录。

![首页](docs/screenshots/home.png)

| 房间查询与报价 | 订单护理动态 | 运营看板 |
| --- | --- | --- |
| ![房间](docs/screenshots/rooms.png) | ![订单](docs/screenshots/order-detail.png) | ![后台](docs/screenshots/admin-dashboard.png) |

## 功能一览

**顾客端（官网）**

- 房间浏览：按宠物类型、房型、日期查询空房，逐晚报价（连住折扣）
- 账号：手机号 + 短信验证码注册、短信 / 邮件找回密码；登录限流与图形验证码
- 我的宠物：建档（照片、体重、性格、饮食、过敏、疫苗与驱虫）
- 在线预约：日历选入住/离店，费用明细实时刷新；校验类型、体型、性格与疫苗
- 在线支付：微信 / 支付宝收银台（沙箱或真实渠道）；超时未支付自动取消
- 自助改期与取消：入住日前可改期（多退少补）；取消按违约金规则退款
- 订单进度、护理时间线、评价与站内通知
- 增值服务：接送、加长遛弯、视频探视、喂药、洗护、SPA、生日布置，可按次或按晚加购
- 优惠码、会员等级（萌新 / 银卡 / 金卡 / 黑金）与积分抵扣；完成寄养按实付累计积分
- 健康护照：疫苗接种记录自动回写有效期，用药计划在入住时生成护理任务
- 满房候补、节假日日历房价、门店公告、物资库存与员工任务

数据库在本机 MySQL 运行，不使用 Docker。Windows 可执行：

```bash
uv run python scripts/dev.py seed
uv run python scripts/dev.py run
```

**运营后台（`/admin/`）**

- 运营看板：今日入住 / 离店、在住率、本月净收入、待收款、评分
- 房态日历、可用房间查询、订单办理入住 / 离店 / 取消 / 收款
- 房间、护理记录、收退款流水、评价回复、站内通知
- 角色：预置「前台」「护理师」权限组

## 快速开始

依赖：Python 3.13、[uv](https://docs.astral.sh/uv/)、GNU Make、MySQL 8+。

```bash
make seed   # 安装依赖、建库、迁移、写入演示数据
make run    # http://127.0.0.1:8000/
make test   # 全部单元测试
make help   # 全部命令
```

演示账号：

| 角色 | 入口 | 账号 / 密码 |
| --- | --- | --- |
| 管理员 | `/admin/` | `admin` / `admin123` |
| 顾客 | `/account/login/` | `13800000001` / `pawstay123` |

本地运行说明见 [docs/LAUNCH.md](docs/LAUNCH.md)。开发环境短信验证码会打印在 `make run` 控制台。

## 项目结构

```
apps/
  pets/           宠物主人与宠物档案
  rooms/          房间与报价计算
  bookings/       订单、收退款、改期与违约金、房态日历
  care/           护理记录与评价
  notifications/  站内通知（可选同步业务短信）
  payments/       微信 / 支付宝 / 沙箱收银台
  security/       图形验证码、短信验证码、登录限流
  stores/         门店（单店模型）
  web/            官网与个人中心
config/           Django 配置
templates/        页面模板
static/           样式、图标、图片
docs/             说明文档与截图
```
