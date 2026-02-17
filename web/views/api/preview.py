import urllib

from django.http import HttpRequest, HttpResponse

from . import APIView, APIError, takes_json

from renderer import single_pass_render
from renderer.parser import RenderContext

from web.controllers import articles

from web.views.article import ArticleView
from renderer.templates import apply_template
from modules.listpages import page_to_listpages_vars, get_page_vars
from ...models import get_current_site


class PreviewView(APIView):
    """文章预览API视图
    作用：处理文章预览请求，渲染文章源码+模板，返回预览内容、标题和样式
    """
    def _validate_preview_data(self):
        """验证预览请求的参数合法性
        :raise APIError: 参数无效时抛出异常
        """
        if not self.json_input:
            raise APIError('无效的请求参数', 400)
        # 验证页面ID格式
        if 'pageId' not in self.json_input or not self.json_input['pageId'] or not articles.is_full_name_allowed(self.json_input['pageId']):
            raise APIError('无效的页面ID', 400)
        # 验证源码字段
        if 'source' not in self.json_input:
            raise APIError('缺少页面源码内容', 400)

    @takes_json
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """生成文章预览内容
        流程：参数验证 → 加载文章/模板 → 构建URL → 渲染模板 → 返回预览结果
        """
        data = self.json_input
        # 1. 验证预览参数
        self._validate_preview_data()
        
        # 2. 提取预览参数
        article = articles.get_article(data['pageId'])  # 查询关联文章（可能不存在）
        path_params = data.get('pathParams', {})        # 路径参数（默认空字典）
        title = data.get('title', '')                   # 文章标题（默认空）
        source = data['source']                         # 文章源码内容

        # 3. 构建模板渲染参数
        template_page_vars = get_page_vars(article)     # 获取文章模板变量
        template_page_vars['content'] = source          # 将源码注入模板变量

        # 4. 加载分类模板（默认使用%%content%%占位符）
        template_source = '%%content%%'
        # 非模板文章时，尝试加载分类下的_template文章作为模板
        if article is not None and article.name != '_template':
            template = articles.get_article(f'{article.category}:_template')
            if template:
                template_source = articles.get_latest_source(template)

        # 5. 构建规范URL（包含路径参数）
        site = get_current_site()
        encoded_params = ''
        # 拼接URL编码的路径参数
        for param in path_params:
            encoded_params += f'/{param}'
            if path_params[param] is not None:
                # 对参数值进行URL编码（保留安全字符）
                encoded_params += f"/{urllib.parse.quote(path_params[param], safe='')}"
        # 拼接完整规范URL（//域名/文章全名/参数）
        canonical_url = f'//{site.domain}/{article.full_name if article else data["pageId"]}{encoded_params}'

        # 6. 模板变量替换与渲染
        # 处理列表页面变量
        source = page_to_listpages_vars(article, template_source, index=1, total=1, page_vars=template_page_vars)
        # 应用模板参数（注入规范URL等）
        source = apply_template(
            source, 
            lambda param: ArticleView.get_this_page_params(path_params, param, {'canonical_url': canonical_url})
        )
        # 创建渲染上下文（关联文章、路径参数、当前用户）
        context = RenderContext(article, article, path_params, self.request.user)
        # 单遍渲染生成最终预览内容
        content = single_pass_render(source, context)

        # 7. 返回预览结果（标题、内容、样式）
        return self.render_json(200, {
            'title': title, 
            'content': content, 
            'style': context.computed_style
        })
