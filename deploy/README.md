# 多人管理后台部署

生产环境使用单个 Gunicorn 进程和线程池，以确保本地发布任务队列及平台登录进程状态一致。Nginx 负责 HTTPS、上传大小和反向代理。

重要数据位于：

- `/opt/social-auto-upload/team_data/team.db`
- `/opt/social-auto-upload/team_data/media/`
- `/opt/social-auto-upload/cookies/`
- `/etc/sau-team.env`

上述目录和文件必须纳入服务器备份。平台账号 Cookie 不应下载或提交到 Git。
