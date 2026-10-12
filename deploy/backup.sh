#!/bin/bash
# 每天 BACKUP_AT（容器时区 TZ）导出 MySQL 与上传文件到 /backups，并删除超过 BACKUP_KEEP_DAYS 天的旧备份。
# 立即备份一次：make docker-backup
set -euo pipefail

AT="${BACKUP_AT:-03:30}"
KEEP="${BACKUP_KEEP_DAYS:-7}"
DIR=/backups

backup() {
    local stamp tmp
    stamp=$(date +%Y%m%d-%H%M%S)
    tmp="$DIR/.db-$stamp.sql.gz.part"
    MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -h db -uroot --single-transaction --quick --routines --triggers \
        --no-tablespaces --set-gtid-purged=OFF --databases "$MYSQL_DATABASE" | gzip > "$tmp"
    mv "$tmp" "$DIR/db-$stamp.sql.gz"
    tar -czf "$DIR/media-$stamp.tar.gz" -C /data media
    find "$DIR" -maxdepth 1 \( -name 'db-*.sql.gz' -o -name 'media-*.tar.gz' \) -mtime +"$((KEEP - 1))" -delete
    find "$DIR" -maxdepth 1 -name '.db-*.part' -mmin +60 -delete
    echo "$(date '+%F %T') 备份完成：db-$stamp.sql.gz、media-$stamp.tar.gz（保留 $KEEP 天）"
}

mkdir -p "$DIR"
if [ "${1:-}" = "once" ]; then
    backup
    exit
fi

echo "$(date '+%F %T') 备份服务已启动：每天 $AT 执行，保留 $KEEP 天"
while true; do
    now=$(date +%s)
    next=$(date -d "today $AT" +%s)
    [ "$next" -le "$now" ] && next=$(date -d "tomorrow $AT" +%s)
    sleep $((next - now))
    backup || echo "$(date '+%F %T') 备份失败，请检查数据库连接与磁盘空间" >&2
done
