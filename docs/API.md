# PawStay 开放 API（v1）

面向小程序、渠道对接与自有客户端的 JSON API。基础路径：`/api/v1/`。

## 鉴权

1. **Bearer Token**（推荐）：后台「开放 API → API 令牌」创建后，请求头：

   ```http
   Authorization: Bearer <token>
   ```

2. **Session Cookie**：浏览器已登录业主/员工时可直接调用（CSRF：写操作需同源或使用 Token）。

成功响应：

```json
{ "ok": true, "data": { ... } }
```

失败响应：

```json
{ "ok": false, "error": "说明", "code": "unauthorized" }
```

## 公开接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/health/` | 探活 |
| GET | `/api/v1/rooms/availability/?check_in=&check_out=&species=&store=` | 可订房间 + 报价 |
| GET | `/api/v1/rooms/calendar/?start=&nights=&store=` | 房态日历矩阵 |
| GET | `/api/v1/quotes/?room=&check_in=&check_out=&coupon_code=&redeem_points=` | 单房报价（登录可试算积分券） |

## 业主接口（需业主 Token / 登录）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/bookings/` | 创建预约（JSON：pet, room, check_in, check_out, note, coupon_code, redeem_points） |
| GET | `/api/v1/orders/` | 我的订单 |
| GET | `/api/v1/orders/{order_no}/` | 订单详情（含护理） |
| POST | `/api/v1/orders/{order_no}/cancel/` | 取消 |
| GET | `/api/v1/orders/{order_no}/care-records/` | 护理列表 |
| GET | `/api/v1/orders/{order_no}/care-digest/?date=` | 护理日报摘要 |
| POST | `/api/v1/orders/{order_no}/reviews/` | 评价（≥4 星自动发感谢券） |
| POST | `/api/v1/waitlist/` | 加入候补 |
| DELETE/POST | `/api/v1/waitlist/{id}/` | 取消候补 |
| POST | `/api/v1/invoices/` | 申请电子收据 |
| GET | `/api/v1/invoices/{id}/pdf/` | 下载 PDF |

## 员工接口（需员工 Token / 登录）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/staff/orders/{order_no}/check-in/` | 办理入住 |
| POST | `/api/v1/staff/orders/{order_no}/check-out/` | 办理离店（自动发复购券） |
| POST | `/api/v1/staff/orders/{order_no}/care-records/` | 写护理 |
| POST | `/api/v1/staff/orders/{order_no}/collect/` | 门店收款 |

## 示例

```bash
curl -s "https://example.com/api/v1/rooms/availability/?check_in=2026-10-20&check_out=2026-10-23&species=dog" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

```bash
curl -s -X POST "https://example.com/api/v1/bookings/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pet":1,"room":2,"check_in":"2026-10-20","check_out":"2026-10-23","coupon_code":"WELCOME20"}'
```

渠道对接（美团/小程序）建议：先调 `availability` / `calendar` 查房，再 `bookings` 下单，支付仍走官网收银台或后续扩展支付意图接口。
