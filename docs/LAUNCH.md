# 上线清单

面向将 PawStay 部署到公网域名时的检查项。本地开发可忽略「真实支付 / 短信」相关条目。

## 1. 环境变量（`.env`）

| 变量 | 要求 |
| --- | --- |
| `DJANGO_DEBUG` | `false` |
| `DJANGO_SECRET_KEY` | ≥50 字符随机串，勿用 `django-insecure-` |
| `DJANGO_ALLOWED_HOSTS` | 正式域名，如 `stay.example.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://stay.example.com` |
| `DJANGO_SECURE_SSL_REDIRECT` | `true`（或由前置 LB 终结 TLS） |
| `DJANGO_HSTS_SECONDS` | 建议 `31536000`（确认全站 HTTPS 后再开） |
| `MYSQL_*` | 生产库账号与密码 |
| `EMAIL_HOST` 等 | SMTP，用于 500 告警与密码重置邮件 |
| `SMS_BACKEND` | `aliyun`，并填写 AccessKey / 签名 / 模板 |
| `ADMIN_REQUIRE_2FA` | `true` |
| `PAYMENT_SANDBOX` | 真实收款时 `false` |
| `WECHAT_*` / `ALIPAY_*` | 商户号、密钥；退款另需 `WECHAT_CERT_PATH`、`WECHAT_KEY_PATH` |
| `SITE_*` | 品牌名、电话、地址、ICP |

完整键名见项目根目录 `.env.example`。

## 2. 一键验收

```bash
make launch-accept   # 路由 + 关键配置自检
make deploy-check    # Django check --deploy
make test            # 单元测试
```

## 3. 上线后冒烟

1. 打开首页与房间列表，确认门店切换与图片加载
2. 注册 / 登录 → 建宠物 → 预约 → 沙箱或真实支付
3. 后台房态日历点格开单；办理入住并写一条护理记录
4. 取消一笔已支付订单，确认退款流水（失败会标 `RETRY-` 并由 scheduler 重试）
5. 会员中心查看积分与优惠券

## 4. Docker

```bash
cp .env.example .env   # 填好后
make docker-up
make docker-seed       # 可选演示数据
```

`scheduler` 每 5 分钟执行：超时取消、候补通知、退款重试。
