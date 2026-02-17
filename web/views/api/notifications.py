from django.http import HttpRequest

from renderer import single_pass_render
from renderer.parser import RenderContext
from web.controllers import articles, notifications
from web.models.forum import ForumThread
from web.models.notifications import UserNotification
from web.views.api import APIError, APIView, takes_json, takes_url_params


class NotificationsView(APIView):
    """通知列表API视图
    作用：查询用户的通知列表，支持分页、筛选未读、标记已读，渲染通知内容
    """
    @staticmethod
    def _replace_params(text: str, params: dict):
        """替换文本中的参数占位符
        :param text: 包含%%参数名%%占位符的文本
        :param params: 参数键值对
        :return: 替换后的文本
        """
        for param, value in params.items():
            text = text.replace(f'%%{param}%%', str(value))
        return text

    def render_notification(self, notification: UserNotification, is_viewed: bool, render_context: RenderContext):
        """格式化通知数据为API响应格式
        :param notification: 用户通知对象
        :param is_viewed: 是否已读
        :param render_context: 渲染上下文
        :return: 格式化后的通知字典
        """
        # 基础通知数据（ID、类型、创建时间、已读状态 + 元数据）
        base_notification = dict(**{
            'id': notification.id,
            'type': notification.type,
            'created_at': notification.created_at.isoformat(),
            'is_viewed': is_viewed,
        }, **notification.meta)

        # 对论坛相关通知渲染消息内容
        forum_notification_types = [
            UserNotification.NotificationType.NewThreadPost,  # 新帖子
            UserNotification.NotificationType.NewPostReply,   # 新回复
            UserNotification.NotificationType.ForumMention    # 论坛@提及
        ]
        if notification.type in forum_notification_types:
            # 渲染通知消息内容（使用单遍渲染模式）
            base_notification['message'] = single_pass_render(
                base_notification['message_source'], 
                render_context, 
                mode='message'
            ),

        return base_notification

    @takes_url_params
    def get(self, request: HttpRequest, *, cursor: int=-1, limit: int=10, unread: bool=False, mark_as_viewed: bool=False):
        """获取用户通知列表（支持分页、筛选、标记已读）
        :param cursor: 分页游标（最后一条通知ID），默认-1（从头开始）
        :param limit: 每页条数，默认10
        :param unread: 是否仅显示未读通知，默认False
        :param mark_as_viewed: 是否自动标记为已读，默认False
        """
        # 创建渲染上下文（无关联文章，仅传递当前用户）
        render_context = RenderContext(None, None, {}, request.user)
        all_notifications = []

        # 获取分页通知列表
        notifications_batch = notifications.get_notifications(
            request.user, 
            cursor=cursor, 
            limit=limit, 
            unread=unread, 
            mark_as_viewed=mark_as_viewed
        )

        # 格式化每条通知数据
        for notification, is_viewed in notifications_batch:
            all_notifications.append(self.render_notification(notification, is_viewed, render_context))
        
        # 构造分页响应（返回下一页游标和通知列表）
        next_cursor = all_notifications[-1]['id'] if all_notifications else -1
        return self.render_json(
            200, {'cursor': next_cursor, 'notifications': all_notifications}
        )


class NotificationsSubscribeView(APIView):
    """通知订阅/取消订阅API视图"""
    @staticmethod
    def _get_subscription_info(data: dict):
        """解析订阅参数，获取文章/论坛帖子信息
        :param data: 请求参数
        :return: 包含article/forum_thread的参数字典
        :raise APIError: 参数无效时抛出异常
        """
        article_name = data.get('pageId')    # 文章ID
        thread_id = data.get('forumThreadId')# 论坛帖子ID

        args = {}

        # 订阅文章通知
        if article_name:
            article = articles.get_article(article_name)
            args.update({'article': article})
        # 订阅论坛帖子通知
        elif thread_id:
            forum_thread = ForumThread.objects.filter(id=thread_id).first()
            args.update({'forum_thread': forum_thread})
        # 无有效参数
        else:
            raise APIError('无效的订阅参数', 400)

        return args
    
    @staticmethod
    def _verify_access(request: HttpRequest, args):
        """验证用户对订阅对象的访问权限
        :param request: 当前请求对象
        :param args: 包含article/forum_thread的参数字典
        :raise APIError: 权限不足时抛出异常
        """
        # 验证文章查看权限
        if args.get('article') and not request.user.has_perm('roles.view_articles', args.get('article')):
            raise APIError('权限不足', 403)
        # 验证论坛帖子查看权限
        if args.get('forum_thread') and not request.user.has_perm('roles.view_forum_threads', args.get('forum_thread')):
            raise APIError('权限不足', 403)

    @takes_json
    def post(self, request: HttpRequest, *args, **kwargs):
        """订阅文章/论坛帖子通知"""
        # 解析订阅参数
        args = self._get_subscription_info(self.json_input)
        # 验证访问权限
        self._verify_access(request, args)
        # 执行订阅操作
        subscription = notifications.subscribe_to_notifications(request.user, **args)

        if subscription:
            return self.render_json(200, {'status': 'ok'})
        else:
            raise APIError('订阅通知失败', 400)
    
    @takes_json
    def delete(self, request: HttpRequest, *args, **kwargs):
        """取消订阅文章/论坛帖子通知"""
        # 解析订阅参数
        args = self._get_subscription_info(self.json_input)
        # 验证访问权限
        self._verify_access(request, args)
        # 执行取消订阅操作
        subscription = notifications.unsubscribe_from_notifications(request.user, **args)

        if subscription:
            return self.render_json(200, {'status': 'ok'})
        else:
            raise APIError('该订阅不存在', 404)
