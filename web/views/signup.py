from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import AbstractUser as _UserType
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_str
from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponseRedirect
from django.contrib.auth import login
from django.views.generic.base import TemplateResponseMixin, ContextMixin, View

import re

from web.models.users import UsedToken
from .invite import account_activation_token
from web.events import EventBase


User = get_user_model()


class OnUserSignUp(EventBase, name='on_user_signup'):
    """用户注册完成事件"""
    request: HttpRequest
    user: _UserType

class AcceptInvitationView(TemplateResponseMixin, ContextMixin, View):
    """接受邀请注册视图（处理用户通过邀请链接完成注册/激活）"""
    template_name = "signup/accept.html"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_user(self):
        """从URL的uidb64参数解析并获取对应的用户对象"""
        try:
            uid = force_str(urlsafe_base64_decode(self.kwargs["uidb64"]))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            # 解析失败或用户不存在时返回None
            user = None
        return user

    def get(self, request, *args, **kwargs):
        """处理GET请求：展示邀请注册页面（仅未登录用户可访问）"""
        # 已登录用户直接重定向到登录后页面
        if not isinstance(request.user, AnonymousUser):
            return HttpResponseRedirect(redirect_to=settings.LOGIN_REDIRECT_URL)
        
        path = request.META['RAW_PATH'][1:]
        context = self.get_context_data(path=path)
        user = self.get_user()
        
        # 验证邀请令牌是否有效（未被使用且未过期）
        if UsedToken.is_used(self.kwargs['token']) or not account_activation_token.check_token(user, self.kwargs["token"]):
            context.update({'error': '无效的邀请链接。', 'error_fatal': True})
            return self.render_to_response(context)
        
        # Wikidot类型用户补充上下文数据
        if user.type == User.UserType.Wikidot:
            context.update({'is_wikidot': True, 'username': user.wikidot_username})
        
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        """处理POST请求：完成邀请注册（设置密码、激活账号）"""
        path = request.META['RAW_PATH'][1:]
        context = self.get_context_data(path=path)
        user = self.get_user()
        
        # 再次验证邀请令牌有效性
        if UsedToken.is_used(self.kwargs['token']) or not account_activation_token.check_token(user, self.kwargs["token"]):
            context.update({'error': '无效的邀请链接。', 'error_fatal': True})
            return self.render_to_response(context)
        
        # 区分Wikidot用户和普通用户的用户名处理
        if user.type == User.UserType.Wikidot:
            username = user.wikidot_username
            context.update({'is_wikidot': True})
        else:
            username = request.POST.get('username', '').strip()
        context.update({'username': username})
        
        # 获取并验证密码
        password1 = request.POST.get('password', '')
        password2 = request.POST.get('password2', '')
        
        # 验证用户名格式（仅允许字母、数字、-、_、.）
        if not re.match(r"^[\w.-]+\Z", username, re.ASCII):
            context.update({'error': '用户名格式无效。允许使用的字符：A-Z、a-z、0-9、-、_、.。'})
            return self.render_to_response(context)
        
        # 检查用户名是否已被占用
        user_exists = User.objects.filter(username=username)
        wd_user_exists = User.objects.filter(wikidot_username=username)
        if (user_exists and user_exists[0] != user) or (wd_user_exists and wd_user_exists[0] != user):
            context.update({'error': '该用户名已被使用。'})
            return self.render_to_response(context)
        
        # 密码非空验证
        if not password1:
            context.update({'error': '请设置密码。'})
            return self.render_to_response(context)
        
        # 两次密码一致性验证
        if password1 != password2:
            context.update({'error': '两次输入的密码不一致。'})
            return self.render_to_response(context)
        
        # 更新用户信息并激活账号
        if user.type != User.UserType.Wikidot:
            user.username = username
        else:
            # Wikidot用户转为普通用户，用户名沿用wikidot_username
            user.username = user.wikidot_username
            user.type = User.UserType.Normal
        
        user.set_password(password1)  # 设置加密密码
        user.is_active = True  # 激活账号
        user.save()
        
        # 标记令牌已使用（防止重复使用）
        UsedToken.mark_used(self.kwargs['token'], is_case_sensitive=True)
        
        # 自动登录用户
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        
        # 触发用户注册完成事件
        OnUserSignUp(request, user).emit()
        
        # 重定向到登录后页面
        return HttpResponseRedirect(redirect_to=settings.LOGIN_REDIRECT_URL)
