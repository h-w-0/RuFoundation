import modules
from django.http import HttpRequest, HttpResponse

from web.middleware import CsrfViewMiddleware
from web.controllers import articles

from renderer.parser import RenderContext
from . import APIView, takes_json, APIError


class ModuleView(APIView):
    """模块调用API视图
    作用：处理前端发起的模块渲染/API调用请求，支持参数标准化、CSRF校验、异常处理
    """
    @takes_json
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """处理模块调用请求
        支持两种调用方式：
        1. render：渲染指定模块内容
        2. 其他method：调用模块的API方法（需校验CSRF）
        """
        data = self.json_input
        
        # 1. 基础参数验证
        if not data or type(data) != dict:
            raise APIError('无效的请求参数', 400)
        
        # 提取请求参数并标准化（所有key转为小写）
        module = data.get('module', None)       # 要调用的模块名称
        params = data.get('params', {})         # 模块通用参数
        path_params = data.get('pathParams', {})# 路径参数
        page_id = data.get('pageId', None)      # 关联的文章ID
        content = data.get('content', None)     # 渲染用的内容（仅render方法）
        method = data.get('method', None)       # 调用方法（render/其他API方法）
        
        # 参数key小写化，保证参数传递的一致性
        params = {key.lower(): value for (key, value) in params.items()}
        path_params = {key.lower(): value for (key, value) in path_params.items()}
        
        # 2. 加载关联文章并创建渲染上下文
        article = articles.get_article(page_id)
        # 构建渲染上下文（当前文章、源文章、路径参数、当前用户）
        context = RenderContext(article, article, path_params, request.user)
        
        # 验证文章存在性（传递了pageId但文章不存在时抛出异常）
        if page_id and not article:
            raise APIError('页面不存在', 404)
        
        # 3. 执行模块调用逻辑
        try:
            # 模块渲染请求
            if method == 'render':
                result = modules.render_module(module, context, params, content=content)
                return self.render_json(200, {'result': result})
            # 模块API方法调用
            else:
                # 调用模块API，返回响应数据和CSRF安全标记
                response, is_csrf_safe = modules.handle_api(module, method, context, params)
                
                # 非CSRF安全的请求需校验CSRF令牌
                if not is_csrf_safe:
                    # 执行CSRF验证（复用自定义CSRF中间件逻辑）
                    reason = CsrfViewMiddleware([]).process_view(request, None, (), {})
                    if reason:  # CSRF验证失败时返回验证结果
                        return reason
                
                return self.render_json(200, response)
        
        # 捕获模块调用异常并转为API异常
        except modules.ModuleError as e:
            raise APIError(e.message)
