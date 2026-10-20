"""在导入 Django 前将 PyMySQL 注册为 MySQLdb，这样 Windows 本机无需编译 mysqlclient。"""

import pymysql

pymysql.install_as_MySQLdb()
