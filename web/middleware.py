from django.conf import settings
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from django.shortcuts import render

from web.models.site import Site
from web import threadvars

import logging
import django.middleware.csrf
import urllib.parse


User = get_user_model()

class BotAuthTokenMiddleware(object):
    """机器人令牌认证中间件
    作用：通过请求头中的Bearer Token验证机器人账号身份，跳过CSRF验证
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 检查请求头中是否包含Authorization且以Bearer开头
        if "Authorization" in request.headers and request.headers["Authorization"].startswith("Bearer "):
            try:
                # 提取Token并匹配机器人用户（type=bot）的api_key
                request.user = User.objects.get(type="bot", api_key=request.headers["Authorization"][7:])
                # 标记CSRF验证已完成，跳过后续CSRF检查
                setattr(request, 'csrf_processing_done', True)
            except User.DoesNotExist:
                # Token无效时不做处理，继续走正常认证流程
                pass
        return self.get_response(request)


class FixRawPathMiddleware(object):
    """RAW_PATH修复中间件
    作用：统一请求的RAW_PATH参数，避免因环境差异导致的路径缺失问题
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 标准化META中的路径参数
        # 优先级：RAW_PATH > RAW_URI解析 > 默认request.path
        if 'RAW_PATH' not in request.META:
            if 'RAW_URI' in request.META:
                # 从RAW_URI中解析出路径部分
                parsed = urllib.parse.urlparse(request.META['RAW_URI'])
                request.META['RAW_PATH'] = parsed.path
            else:
                # 兜底使用默认path（虽可能不准确，但避免程序崩溃）
                request.META['RAW_PATH'] = request.path

        return self.get_response(request)


# 该中间件用于重定向跨域名访问媒体文件的请求（媒体域名↔主域名），保障Cookie安全
class MediaHostMiddleware(object):
    """媒体域名重定向中间件
    核心：确保媒体文件仅通过媒体域名访问，普通页面仅通过主域名访问，防止Cookie泄露
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 设置当前站点上下文（线程隔离）
        with threadvars.context():
            # 第一步：根据请求域名匹配对应的Site实例
            raw_host = request.get_host()
            # 补充端口号（确保域名+端口的完整匹配）
            if ':' not in raw_host and 'SERVER_PORT' in request.META:
                raw_host += ':' + request.META['SERVER_PORT']
                possible_sites = Site.objects.filter(Q(domain=raw_host) | Q(media_domain=raw_host))
            else:
                possible_sites = []
            
            # 无匹配结果时，尝试仅匹配域名（忽略端口）
            if not possible_sites:
                raw_host = request.get_host().split(':')[0]
                possible_sites = Site.objects.filter(Q(domain=raw_host) | Q(media_domain=raw_host))
                
                # 仍无匹配时的异常处理
                if not possible_sites:
                    if Site.objects.exists():
                        logging.warning(f'该域名（{raw_host}）未配置站点信息')
                        raise PermissionDenied()  # 拒绝访问
                    else:
                        # 无任何站点配置时，返回提示页面
                        return render(request, 'no_site.html')

            # 取第一个匹配的站点作为当前站点
            site = possible_sites[0]
            threadvars.put('current_site', site)

            # 第二步：判断当前请求是否为媒体域名/媒体路径
            # 判断是否访问媒体域名（忽略端口）
            is_media_host = request.get_host().split(':')[0] == site.media_domain
            # 定义媒体文件路径前缀（匹配这些前缀的视为媒体请求）
            media_prefixes = ['local--files', 'local--code', 'local--html', 'local--theme']
            # 判断当前请求路径是否为媒体路径
            is_media_url = bool([x for x in media_prefixes if request.path.startswith(f'/{x}/')])

            # 第三步：跨域名访问时重定向（主域名≠媒体域名时生效）
            if site.media_domain != site.domain:
                non_media_host = site.domain

                # 媒体域名访问非媒体路径 → 重定向到主域名
                if is_media_host and not is_media_url:
                    return HttpResponseRedirect(f'//{non_media_host}{request.get_full_path()}')
                # 主域名访问媒体路径 → 重定向到媒体域名
                elif not is_media_host and is_media_url:
                    return HttpResponseRedirect(f'//{site.media_domain}{request.get_full_path()}')

            # 处理请求并获取响应
            response = self.get_response(request)

            # 第四步：设置响应头（保障安全/跨域）
            if is_media_host or (site.domain == site.media_domain and is_media_url):
                # 媒体文件允许跨域访问
                response['Access-Control-Allow-Origin'] = '*'
            else:
                # 普通页面添加安全响应头
                response['X-Content-Type-Options'] = 'nosniff'  # 防止MIME类型嗅探
                response['X-Frame-Options'] = 'DENY'  # 禁止嵌入iframe

            return response


class UserContextMiddleware(object):
    """用户上下文中间件
    作用：将当前请求的用户对象存入线程变量，供全局调用
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        threadvars.put('current_user', request.user)
        return self.get_response(request)


class CsrfViewMiddleware(django.middleware.csrf.CsrfViewMiddleware):
    """自定义CSRF防护中间件
    扩展：动态配置CSRF可信源，适配多站点域名
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = None

    @property
    def csrf_trusted_origins_hosts(self):
        """获取所有站点的主域名作为CSRF可信源"""
        return [site.domain for site in Site.objects.all()]

    @property
    def allowed_origins_exact(self):
        """生成精确匹配的允许源列表（包含不同协议/端口）"""
        port = ':' + str(self.request.META['SERVER_PORT'])
        hosts = self.csrf_trusted_origins_hosts
        return \
            [f'http://{host}{port}' for host in hosts] +\
            [f'http://{host}' for host in hosts] +\
            [f'https://{host}' for host in hosts]

    @property
    def allowed_origin_subdomains(self):
        """子域名允许列表（此处暂为空）"""
        return dict()

    def process_view(self, request, callback, callback_args, callback_kwargs):
        """重写视图处理方法，绑定当前请求对象"""
        self.request = request
        return super().process_view(request, callback, callback_args, callback_kwargs)


class ForwardedPortMiddleware(object):
    """转发端口清理中间件
    作用：移除HTTP_HOST中的端口号，统一域名格式
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 仅保留域名部分，移除端口号
        request.META['HTTP_HOST'] = request.META['HTTP_HOST'].split(':')[0]
        return self.get_response(request)


class DropWikidotAuthMiddleware(object):
    """Wikidot认证Cookie清理中间件
    作用：删除所有Wikidot相关的认证Cookie，避免认证冲突
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # 遍历所有Cookie，删除Wikidot相关的认证Cookie
        for cookie in request.COOKIES:
            # 匹配固定名称的Wikidot Cookie
            if cookie in ['wikidot_token7', 'wikidot_udsession', 'WIKIDOT_SESSION_ID']:
                response.delete_cookie(cookie, path='/')
            # 匹配以WIKIDOT_SESSION_ID_开头的Cookie
            if cookie.startswith('WIKIDOT_SESSION_ID_'):
                response.delete_cookie(cookie, path='/')
        return response


class SpyRequestMiddleware(object):
    """请求监控中间件
    作用：记录当前请求对象和客户端真实IP，存入线程变量供日志/审计使用
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with threadvars.context():
            # 获取客户端真实IP（优先取X-Forwarded-For，兼容反向代理）
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0]  # 取第一个IP（避免代理层多IP）
            else:
                ip = request.META.get('REMOTE_ADDR')  # 兜底取远程IP

            # 将请求对象和IP存入线程变量
            threadvars.put('current_request', request)
            threadvars.put('current_client_ip', ip)
            return self.get_response(request)
