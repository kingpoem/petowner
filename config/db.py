"""在导入 Django 前将 PyMySQL 注册为 MySQLdb，避免容器内编译 mysqlclient。"""

import pymysql

pymysql.install_as_MySQLdb()
