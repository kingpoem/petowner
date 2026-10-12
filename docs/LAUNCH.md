# 本地运行说明

课程精简版本地启动步骤（生产上线清单已移除）。

```bash
# 安装依赖、建库、迁移、写入演示数据
make seed

# 启动开发服务器
make run    # http://127.0.0.1:8000/

# 单元测试
make test
```

演示账号：

| 角色 | 入口 | 账号 / 密码 |
| --- | --- | --- |
| 管理员 | `/admin/` | `admin` / `admin123` |
| 顾客 | `/account/login/` | `13800000001` / `pawstay123` |

更多说明见项目根目录 [README.md](../README.md)。
