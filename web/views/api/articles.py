import logging
from django.conf import settings
from django.http import HttpRequest, HttpResponse

from modules.sitechanges import log_entry_default_comment
from shared_data import shared_articles
from . import APIView, APIError, takes_json

from web.controllers import articles, notifications

from renderer.utils import render_user_to_json
from renderer import single_pass_render
from renderer.parser import RenderContext

import json

from web.controllers.search import update_search_index
from web.models.articles import Category, ExternalLink, Article

from modules import rate, ModuleError


class AllArticlesView(APIView):
    """所有文章列表API视图
    作用：获取当前用户有权限查看的所有文章（过滤隐藏分类）
    """
    def get(self, request: HttpRequest):
        result = []
        # 获取当前用户无权查看的隐藏分类
        hidden_categories = articles.get_hidden_categories_for(request.user)
        # 遍历所有文章，过滤隐藏分类下的内容
        for category, entries in shared_articles.get_all_articles().items():
            if category in hidden_categories:
                continue
            result.extend(entries)
        return self.render_json(200, result)


class ArticleView(APIView):
    """文章基础API视图（提供通用验证逻辑）"""
    def _validate_article_data(self, data, allow_partial=False):
        """验证文章提交数据的合法性
        :param data: 提交的文章数据
        :param allow_partial: 是否允许部分字段（用于更新操作）
        :raise APIError: 数据验证失败时抛出异常
        """
        if not data:
            raise APIError('无效的请求参数', 400)
        # 验证页面ID格式
        if 'pageId' not in data or not data['pageId'] or not articles.is_full_name_allowed(data['pageId']):
            raise APIError('无效的页面ID', 400)
        # 验证源码字段（更新操作允许不传递）
        if ('source' not in data or not (data['source'] or '').strip()) and not (
                allow_partial and 'source' not in data):
            raise APIError('缺少页面源码内容', 400)
        # 验证标题字段（更新操作允许不传递）
        if ('title' not in data or data['title'] is None) and not (allow_partial and 'title' not in data):
            raise APIError('缺少页面标题', 400)
        # 验证源码长度限制
        if 'source' in data and len(data['source']) > settings.ARTICLE_SOURCE_LIMIT:
            raise APIError('页面源码长度超出限制')

class CreateView(ArticleView):
    """文章创建API视图"""
    @takes_json
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        data = self.json_input

        # 验证创建数据
        self._validate_article_data(data)

        # 解析分类和名称，检查创建权限
        category, name = articles.get_name(data['pageId'])
        if not request.user.has_perm('roles.create_articles', Category.get_or_default_category(category)):
            raise APIError('权限不足', 403)

        # 检查页面ID是否已存在
        article = articles.get_article(data['pageId'])
        if article is not None:
            raise APIError('该页面ID已存在', 409)

        # 创建文章主体
        article = articles.create_article(articles.normalize_article_name(data['pageId']), request.user)
        article.title = data['title']
        article.save()
        # 创建文章版本记录
        version = articles.create_article_version(article, data['source'], request.user)
        # 刷新文章链接关系
        articles.refresh_article_links(version)
        
        # 设置父文章（如果传递了parent参数）
        if data.get('parent') is not None:
            articles.set_parent(article, articles.normalize_article_name(data['parent']), request.user)

        # 订阅文章通知
        notifications.subscribe_to_notifications(subscriber=request.user, article=article)

        return self.render_json(201, {'status': 'ok'})


class FetchOrUpdateView(ArticleView):
    """文章查询/更新API视图"""
    def get(self, request: HttpRequest, full_name: str) -> HttpResponse:
        """获取单篇文章详情"""
        # 检查查看权限
        category = articles.get_article_category(full_name)
        if not request.user.has_perm('roles.view_articles', category):
            raise APIError('权限不足', 403)
        # 查询文章
        article = articles.get_article(full_name)
        if article is None:
            raise APIError('页面不存在', 404)

        return self.render_article(article)

    def render_article(self, article: Article):
        """格式化文章数据为API响应格式"""
        source = articles.get_latest_source(article)
        authors = [render_user_to_json(author) for author in article.authors.all()]

        return self.render_json(200, {
            'uid': article.id,
            'pageId': articles.get_full_name(article),
            'title': article.title,
            'source': source,
            'tags': articles.get_tags(article),
            'author': authors[0],
            'authors': authors,
            'parent': articles.get_parent(article),
            'locked': article.locked
        })

    @takes_json
    def put(self, request: HttpRequest, full_name: str) -> HttpResponse:
        """更新文章信息（支持重命名、修改标题/源码/标签/父级/锁定状态/作者）"""
        # 查询文章
        article = articles.get_article(full_name)
        if article is None:
            # 即使文章不存在，也需验证查看权限（防止枚举）
            category = articles.get_article_category(full_name)
            if not request.user.has_perm('roles.view_articles', category):
                raise APIError('权限不足', 403)
            raise APIError('页面不存在', 404)

        # 检查文章编辑权限
        can_edit_articles = request.user.has_perm('roles.edit_articles', article)

        # 验证更新数据（允许部分字段）
        data = self.json_input
        self._validate_article_data(data, allow_partial=True)

        # 1. 处理重命名逻辑
        if data['pageId'] != full_name:
            new_name = articles.normalize_article_name(data['pageId'])
            new_category = articles.get_article_category(new_name)
            # 检查移动/重命名权限
            if not request.user.has_perm('roles.move_articles', article) or \
               not request.user.has_perm('roles.move_articles', new_category) if new_category else False:
                raise APIError('权限不足', 403)
            # 检查新名称是否已存在
            article2 = articles.get_article(new_name)
            if article2 is not None and article2.id != article.id and not data.get('forcePageId'):
                raise APIError('该页面ID已存在', 409)
            # 自动去重名称
            new_name = articles.deduplicate_name(new_name, article)
            articles.update_full_name(article, new_name, request.user)

        # 2. 处理标题修改
        if 'title' in data and data['title'] != article.title:
            if not can_edit_articles:
                raise APIError('权限不足', 403)
            articles.update_title(article, data['title'], request.user)

        # 3. 处理源码修改
        if 'source' in data and data['source'] != articles.get_latest_source(article):
            if not can_edit_articles:
                raise APIError('权限不足', 403)
            # 创建新版本记录
            version = articles.create_article_version(article, data['source'], request.user, data.get('comment', ''))
            articles.refresh_article_links(version)

        # 4. 处理标签修改
        if 'tags' in data:
            if not request.user.has_perm('roles.tag_articles', article):
                raise APIError('权限不足', 403)
            articles.set_tags(article, data['tags'], request.user)

        # 5. 处理父级修改
        if 'parent' in data:
            if not can_edit_articles:
                raise APIError('权限不足', 403)
            articles.set_parent(article, data['parent'], request.user)

        # 6. 处理锁定状态修改
        if 'locked' in data:
            if data['locked'] != article.locked:
                if request.user.has_perm('roles.lock_articles', article):
                    articles.set_lock(article, data['locked'], request.user)
                else:
                    raise APIError('权限不足', 403)
            
        # 7. 处理作者修改
        if 'authorsIds' in data:
            # 验证作者ID格式（列表且元素为字符串）
            if isinstance(data['authorsIds'], list) and all(map(lambda a: isinstance(a, str), data['authorsIds'])):
                if can_edit_articles and request.user.has_perm('roles.manage_article_authors', article):
                    articles.set_authors(article, data['authorsIds'], request.user)
                else:
                    raise APIError('权限不足', 403)
            else:
                raise APIError('作者ID格式无效', 400)

        # 刷新数据库数据，更新搜索索引
        article.refresh_from_db()
        update_search_index(article)
        return self.render_article(article)

    def delete(self, request: HttpRequest, full_name: str) -> HttpResponse:
        """删除文章"""
        # 查询文章
        article = articles.get_article(full_name)
        if article is None:
            # 验证查看权限（防止枚举）
            category = articles.get_article_category(full_name)
            if not request.user.has_perm('roles.view_articles', category):
                raise APIError('权限不足', 403)
            raise APIError('页面不存在', 404)

        # 检查删除权限
        if not request.user.has_perm('roles.delete_articles', article):
            raise APIError('权限不足', 403)

        # 触发删除事件，执行删除操作
        articles.OnDeleteArticle(request.user, article).emit()
        articles.delete_article(article)

        return self.render_json(200, {'status': 'ok'})


class FetchOrRevertLogView(APIView):
    """文章操作日志查询/版本回滚API视图"""
    def get(self, request: HttpRequest, full_name: str) -> HttpResponse:
        """获取文章操作日志（分页）"""
        # 检查查看权限
        category = articles.get_article_category(full_name)
        if not request.user.has_perm('roles.view_articles', category):
            raise APIError('权限不足', 403)
        # 解析分页参数
        try:
            c_from = int(request.GET.get('from', '0'))
            c_to = int(request.GET.get('to', '25'))
            get_all = bool(request.GET.get('all'))
        except ValueError:
            raise APIError('列表分页参数格式无效', 400)

        # 获取分页日志和总数量
        log_entries, total_count = articles.get_log_entries_paged(full_name, c_from, c_to, get_all)

        # 格式化日志数据
        output = []
        for entry in log_entries:
            output.append({
                'revNumber': entry.rev_number,
                'user': render_user_to_json(entry.user),
                'comment': entry.comment,
                'defaultComment': log_entry_default_comment(entry),
                'createdAt': entry.created_at.isoformat(),
                'type': entry.type,
                'meta': entry.meta
            })

        return self.render_json(200, {'count': total_count, 'entries': output})

    @takes_json
    def put(self, request: HttpRequest, full_name: str) -> HttpResponse:
        """回滚文章到指定版本"""
        # 查询文章
        article = articles.get_article(full_name)
        if article is None:
            # 验证查看权限
            category = articles.get_article_category(full_name)
            if not request.user.has_perm('roles.view_articles', category):
                raise APIError('权限不足', 403)
            raise APIError('页面不存在', 404)

        # 检查编辑权限
        if not request.user.has_perm('roles.edit_articles', article):
            raise APIError('权限不足', 403)

        data = self.json_input

        # 验证版本号参数
        if not ("revNumber" in data and isinstance(data["revNumber"], int)):
            raise APIError('无效的版本号', 400)

        # 执行版本回滚
        articles.revert_article_version(article, data["revNumber"], request.user)
        # 刷新链接关系，更新搜索索引
        version = articles.get_latest_version(article)
        articles.refresh_article_links(version)

        article.refresh_from_db()
        update_search_index(article)
        return self.render_json(200, {"pageId": article.full_name})


class FetchVersionView(APIView):
    """文章指定版本查询API视图"""
    def get(self, request: HttpRequest, full_name: str) -> HttpResponse:
        """获取文章指定版本的源码和渲染结果"""
        # 检查查看权限
        category = articles.get_article_category(full_name)
        if not request.user.has_perm('roles.view_articles', category):
            raise APIError('权限不足', 403)
        
        # 查询文章和指定版本源码
        article = articles.get_article(full_name)
        source = articles.get_source_at_rev_num(article, int(request.GET.get('revNum')))

        # 渲染并返回结果
        if source:
            context = RenderContext(article, article,
                                    json.loads(request.GET.get('pathParams', "{}")), self.request.user)
            rendered = single_pass_render(source, context)

            return self.render_json(200, {'source': source, "rendered": rendered})
        raise APIError('该版本不存在', 404)


class FetchExternalLinks(APIView):
    """文章外部链接查询API视图
    作用：获取文章的子文章、包含链接、普通链接
    """
    def get(self, request: HttpRequest, full_name: str) -> HttpResponse:
        # 检查查看权限
        category = articles.get_article_category(full_name)
        if not request.user.has_perm('roles.view_articles', category):
            raise APIError('权限不足', 403)
        
        # 查询文章
        article = articles.get_article(full_name)
        if not article:
            raise APIError('页面不存在', 404)

        # 1. 获取子文章列表
        links_children = [{'id': x.full_name, 'title': x.title, 'exists': True} for x in
                          Article.objects.filter(parent=article)]

        # 2. 获取所有指向当前文章的外部链接
        links_all = ExternalLink.objects.filter(link_to=full_name)

        links_include = []  # 包含类型链接
        links_links = []    # 普通链接

        # 批量查询链接来源文章
        articles_dict = articles.fetch_articles_by_names([link.link_from.lower() for link in links_all])

        # 格式化链接数据
        for link in links_all:
            article = articles_dict.get(link.link_from.lower())
            article_record = {'id': article.full_name, 'title': article.title, 'exists': True} if article else {
                'id': link.link_from.lower(), 'title': link.link_from.lower(), 'exists': False}
            if link.link_type == ExternalLink.Type.Include:
                links_include.append(article_record)
            elif link.link_type == ExternalLink.Type.Link:
                links_links.append(article_record)

        return self.render_json(200, {'children': links_children, 'includes': links_include, 'links': links_links})

class FetchOrUpdateVotesView(APIView):
    """文章投票查询/重置API视图"""
    def get(self, request: HttpRequest, full_name: str) -> HttpResponse:
        """获取文章投票数据"""
        # 检查查看权限
        category = articles.get_article_category(full_name)
        if not request.user.has_perm('roles.view_articles', category):
            raise APIError('权限不足', 403)
        
        # 查询文章
        article = articles.get_article(full_name)
        if not article:
            raise APIError('页面不存在', 404)

        # 获取投票数据（处理模块异常）
        try:
            return self.render_json(200, rate.api_get_votes(RenderContext(article=article, source_article=article, user=request.user), {}))
        except ModuleError as e:
            raise APIError(e.message, 500)

    def delete(self, request: HttpRequest, full_name: str) -> HttpResponse:
        """重置文章投票数据"""
        # 查询文章
        article = articles.get_article(full_name)
        if article is None:
            # 验证查看权限
            category = articles.get_article_category(full_name)
            if not request.user.has_perm('roles.view_articles', category):
                raise APIError('权限不足', 403)
            raise APIError('页面不存在', 404)

        # 检查重置投票权限
        if not request.user.has_perm('roles.reset_article_votes', article):
            raise APIError('权限不足', 403)

        # 执行投票重置
        articles.delete_article_votes(article, user=request.user)

        # 返回最新投票数据
        return self.get(request, full_name)
